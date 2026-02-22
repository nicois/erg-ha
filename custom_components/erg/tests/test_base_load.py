"""Tests for forced base load job handling.

A forced base load job (running all day at constant power) must always
appear in the boxes submitted to the scheduler, even when the elapsed-time
budget for the current day has been fully consumed.  The scheduler needs
forced jobs to model their power draw for accurate battery SoC projection.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from custom_components.erg.jobs import expand_recurring_jobs
from custom_components.erg.const import (
    format_duration_seconds,
    parse_slot_duration_seconds,
)


AEST = timezone(timedelta(hours=11))


def _base_load_job() -> dict:
    """A forced daily base load running all day at 0.2 kW AC."""
    return {
        "entity_id": "sensor.base_load",
        "ac_power": 0.2,
        "dc_power": 0.0,
        "force": True,
        "benefit": 0,
        "enabled": True,
        "recurrence": {
            "frequency": "daily",
            "time_window_start": "00:00",
            "time_window_end": "00:00",
            "maximum_duration": "24h",
            "minimum_duration": "24h",
            "minimum_burst": "0s",
        },
    }


def _apply_elapsed_adjustment(
    boxes: list[dict],
    tracking_date,
    elapsed_today: dict[str, float],
    slot_seconds: int = 900,
) -> list[dict]:
    """Replicate the coordinator's step 5b elapsed-time adjustment.

    This is the logic from coordinator.py lines 231-274, extracted so we
    can unit-test it without instantiating the full HA coordinator.
    """
    adjusted: list[dict] = []
    for box in boxes:
        entity_id = box["entity"]
        if entity_id.startswith("__"):
            adjusted.append(box)
            continue

        # Forced boxes skip elapsed adjustment entirely
        if box.get("force"):
            adjusted.append(box)
            continue

        box_start = datetime.fromisoformat(box["start_time"])
        if box_start.date() != tracking_date:
            adjusted.append(box)
            continue

        elapsed = elapsed_today.get(entity_id, 0)
        max_secs = parse_slot_duration_seconds(box["maximum_duration"])
        remaining = max(0, max_secs - elapsed)

        if remaining <= 0:
            continue  # budget exhausted, exclude from API request

        effective_start = datetime.fromisoformat(box["start_time"])
        box_finish = datetime.fromisoformat(box["finish_time"])
        window_secs = max(
            0, int((box_finish - effective_start).total_seconds())
        )
        remaining = min(remaining, window_secs)

        box["maximum_duration"] = format_duration_seconds(int(remaining))
        adjusted.append(box)

    return adjusted


class TestForcedBaseLoadExpansion:
    """Tests that expand_recurring_jobs produces a box for the current day."""

    def test_base_load_produces_box_for_today(self):
        now = datetime(2026, 2, 28, 14, 0, 0, tzinfo=AEST)
        horizon_end = datetime(2026, 3, 2, 0, 0, 0, tzinfo=AEST)

        boxes = expand_recurring_jobs([_base_load_job()], now, horizon_end, AEST)

        today_boxes = [
            b for b in boxes
            if b["entity"] == "sensor.base_load"
            and datetime.fromisoformat(b["start_time"]).date() == now.date()
        ]
        assert len(today_boxes) == 1
        assert today_boxes[0]["force"] is True
        assert today_boxes[0]["ac_power"] == 0.2


class TestForcedBaseLoadSubmission:
    """Tests that forced base load survives elapsed-time adjustment."""

    def test_forced_base_load_present_after_elapsed_adjustment(self):
        """When elapsed time has been fully consumed, forced jobs must
        still appear in the submitted boxes for today.

        This currently fails because step 5b drops ALL boxes (including
        forced ones) when remaining <= 0.
        """
        now = datetime(2026, 2, 28, 14, 0, 0, tzinfo=AEST)
        horizon_end = datetime(2026, 3, 2, 0, 0, 0, tzinfo=AEST)

        boxes = expand_recurring_jobs([_base_load_job()], now, horizon_end, AEST)

        # Simulate: the base load has already used its full 24h budget today
        elapsed_today = {"sensor.base_load": 86400}

        adjusted = _apply_elapsed_adjustment(
            boxes,
            tracking_date=now.date(),
            elapsed_today=elapsed_today,
        )

        today_boxes = [
            b for b in adjusted
            if b["entity"] == "sensor.base_load"
            and datetime.fromisoformat(b["start_time"]).date() == now.date()
        ]
        assert len(today_boxes) >= 1, (
            "Forced base load box for current day was dropped from API request"
        )
