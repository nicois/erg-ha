"""Solar forecast retrieval and conversion to PowerBox dicts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

_LOGGER = logging.getLogger(__name__)


def solar_forecast_to_boxes(
    wh_hours: dict[str, float],
    horizon_start: datetime,
    horizon_end: datetime,
) -> list[dict[str, Any]]:
    """Convert a wh_hours solar forecast into forced DC PowerBox entries.

    Each forecast period becomes a single forced PowerBox with:
    - start/finish bounding exactly that period
    - dc_power = -(Wh / period_hours)  (negative = generation)
    - force = true (solar generation is not optional)
    - maximum_duration = period length
    """
    if not wh_hours:
        return []

    # Parse timestamps once and map parsed datetimes directly to Wh values.
    # This avoids isoformat() round-trip mismatches (e.g. "Z" vs "+00:00",
    # trailing microsecond zeros) that would cause KeyError on lookup.
    parsed: dict[datetime, float] = {
        datetime.fromisoformat(ts): wh for ts, wh in wh_hours.items()
    }
    sorted_times = sorted(parsed.keys())
    boxes: list[dict[str, Any]] = []

    for i, period_start in enumerate(sorted_times):
        # Determine period end from next timestamp, or assume 1h
        if i + 1 < len(sorted_times):
            period_end = sorted_times[i + 1]
        else:
            period_end = period_start + timedelta(hours=1)

        # Clip to horizon
        effective_start = max(period_start, horizon_start)
        effective_end = min(period_end, horizon_end)
        if effective_end <= effective_start:
            continue

        wh = parsed[period_start]
        if wh <= 0:
            continue

        period_seconds = (period_end - period_start).total_seconds()
        if period_seconds <= 0:
            continue

        # Scale energy proportionally when the period is clipped to the horizon.
        effective_seconds = (effective_end - effective_start).total_seconds()
        effective_wh = wh * effective_seconds / period_seconds
        effective_hours = effective_seconds / 3600
        dc_kw = (effective_wh / 1000) / effective_hours  # Wh -> kWh -> kW average

        effective_duration = effective_end - effective_start
        duration_str = f"{int(effective_duration.total_seconds())}s"

        boxes.append({
            "entity": "__solar__",
            "start_time": effective_start.isoformat(),
            "finish_time": effective_end.isoformat(),
            "maximum_duration": duration_str,
            "minimum_duration": duration_str,
            "minimum_burst": duration_str,
            "ac_power": 0,
            "dc_power": -dc_kw,
            "force": True,
            "benefit": 0,
        })

    return boxes


async def get_solar_forecast(
    hass: Any,
    config_entry_ids: list[str] | None = None,
) -> dict[str, float]:
    """Retrieve and merge solar forecasts from HA energy platform providers.

    This function depends on Home Assistant and can only be called within
    a running HA instance. It discovers all integrations implementing
    async_get_solar_forecast via the energy platform protocol.

    Args:
        hass: Home Assistant instance
        config_entry_ids: Specific config entries to query, or None for
            auto-discovery of all solar forecast providers.

    Returns:
        Merged wh_hours dict (ISO datetime string -> Wh).
        When multiple providers cover the same timestamp, values are summed.
    """
    from homeassistant.core import callback
    from homeassistant.helpers.integration_platform import (
        async_process_integration_platforms,
    )

    forecast_platforms: dict[str, Any] = {}

    @callback
    def _register(hass_ref: Any, domain: str, platform: Any) -> None:
        if hasattr(platform, "async_get_solar_forecast"):
            forecast_platforms[domain] = platform.async_get_solar_forecast

    await async_process_integration_platforms(
        hass, "energy", _register, wait_for_platforms=True
    )

    merged: dict[str, float] = {}

    if config_entry_ids is not None:
        entries = config_entry_ids
    else:
        entries = [
            entry.entry_id
            for entry in hass.config_entries.async_entries()
            if entry.domain in forecast_platforms
        ]

    from homeassistant.config_entries import ConfigEntryState

    for entry_id in entries:
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is None or entry.domain not in forecast_platforms:
            continue
        if entry.state is not ConfigEntryState.LOADED:
            _LOGGER.debug(
                "Skipping solar forecast from %s (%s): not yet loaded",
                entry.domain,
                entry_id,
            )
            continue
        try:
            forecast = await forecast_platforms[entry.domain](hass, entry_id)
        except Exception:
            _LOGGER.warning(
                "Failed to get solar forecast from %s (%s)",
                entry.domain,
                entry_id,
                exc_info=True,
            )
            continue
        if forecast is None:
            continue
        for ts, wh in forecast.get("wh_hours", {}).items():
            merged[ts] = merged.get(ts, 0) + wh

    return merged
