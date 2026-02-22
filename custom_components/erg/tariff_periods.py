"""Recurring tariff definitions and expansion to absolute TariffPeriod dicts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, tzinfo
from typing import Any

from .jobs import _parse_time, day_matches

_LOGGER = logging.getLogger(__name__)


def read_entity_forecasts(
    hass: Any,
    entity_id: str,
    horizon_start: datetime,
    horizon_end: datetime,
) -> list[dict[str, Any]]:
    """Read current + forecast prices from a HA sensor entity.

    Returns a sorted list of {"start": datetime, "end": datetime, "price": float}
    intervals clipped to [horizon_start, horizon_end].

    Compatible with any sensor that exposes:
    - State: current price in $/kWh
    - Attributes: ``forecasts`` list with ``start_time``, ``end_time``, ``per_kwh``
      (e.g. Amber Electric HA integration)
    """
    state = hass.states.get(entity_id)
    if state is None or state.state in ("unknown", "unavailable"):
        _LOGGER.warning("Price entity %s is unavailable", entity_id)
        return []

    intervals: list[dict[str, Any]] = []

    # Current interval from sensor state + attributes
    try:
        current_price = float(state.state)
    except (ValueError, TypeError):
        _LOGGER.warning(
            "Could not parse price from %s: %s", entity_id, state.state
        )
        return []

    attrs = state.attributes
    start_str = attrs.get("start_time")
    end_str = attrs.get("end_time")
    if start_str and end_str:
        try:
            intervals.append({
                "start": datetime.fromisoformat(str(start_str)),
                "end": datetime.fromisoformat(str(end_str)),
                "price": abs(current_price),
            })
        except (ValueError, TypeError):
            pass

    # Forecast intervals from attribute
    forecasts = attrs.get("forecasts", [])
    for f in forecasts:
        f_start = f.get("start_time")
        f_end = f.get("end_time")
        f_price = f.get("per_kwh")
        if f_start is None or f_end is None or f_price is None:
            continue
        try:
            intervals.append({
                "start": datetime.fromisoformat(str(f_start)),
                "end": datetime.fromisoformat(str(f_end)),
                "price": abs(float(f_price)),
            })
        except (ValueError, TypeError):
            continue

    # Clip to horizon and discard empty intervals
    clipped: list[dict[str, Any]] = []
    for iv in intervals:
        s = max(iv["start"], horizon_start)
        e = min(iv["end"], horizon_end)
        if e > s:
            clipped.append({"start": s, "end": e, "price": iv["price"]})

    # Sort by start time and deduplicate overlapping intervals
    clipped.sort(key=lambda x: x["start"])
    return clipped


def _merge_entity_into_window(
    entity_intervals: list[dict[str, Any]],
    window_start: datetime,
    window_end: datetime,
    fallback_price: float,
) -> list[dict[str, Any]]:
    """Merge entity forecast intervals into a time window with fallback pricing.

    Returns a list of {"start": datetime, "end": datetime, "price": float}
    covering the entire window without gaps. Gaps in entity coverage use
    *fallback_price*.
    """
    if not entity_intervals:
        return [{"start": window_start, "end": window_end, "price": fallback_price}]

    # Clip entity intervals to the window
    clipped = []
    for iv in entity_intervals:
        s = max(iv["start"], window_start)
        e = min(iv["end"], window_end)
        if e > s:
            clipped.append({"start": s, "end": e, "price": iv["price"]})
    clipped.sort(key=lambda x: x["start"])

    if not clipped:
        return [{"start": window_start, "end": window_end, "price": fallback_price}]

    # Fill gaps with fallback
    result: list[dict[str, Any]] = []
    cursor = window_start
    for iv in clipped:
        if iv["start"] > cursor:
            result.append({"start": cursor, "end": iv["start"], "price": fallback_price})
        result.append(iv)
        cursor = max(cursor, iv["end"])
    if cursor < window_end:
        result.append({"start": cursor, "end": window_end, "price": fallback_price})

    return result


def _align_price_intervals(
    import_intervals: list[dict[str, Any]],
    feedin_intervals: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Align import and feed-in price intervals into unified tariff periods.

    Both input lists must fully cover the same time window (no gaps).
    Returns a list of {"start": ISO, "end": ISO, "import_price": float,
    "feed_in_price": float} dicts.
    """
    # Collect all unique time boundaries
    boundaries: set[datetime] = set()
    for iv in import_intervals + feedin_intervals:
        boundaries.add(iv["start"])
        boundaries.add(iv["end"])
    boundaries_sorted = sorted(boundaries)

    if len(boundaries_sorted) < 2:
        return []

    # Build a lookup: for each point in time, find the applicable price
    def find_price(intervals: list[dict[str, Any]], t: datetime) -> float:
        for iv in intervals:
            if iv["start"] <= t < iv["end"]:
                return iv["price"]
        return 0.0

    periods = []
    for i in range(len(boundaries_sorted) - 1):
        s = boundaries_sorted[i]
        e = boundaries_sorted[i + 1]
        periods.append({
            "start": s.isoformat(),
            "end": e.isoformat(),
            "import_price": find_price(import_intervals, s),
            "feed_in_price": find_price(feedin_intervals, s),
        })

    return periods


def expand_recurring_tariffs(
    tariff_defs: list[dict[str, Any]],
    horizon_start: datetime,
    horizon_end: datetime,
    local_tz: tzinfo,
    hass: Any = None,
) -> list[dict[str, Any]]:
    """Expand recurring tariff definitions into absolute TariffPeriod dicts.

    Output format matches Go API:
        {"start": ISO, "end": ISO, "import_price": float, "feed_in_price": float}

    If a tariff definition contains ``import_price_entity`` or
    ``feed_in_price_entity``, the corresponding prices are read from the HA
    entity's current state and forecast attributes.  *hass* must be provided
    for entity-linked tariffs.
    """
    periods: list[dict[str, Any]] = []
    current_day = horizon_start.date()
    end_day = horizon_end.date()

    # Pre-read entity forecasts (cache per entity to avoid repeated reads)
    entity_cache: dict[str, list[dict[str, Any]]] = {}

    def get_entity_forecasts(entity_id: str) -> list[dict[str, Any]]:
        if entity_id not in entity_cache:
            if hass is None:
                _LOGGER.warning(
                    "Entity-linked tariff requires hass; ignoring %s", entity_id
                )
                entity_cache[entity_id] = []
            else:
                entity_cache[entity_id] = read_entity_forecasts(
                    hass, entity_id, horizon_start, horizon_end
                )
        return entity_cache[entity_id]

    for tariff in tariff_defs:
        recurrence = tariff.get("recurrence")
        if recurrence is None:
            # Pass through absolute tariff periods (already have start/end)
            if "start" in tariff and "end" in tariff:
                periods.append({
                    "start": tariff["start"],
                    "end": tariff["end"],
                    "import_price": tariff.get("import_price", 0.0),
                    "feed_in_price": tariff.get("feed_in_price", 0.0),
                })
            continue

        import_entity = tariff.get("import_price_entity", "")
        feedin_entity = tariff.get("feed_in_price_entity", "")
        has_entity = bool(import_entity or feedin_entity)

        # Pre-fetch entity data if needed
        import_forecasts = get_entity_forecasts(import_entity) if import_entity else []
        feedin_forecasts = get_entity_forecasts(feedin_entity) if feedin_entity else []

        day = current_day
        while day <= end_day:
            if day_matches(day, recurrence):
                window_start = datetime.combine(
                    day, _parse_time(recurrence["time_window_start"])
                ).replace(tzinfo=local_tz)
                window_end = datetime.combine(
                    day, _parse_time(recurrence["time_window_end"])
                ).replace(tzinfo=local_tz)

                # Overnight window wraps to next day
                if window_end <= window_start:
                    window_end += timedelta(days=1)

                # Clip to horizon
                effective_start = max(window_start, horizon_start)
                effective_end = min(window_end, horizon_end)

                if effective_end <= effective_start:
                    day += timedelta(days=1)
                    continue

                if not has_entity:
                    # Static tariff — single period for the whole window
                    periods.append({
                        "start": effective_start.isoformat(),
                        "end": effective_end.isoformat(),
                        "import_price": tariff.get("import_price", 0.0),
                        "feed_in_price": tariff.get("feed_in_price", 0.0),
                    })
                else:
                    # Entity-linked tariff — merge entity forecasts with
                    # static fallback prices into fine-grained periods
                    import_merged = _merge_entity_into_window(
                        import_forecasts,
                        effective_start,
                        effective_end,
                        tariff.get("import_price", 0.0),
                    )
                    feedin_merged = _merge_entity_into_window(
                        feedin_forecasts,
                        effective_start,
                        effective_end,
                        tariff.get("feed_in_price", 0.0),
                    )
                    periods.extend(
                        _align_price_intervals(import_merged, feedin_merged)
                    )

            day += timedelta(days=1)

    return periods
