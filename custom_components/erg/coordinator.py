"""DataUpdateCoordinator for the Erg Energy Scheduler integration."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import ErgApiClient, ErgApiError
from .const import (
    DEFAULT_HORIZON_HOURS,
    DEFAULT_SLOT_DURATION,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)
from .jobs import expand_recurring_jobs
from .solar import get_solar_forecast, solar_forecast_to_boxes

_LOGGER = logging.getLogger(__name__)


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

    async def _async_update_data(self) -> dict[str, Any]:
        """Fetch data from the Erg scheduler."""
        opts = self.config_entry.options
        now = datetime.now().astimezone()
        local_tz = now.tzinfo

        horizon_hours = opts.get("horizon_hours", DEFAULT_HORIZON_HOURS)
        horizon_start = now
        horizon_end = now + timedelta(hours=horizon_hours)

        # 1. Read battery state of charge
        soc_kwh = 0.0
        soc_entity = opts.get("battery_soc_entity", "")
        if soc_entity:
            state = self.hass.states.get(soc_entity)
            if state is not None and state.state not in ("unknown", "unavailable"):
                try:
                    soc_kwh = float(state.state)
                except (ValueError, TypeError):
                    _LOGGER.warning(
                        "Could not parse battery SoC from %s: %s",
                        soc_entity,
                        state.state,
                    )

        # 2. Build tariff periods from options
        tariff_periods = opts.get("tariff_periods", [])

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

        # 4. Expand recurring jobs
        jobs = opts.get("jobs", [])
        job_boxes = expand_recurring_jobs(jobs, horizon_start, horizon_end, local_tz)

        # 5. Merge all boxes
        all_boxes = solar_boxes + job_boxes

        # 6. Build API request matching Go ScheduleRequest schema
        slot_duration = opts.get("slot_duration", DEFAULT_SLOT_DURATION)
        request: dict[str, Any] = {
            "system": {
                "grid_import_limit": opts.get("grid_import_limit", 10.0),
                "grid_export_limit": opts.get("grid_export_limit", 5.0),
                "inverter_power": opts.get("inverter_power", 5.0),
                "battery_capacity": opts.get("battery_capacity", 0.0),
                "state_of_charge": soc_kwh,
                "battery_storage_value_per_kilowatt_hour": opts.get(
                    "battery_storage_value", 0.0
                ),
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
            raise UpdateFailed(f"Erg schedule request failed: {err}") from err

        # 8. Return the parsed response
        return result
