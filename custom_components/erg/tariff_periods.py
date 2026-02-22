"""Recurring tariff definitions and expansion to absolute TariffPeriod dicts."""

from __future__ import annotations

from datetime import datetime, timedelta, tzinfo
from typing import Any

from .jobs import _parse_time, day_matches


def expand_recurring_tariffs(
    tariff_defs: list[dict[str, Any]],
    horizon_start: datetime,
    horizon_end: datetime,
    local_tz: tzinfo,
) -> list[dict[str, Any]]:
    """Expand recurring tariff definitions into absolute TariffPeriod dicts.

    Output format matches Go API:
        {"start": ISO, "end": ISO, "import_price": float, "feed_in_price": float}
    """
    periods: list[dict[str, Any]] = []
    current_day = horizon_start.date()
    end_day = horizon_end.date()

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

                if effective_end > effective_start:
                    periods.append(
                        {
                            "start": effective_start.isoformat(),
                            "end": effective_end.isoformat(),
                            "import_price": tariff.get("import_price", 0.0),
                            "feed_in_price": tariff.get("feed_in_price", 0.0),
                        }
                    )

            day += timedelta(days=1)

    return periods
