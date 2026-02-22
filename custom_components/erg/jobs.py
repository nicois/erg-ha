"""Recurring job definitions and expansion to concrete PowerBox dicts."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, tzinfo
from typing import Any


def day_matches(day: date, recurrence: dict[str, Any]) -> bool:
    """Check if a calendar date matches a recurrence rule."""
    weekday = day.weekday()  # 0=Monday, 6=Sunday
    freq = recurrence["frequency"]

    if freq == "daily":
        return True
    elif freq == "weekdays":
        return weekday <= 4
    elif freq == "weekends":
        return weekday >= 5
    elif freq == "weekly":
        return weekday == recurrence.get("day_of_week", 0)
    elif freq == "custom":
        return weekday in recurrence.get("days_of_week", [])
    return False


def _parse_time(s: str) -> time:
    """Parse a HH:MM time string."""
    parts = s.split(":")
    return time(int(parts[0]), int(parts[1]))


def expand_recurring_jobs(
    jobs: list[dict[str, Any]],
    horizon_start: datetime,
    horizon_end: datetime,
    local_tz: tzinfo,
) -> list[dict[str, Any]]:
    """Expand recurring job definitions into concrete PowerBox dicts.

    For each job, iterates over every day in the horizon. If the day matches
    the job's recurrence rule, emits a PowerBox dict with absolute timestamps.

    One-shot jobs (recurrence is None, with explicit start/finish) are passed
    through directly if they overlap the horizon.
    """
    boxes: list[dict[str, Any]] = []
    current_day = horizon_start.date()
    end_day = horizon_end.date()

    for job in jobs:
        if not job.get("enabled", True):
            continue

        recurrence = job.get("recurrence")

        # One-shot job: explicit start/finish, no recurrence
        if recurrence is None:
            start_str = job.get("start")
            finish_str = job.get("finish")
            if not start_str or not finish_str:
                continue
            job_start = datetime.fromisoformat(start_str)
            job_finish = datetime.fromisoformat(finish_str)
            # Clip to horizon
            effective_start = max(job_start, horizon_start)
            effective_end = min(job_finish, horizon_end)
            if effective_end <= effective_start:
                continue
            boxes.append(_make_box(job, effective_start, effective_end))
            continue

        # Recurring job: expand across matching days
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
                    boxes.append(
                        _make_box_from_recurrence(job, recurrence, effective_start, effective_end)
                    )

            day += timedelta(days=1)

    return boxes


def _make_box(
    job: dict[str, Any],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Create a PowerBox dict from a one-shot job definition."""
    return {
        "entity": job["entity_id"],
        "start_time": start.isoformat(),
        "finish_time": end.isoformat(),
        "maximum_duration": job.get("maximum_duration", "1h"),
        "minimum_duration": job.get("minimum_duration", "0s"),
        "minimum_burst": job.get("minimum_burst", "0s"),
        "ac_power": job.get("ac_power", 0),
        "dc_power": job.get("dc_power", 0),
        "force": job.get("force", False),
        "benefit": job.get("benefit", 0),
    }


def _make_box_from_recurrence(
    job: dict[str, Any],
    recurrence: dict[str, Any],
    start: datetime,
    end: datetime,
) -> dict[str, Any]:
    """Create a PowerBox dict from a recurring job definition."""
    return {
        "entity": job["entity_id"],
        "start_time": start.isoformat(),
        "finish_time": end.isoformat(),
        "maximum_duration": recurrence["maximum_duration"],
        "minimum_duration": recurrence.get("minimum_duration", "0s"),
        "minimum_burst": recurrence.get("minimum_burst", "0s"),
        "ac_power": job.get("ac_power", 0),
        "dc_power": job.get("dc_power", 0),
        "force": job.get("force", False),
        "benefit": job.get("benefit", 0),
    }
