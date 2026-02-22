"""DataUpdateCoordinator for the Erg Energy Scheduler integration."""

from __future__ import annotations

import asyncio
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

_SCHEDULE_POLL_INTERVAL = 2  # seconds between polls
_SCHEDULE_POLL_MAX_ATTEMPTS = 60  # 2-minute total timeout


def _extend_tariff_coverage(
    periods: list[dict[str, Any]],
    horizon_start: datetime,
    horizon_end: datetime,
) -> list[dict[str, Any]]:
    """Extend tariff periods so they cover the full scheduling horizon.

    If the earliest period starts after ``horizon_start``, its start is
    moved backward.  If the latest period ends before ``horizon_end``,
    its end is moved forward.  This prevents zero-price gaps at the
    edges of the horizon where the solver would otherwise get free
    electricity.
    """
    if not periods:
        return periods

    # Sort by start time so first/last are the temporal edges.
    try:
        sorted_periods = sorted(
            periods, key=lambda p: datetime.fromisoformat(p["start"])
        )
    except (ValueError, TypeError, KeyError):
        return periods

    first = sorted_periods[0]
    last = sorted_periods[-1]

    try:
        first_start = datetime.fromisoformat(first["start"])
        last_end = datetime.fromisoformat(last["end"])
    except (ValueError, TypeError, KeyError):
        return sorted_periods

    if first_start > horizon_start:
        first["start"] = horizon_start.isoformat()
    if last_end < horizon_end:
        last["end"] = horizon_end.isoformat()

    return sorted_periods


def _merge_aemo_with_manual(
    aemo_periods: list[dict[str, Any]],
    manual_periods: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge AEMO wholesale prices with manual tariff offsets.

    Manual tariff periods represent time-varying non-wholesale components
    (network charges, retailer margin, feed-in rebates, etc.). Each AEMO
    30-minute period's wholesale price is added to the manual tariff that
    covers the same time, producing the total price the consumer actually
    pays or receives.

    When no manual tariff covers an AEMO period, the wholesale price is
    used alone (offset of zero).
    """
    # Pre-parse manual period boundaries for lookup
    parsed_manual: list[tuple[datetime, datetime, float, float]] = []
    for m in manual_periods:
        try:
            ms = datetime.fromisoformat(m["start"])
            me = datetime.fromisoformat(m["end"])
        except (ValueError, TypeError, KeyError):
            continue
        parsed_manual.append((
            ms, me, m.get("import_price", 0.0), m.get("feed_in_price", 0.0)
        ))

    result: list[dict[str, Any]] = []
    for aemo in aemo_periods:
        try:
            aemo_start = datetime.fromisoformat(aemo["start"])
        except (ValueError, TypeError, KeyError):
            continue

        import_offset = 0.0
        feed_in_offset = 0.0
        for ms, me, m_import, m_feedin in parsed_manual:
            if ms <= aemo_start < me:
                import_offset = m_import
                feed_in_offset = m_feedin
                break

        result.append({
            "start": aemo["start"],
            "end": aemo["end"],
            "import_price": aemo.get("import_price", 0.0) + import_offset,
            "feed_in_price": aemo.get("feed_in_price", 0.0) + feed_in_offset,
        })
    return result


def _split_ev_boxes(boxes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Split boxes with min_energy into a must-have + overflow pair.

    When a box has min_energy > 0 and target_energy > min_energy, it is
    split into two boxes:
      - Must-have box: keeps the primary entity, target_energy=min_energy,
        benefit=original benefit (high $/kWh ratio).
      - Overflow box: entity suffixed with ``__overflow``,
        target_energy=remainder, benefit=low_benefit (lower $/kWh ratio).

    Both boxes inherit all other fields. The ``min_energy`` and
    ``low_benefit`` keys are stripped from all output boxes since the
    scheduler API does not know about them.
    """
    result: list[dict[str, Any]] = []
    for box in boxes:
        min_energy = box.pop("min_energy", 0)
        low_benefit = box.pop("low_benefit", 0)
        target = box.get("target_energy", 0)

        if min_energy > 0 and target > min_energy:
            # Must-have box: high-value portion
            must_have = dict(box)
            must_have["target_energy"] = min_energy
            # benefit stays as-is (the high-value amount)
            result.append(must_have)

            # Overflow box: lower-value remainder
            overflow = dict(box)
            overflow["entity"] = f"{box['entity']}__overflow"
            overflow["target_energy"] = target - min_energy
            overflow["benefit"] = low_benefit
            result.append(overflow)
        else:
            result.append(box)

    return result


def _merge_overflow_assignments(
    assignments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Merge ``__overflow`` assignments back into the primary entity.

    After the scheduler returns, overflow assignments need to be folded
    into their parent entity so that downstream execution sees a single
    combined assignment per physical device.
    """
    overflow_map: dict[str, dict[str, Any]] = {}
    primary: list[dict[str, Any]] = []

    for a in assignments:
        entity = a.get("entity", "")
        if entity.endswith("__overflow"):
            base = entity.rsplit("__overflow", 1)[0]
            overflow_map[base] = a
        else:
            primary.append(a)

    if not overflow_map:
        return assignments

    primary_by_entity = {a["entity"]: a for a in primary}

    for base_entity, overflow in overflow_map.items():
        target = primary_by_entity.get(base_entity)
        if target is not None:
            target["slots"] = (target.get("slots") or []) + (
                overflow.get("slots") or []
            )
            if overflow.get("slot_powers"):
                target.setdefault("slot_powers", []).extend(
                    overflow["slot_powers"]
                )
            target["run_time_seconds"] = target.get(
                "run_time_seconds", 0
            ) + overflow.get("run_time_seconds", 0)
            target["energy_cost"] = target.get(
                "energy_cost", 0
            ) + overflow.get("energy_cost", 0)
        else:
            # Overflow scheduled but must-have was not — create entry
            # under the primary entity name.
            merged = dict(overflow)
            merged["entity"] = base_entity
            primary.append(merged)

    return primary


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
        self._last_solve_status: str = "unknown"
        self._last_solve_error: str = ""

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

        for assignment in self.data.get("assignments") or []:
            entity_id = assignment.get("entity", "")
            if entity_id.startswith("__"):
                continue
            for slot_str in assignment.get("slots") or []:
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

        for assignment in self.data.get("assignments") or []:
            entity_id = assignment.get("entity", "")
            if entity_id.startswith("__"):
                continue

            slots = assignment.get("slots") or []
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

        # 2. Expand tariff periods
        # Manual tariff periods are always expanded — they define the
        # time-varying non-wholesale price components (network charges,
        # retailer margin, feed-in rebates).  When AEMO wholesale is
        # selected, these serve as offsets added to the spot price.
        tariff_source = opts.get("tariff_source", "manual")
        raw_tariffs = opts.get("tariff_periods", [])
        manual_periods = expand_recurring_tariffs(
            raw_tariffs, horizon_start, horizon_end, local_tz, self.hass
        )

        if tariff_source == "aemo":
            region = opts.get("aemo_region", "NSW1")
            try:
                aemo_periods = await self.api_client.get_aemo_tariff(region)
            except Exception:
                _LOGGER.warning("Failed to fetch AEMO tariff data", exc_info=True)
                aemo_periods = None
            if aemo_periods:
                tariff_periods = _merge_aemo_with_manual(
                    aemo_periods, manual_periods
                )
            else:
                _LOGGER.warning(
                    "AEMO data unavailable for %s; using manual tariffs only",
                    region,
                )
                tariff_periods = manual_periods
        else:
            tariff_periods = manual_periods

        tariff_periods = _extend_tariff_coverage(
            tariff_periods, horizon_start, horizon_end
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

        # 3b. Apply solar confidence derating
        solar_confidence = opts.get("solar_confidence", 1.0)
        if 0 < solar_confidence < 1.0:
            for box in solar_boxes:
                box["confidence"] = solar_confidence

        # 4. Expand recurring jobs (read from live job entities)
        job_entities = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id, {}
        ).get("job_entities", {})
        jobs = [job_entity_to_dict(e) for e in job_entities.values()]
        job_boxes = expand_recurring_jobs(jobs, horizon_start, horizon_end, local_tz)

        # 5. Merge all boxes and split EV two-tier boxes
        all_boxes = _split_ev_boxes(solar_boxes + job_boxes)

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

            # Overflow boxes share elapsed tracking with their primary entity
            elapsed_entity = (
                entity_id.rsplit("__overflow", 1)[0]
                if entity_id.endswith("__overflow")
                else entity_id
            )
            elapsed = self._elapsed_today.get(elapsed_entity, 0)
            preserved_slots = active_runs.get(elapsed_entity, [])
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
                "preservation_lower_bound": opts.get("preservation_lower_bound", 0.0),
                "preservation_upper_bound": opts.get("preservation_upper_bound", 0.0),
                "battery_efficiency": opts.get("battery_efficiency", 1.0),
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

        # 7. Call the API (async with polling, fallback to sync)
        try:
            result = await self._schedule_with_polling(request)
        except ErgApiError as err:
            self._last_solve_status = err.code.lower() if hasattr(err, "code") else "error"
            self._last_solve_error = str(err)
            try:
                from homeassistant.components.persistent_notification import async_create
                async_create(
                    self.hass,
                    f"Erg schedule failed: {err}",
                    title="Erg Scheduling Error",
                    notification_id="erg_solve_failed",
                )
            except ImportError:
                pass
            forced = [
                b["entity"]
                for b in all_boxes
                if b.get("force") and not b["entity"].startswith("__")
            ]
            summary = f"{len(all_boxes)} jobs ({len(forced)} forced)"
            if forced:
                summary += f": {', '.join(forced)}"
            raise UpdateFailed(
                f"Erg schedule failed ({err.code}) with {summary}. {err}"
            ) from err

        # 8. Merge preserved active-run slots into API response
        if active_runs:
            assignments = result.get("assignments") or []

            for entity_id, preserved_slots in active_runs.items():
                # Find the first assignment for this entity
                target = None
                for a in assignments:
                    if a["entity"] == entity_id:
                        target = a
                        break

                if target is not None:
                    target["slots"] = preserved_slots + (target.get("slots") or [])
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

        # 8b. Merge overflow assignments back into primary entities
        if result.get("assignments"):
            result["assignments"] = _merge_overflow_assignments(
                result["assignments"]
            )

        # 9. Compute price thresholds from schedule + tariff data
        import_threshold, export_threshold = self._compute_price_thresholds(
            result, tariff_periods
        )
        result["import_price_threshold"] = import_threshold
        result["export_price_threshold"] = export_threshold

        # 10. Mark solve as successful and return
        self._last_solve_status = "ok"
        self._last_solve_error = ""
        try:
            from homeassistant.components.persistent_notification import async_dismiss
            async_dismiss(self.hass, notification_id="erg_solve_failed")
        except ImportError:
            pass
        return result

    async def _schedule_with_polling(self, request: dict) -> dict:
        """Submit a schedule request, preferring async+poll with sync fallback."""
        job = await self.api_client.submit_schedule_async(request)
        if job is None:
            # Server doesn't support async — fall back to sync
            return await self.api_client.schedule(request)

        job_id = job["job_id"]
        for _ in range(_SCHEDULE_POLL_MAX_ATTEMPTS):
            await asyncio.sleep(_SCHEDULE_POLL_INTERVAL)
            status = await self.api_client.get_schedule_job(job_id)

            if status["status"] == "complete":
                return status["result"]
            if status["status"] == "failed":
                err = status.get("error", {})
                raise ErgApiError(
                    err.get("message", "Solver failed"),
                    code=err.get("code", "SOLVER_ERROR"),
                    details=err.get("details", {}),
                )

        raise ErgApiError("Schedule solve timed out", code="SOLVER_TIMEOUT")

    def _compute_price_thresholds(
        self,
        schedule_data: dict[str, Any],
        tariff_periods: list[dict[str, Any]],
    ) -> tuple[float | None, float | None]:
        """Derive import/export price thresholds from the schedule.

        Returns (import_threshold, export_threshold) in $/kWh, or None if
        the schedule has no import/export activity.

        import_threshold: highest import price at which the scheduler chose to
        import — any lower price is also worth importing at.

        export_threshold: lowest feed-in price at which the scheduler chose to
        export — any higher price is also worth exporting at.
        """
        battery_profile = schedule_data.get("battery_profile") or []
        if not battery_profile or not tariff_periods:
            return None, None

        import_prices: list[float] = []
        export_prices: list[float] = []

        for bp in battery_profile:
            t_str = bp.get("time")
            if not t_str:
                continue
            try:
                t = datetime.fromisoformat(t_str)
            except (ValueError, TypeError):
                continue

            grid_import = bp.get("grid_import", 0)
            grid_export = bp.get("grid_export", 0)

            if grid_import > 0.01 or grid_export > 0.01:
                # Find the matching tariff period
                for period in tariff_periods:
                    try:
                        p_start = datetime.fromisoformat(period["start"])
                        p_end = datetime.fromisoformat(period["end"])
                    except (ValueError, TypeError, KeyError):
                        continue
                    if p_start <= t < p_end:
                        if grid_import > 0.01:
                            import_prices.append(period.get("import_price", 0))
                        if grid_export > 0.01:
                            export_prices.append(period.get("feed_in_price", 0))
                        break

        import_threshold = max(import_prices) if import_prices else None
        export_threshold = min(export_prices) if export_prices else None
        return import_threshold, export_threshold
