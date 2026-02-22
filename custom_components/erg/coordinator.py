"""DataUpdateCoordinator for the Erg Energy Scheduler integration."""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ErgApiClient, ErgApiError
from .const import (
    DEFAULT_EXTEND_TO_END_OF_DAY,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_SLOT_DURATION,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    format_duration_seconds,
    parse_slot_duration_seconds,
)
from .job_entities import job_entity_to_dict
from .jobs import expand_recurring_jobs
from .tariff_periods import expand_recurring_tariffs
from .solar import get_solar_forecast, solar_forecast_to_boxes

_LOGGER = logging.getLogger(__name__)


def resolve_soc_kwh(
    soc_value: float,
    unit_of_measurement: str,
    battery_capacity: float,
) -> float:
    """Convert a battery SoC reading to kWh.

    If the sensor's unit is '%', treat the value as a percentage of
    *battery_capacity*.  Otherwise assume the value is already in kWh.
    """
    if unit_of_measurement == "%":
        return (soc_value / 100.0) * battery_capacity
    return soc_value


class ErgScheduleCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Coordinator that assembles state, calls the Erg API, and returns the schedule."""

    def __init__(
        self,
        hass: HomeAssistant,
        config_entry: ConfigEntry,
        api_client: ErgApiClient,
    ) -> None:
        interval_minutes = config_entry.options.get(
            "update_interval", DEFAULT_UPDATE_INTERVAL_MINUTES
        )
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(minutes=interval_minutes),
        )
        self.api_client = api_client
        self.config_entry = config_entry
        self._elapsed_today: dict[str, float] = {}
        self._last_elapsed_update: datetime | None = None
        self._tracking_date: date | None = None

    def get_elapsed(self, entity_id: str) -> float:
        """Return elapsed seconds for *entity_id* today."""
        return self._elapsed_today.get(entity_id, 0)

    def set_elapsed(self, entity_id: str, seconds: float) -> None:
        """Set elapsed seconds for *entity_id* today."""
        self._elapsed_today[entity_id] = seconds

    def _update_elapsed(self, now: datetime, slot_seconds: int) -> None:
        """Accumulate elapsed slot-seconds from the previous schedule.

        Scans self.data for slots whose end time falls between
        _last_elapsed_update and now, adding their duration to
        _elapsed_today per entity. Resets counters on date change.
        """
        today = now.date()
        if self._tracking_date is None or today != self._tracking_date:
            self._elapsed_today = {}
            self._tracking_date = today
            self._last_elapsed_update = now
            return

        if self.data is None or self._last_elapsed_update is None:
            self._last_elapsed_update = now
            return

        slot_duration = timedelta(seconds=slot_seconds)
        window_start = self._last_elapsed_update
        window_end = now

        for assignment in self.data.get("assignments", []):
            entity_id = assignment.get("entity", "")
            if entity_id.startswith("__"):
                continue
            for slot_str in assignment.get("slots", []):
                slot_end = datetime.fromisoformat(slot_str) + slot_duration
                if window_start < slot_end <= window_end:
                    self._elapsed_today[entity_id] = (
                        self._elapsed_today.get(entity_id, 0) + slot_seconds
                    )

        self._last_elapsed_update = now

    def _find_active_runs(
        self, now: datetime, slot_seconds: int
    ) -> dict[str, list[str]]:
        """Find entities with currently-active slots and their contiguous forward runs.

        Returns {entity_id: [preserved_slot_iso_strings]}.
        """
        if self.data is None:
            return {}

        slot_duration = timedelta(seconds=slot_seconds)
        result: dict[str, list[str]] = {}

        for assignment in self.data.get("assignments", []):
            entity_id = assignment.get("entity", "")
            if entity_id.startswith("__"):
                continue

            slots = assignment.get("slots", [])
            if not slots:
                continue

            parsed = sorted((datetime.fromisoformat(s), s) for s in slots)

            active_idx = None
            for i, (slot_start, _) in enumerate(parsed):
                if slot_start <= now < slot_start + slot_duration:
                    active_idx = i
                    break

            if active_idx is None:
                continue

            contiguous = [parsed[active_idx][1]]
            for i in range(active_idx + 1, len(parsed)):
                prev_start = parsed[i - 1][0]
                curr_start = parsed[i][0]
                if curr_start == prev_start + slot_duration:
                    contiguous.append(parsed[i][1])
                else:
                    break

            result[entity_id] = contiguous

        return result

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Erg scheduler."""
        opts = self.config_entry.options
        now = datetime.now().astimezone()
        local_tz = now.tzinfo

        slot_duration_str = opts.get("slot_duration", DEFAULT_SLOT_DURATION)
        slot_seconds = parse_slot_duration_seconds(slot_duration_str)
        self._update_elapsed(now, slot_seconds)

        horizon_hours = opts.get("horizon_hours", DEFAULT_HORIZON_HOURS)
        horizon_start = now
        horizon_end = now + timedelta(hours=horizon_hours)
        if opts.get("extend_to_end_of_day", DEFAULT_EXTEND_TO_END_OF_DAY):
            end_of_day = (horizon_end + timedelta(days=1)).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            horizon_end = end_of_day

        # 1. Read battery state of charge
        soc_kwh = 0.0
        battery_capacity = opts.get("battery_capacity", 0.0)
        soc_entity = opts.get("battery_soc_entity", "")
        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    soc_value = float(state.state)
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Could not parse battery SoC from %s: %s",
                        soc_entity,
                        state.state,
                    )
                else:
                    unit = state.attributes.get("unit_of_measurement", "")
                    soc_kwh = resolve_soc_kwh(
                        soc_value, unit, battery_capacity
                    )

        # 2. Expand recurring tariff definitions into absolute periods
        raw_tariffs = opts.get("tariff_periods", [])
        tariff_periods = expand_recurring_tariffs(
            raw_tariffs, horizon_start, horizon_end, local_tz
        )

        # 3. Solar forecast
        solar_boxes: list[dict[str, Any]] = []
        solar_provider = opts.get("solar_forecast_provider", "none")
        if solar_provider != "none":
            try:
                wh_hours = await get_solar_forecast(self.hass)
                solar_boxes = solar_forecast_to_boxes(
                    wh_hours, horizon_start, horizon_end
                )
            except Exception:
                _LOGGER.warning("Failed to retrieve solar forecast", exc_info=True)

        # 4. Expand recurring jobs (read from live job entities)
        job_entities = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        ).get("job_entities", {})
        jobs = [job_entity_to_dict(e) for e in job_entities.values()]
        job_boxes = expand_recurring_jobs(jobs, horizon_start, horizon_end, local_tz)

        # 5. Merge all boxes
        all_boxes = solar_boxes + job_boxes

        # 5b. Adjust boxes for elapsed time and active runs
        active_runs = self._find_active_runs(now, slot_seconds)
        slot_td = timedelta(seconds=slot_seconds)

        adjusted_boxes: list[dict[str, Any]] = []
        for box in all_boxes:
            entity_id = box["entity"]
            if entity_id.startswith("__"):
                adjusted_boxes.append(box)
                continue

            # Forced boxes must always be submitted so the scheduler
            # can model their power draw — skip elapsed adjustment.
            if box.get("force"):
                adjusted_boxes.append(box)
                continue

            # Only deduct elapsed from today's boxes
            box_start = datetime.fromisoformat(box["start_time"])
            if box_start.date() != self._tracking_date:
                adjusted_boxes.append(box)
                continue

            elapsed = self._elapsed_today.get(entity_id, 0)
            preserved_slots = active_runs.get(entity_id, [])
            preserved_seconds = len(preserved_slots) * slot_seconds

            max_secs = parse_slot_duration_seconds(box["maximum_duration"])
            remaining = max(0, max_secs - elapsed - preserved_seconds)

            if remaining <= 0 and not preserved_slots:
                continue  # budget exhausted, exclude from API request

            if preserved_slots:
                last_preserved = max(
                    datetime.fromisoformat(s) for s in preserved_slots
                )
                box["start_time"] = (last_preserved + slot_td).isoformat()

            # Cap remaining at the available window. A job cannot run
            # longer than its window, and sending a budget that exceeds
            # the window causes incorrect power scaling in the scheduler.
            effective_start = datetime.fromisoformat(box["start_time"])
            box_finish = datetime.fromisoformat(box["finish_time"])
            window_secs = max(
                0, int((box_finish - effective_start).total_seconds())
            )
            remaining = min(remaining, window_secs)

            box["maximum_duration"] = format_duration_seconds(int(remaining))

            adjusted_boxes.append(box)

        all_boxes = adjusted_boxes

        # 5c. Inject forced boxes for Erg-managed entities that are currently ON
        # but were not included in the submitted boxes. This ensures the scheduler
        # models their power draw for accurate battery SoC projection.
        submitted_entities = {b["entity"] for b in all_boxes}
        update_interval_secs = int(
            opts.get("update_interval", DEFAULT_UPDATE_INTERVAL_MINUTES) * 60
        )
        update_duration = format_duration_seconds(update_interval_secs)

        for entity in job_entities.values():
            attrs = entity.extra_state_attributes
            entity_id = attrs.get("entity_id", "")
            if not entity_id or entity_id in submitted_entities:
                continue

            state = self.hass.states.get(entity_id)
            if state is None or state.state != "on":
                continue

            ac = attrs.get("ac_power", 0.0)
            dc = attrs.get("dc_power", 0.0)
            if ac == 0 and dc == 0:
                continue

            _LOGGER.debug(
                "Injecting active load for %s (ac=%.2f kW, dc=%.2f kW)",
                entity_id, ac, dc,
            )
            all_boxes.append({
                "entity": f"__active_{entity_id}__",
                "start_time": horizon_start.isoformat(),
                "finish_time": (horizon_start + timedelta(seconds=update_interval_secs)).isoformat(),
                "maximum_duration": update_duration,
                "minimum_duration": update_duration,
                "minimum_burst": update_duration,
                "ac_power": ac,
                "dc_power": dc,
                "force": True,
                "benefit": 0,
            })

        # 6. Build API request matching Go ScheduleRequest schema
        slot_duration = opts.get("slot_duration", DEFAULT_SLOT_DURATION)
        request: dict[str, Any] = {
            "system": {
                "grid_import_limit": opts.get("grid_import_limit", 10.0),
                "grid_export_limit": opts.get("grid_export_limit", 5.0),
                "inverter_power": opts.get("inverter_power", 5.0),
                "battery_capacity": battery_capacity,
                "state_of_charge": soc_kwh,
                "battery_storage_value_per_kilowatt_hour": opts.get(
                    "battery_storage_value", 0.0
                ),
                "battery_preservation": opts.get("battery_preservation", 0.0),
            },
            "tariff": {
                "periods": tariff_periods,
            },
            "boxes": all_boxes,
            "horizon": {
                "start": horizon_start.isoformat(),
                "end": horizon_end.isoformat(),
                "slot_duration": slot_duration,
            },
        }

        # 7. Call the API
        try:
            result = await self.api_client.schedule(request)
        except ErgApiError as err:
            forced = [
                b["entity"]
                for b in all_boxes
                if b.get("force") and not b["entity"].startswith("__")
            ]
            summary = f"{len(all_boxes)} jobs ({len(forced)} forced)"
            if forced:
                summary += f": {', '.join(forced)}"
            raise UpdateFailed(
                f"Erg schedule failed with {summary}. {err}"
            ) from err

        # 8. Merge preserved active-run slots into API response
        if active_runs:
            assignments = result.get("assignments", [])

            for entity_id, preserved_slots in active_runs.items():
                # Find the first assignment for this entity
                target = None
                for a in assignments:
                    if a["entity"] == entity_id:
                        target = a
                        break

                if target is not None:
                    target["slots"] = preserved_slots + target.get("slots", [])
                    target["run_time_seconds"] = (
                        target.get("run_time_seconds", 0)
                        + len(preserved_slots) * slot_seconds
                    )
                else:
                    assignments.append({
                        "entity": entity_id,
                        "slots": preserved_slots,
                        "run_time_seconds": len(preserved_slots) * slot_seconds,
                        "energy_cost": 0,
                    })
            result["assignments"] = assignments

        # 9. Return the parsed response
        return result
