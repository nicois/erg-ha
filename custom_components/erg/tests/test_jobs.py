"""Tests for jobs.py — recurring job expansion and day matching."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import pytest

from custom_components.erg.jobs import day_matches, expand_recurring_jobs

UTC = timezone.utc


class TestDayMatches:
    """Tests for the day_matches function."""

    def test_daily_matches_any_day(self):
        rec = {"frequency": "daily"}
        # Monday through Sunday
        for offset in range(7):
            d = date(2026, 2, 16) + timedelta(days=offset)  # 16 Feb 2026 is Monday
            assert day_matches(d, rec) is True

    def test_weekdays_matches_mon_to_fri(self):
        rec = {"frequency": "weekdays"}
        monday = date(2026, 2, 16)
        for offset in range(5):
            assert day_matches(monday + timedelta(days=offset), rec) is True
        # Saturday and Sunday
        assert day_matches(monday + timedelta(days=5), rec) is False
        assert day_matches(monday + timedelta(days=6), rec) is False

    def test_weekends_matches_sat_and_sun(self):
        rec = {"frequency": "weekends"}
        monday = date(2026, 2, 16)
        for offset in range(5):
            assert day_matches(monday + timedelta(days=offset), rec) is False
        assert day_matches(monday + timedelta(days=5), rec) is True
        assert day_matches(monday + timedelta(days=6), rec) is True

    def test_weekly_matches_specific_day(self):
        rec = {"frequency": "weekly", "day_of_week": 2}  # Wednesday
        monday = date(2026, 2, 16)
        assert day_matches(monday, rec) is False
        assert day_matches(monday + timedelta(days=2), rec) is True

    def test_custom_matches_specified_days(self):
        rec = {"frequency": "custom", "days_of_week": [0, 3, 5]}  # Mon, Thu, Sat
        monday = date(2026, 2, 16)
        expected = [True, False, False, True, False, True, False]
        for offset, exp in enumerate(expected):
            assert day_matches(monday + timedelta(days=offset), rec) is exp

    def test_unknown_frequency_returns_false(self):
        rec = {"frequency": "monthly"}
        assert day_matches(date(2026, 2, 16), rec) is False


class TestExpandRecurringJobs:
    """Tests for expand_recurring_jobs."""

    def test_empty_jobs_returns_empty(self):
        result = expand_recurring_jobs(
            [],
            datetime(2026, 2, 16, 0, 0, tzinfo=UTC),
            datetime(2026, 2, 17, 0, 0, tzinfo=UTC),
            UTC,
        )
        assert result == []

    def test_daily_job_produces_box_per_day(self):
        jobs = [
            {
                "entity_id": "switch.pump",
                "ac_power": 1.0,
                "dc_power": 0,
                "force": False,
                "benefit": 10,
                "enabled": True,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "09:00",
                    "time_window_end": "17:00",
                    "maximum_duration": "3h",
                    "minimum_duration": "0s",
                    "minimum_burst": "0s",
                },
            }
        ]
        # 3-day horizon
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 19, 0, 0, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        assert len(boxes) == 3
        for box in boxes:
            assert box["entity"] == "switch.pump"
            assert box["ac_power"] == 1.0
            assert box["maximum_duration"] == "3h"

    def test_weekdays_filters_weekend(self):
        jobs = [
            {
                "entity_id": "switch.ev",
                "ac_power": 7.0,
                "dc_power": 0,
                "force": True,
                "benefit": 0,
                "enabled": True,
                "recurrence": {
                    "frequency": "weekdays",
                    "time_window_start": "08:00",
                    "time_window_end": "18:00",
                    "maximum_duration": "2h",
                },
            }
        ]
        # Mon 16 Feb to Sun 22 Feb (7 days, 5 weekdays)
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        assert len(boxes) == 5

    def test_overnight_window_wraps(self):
        jobs = [
            {
                "entity_id": "switch.ev",
                "ac_power": 7.0,
                "dc_power": 0,
                "force": False,
                "benefit": 0,
                "enabled": True,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "22:00",
                    "time_window_end": "06:00",
                    "maximum_duration": "6h",
                },
            }
        ]
        # Single day — the window runs 22:00 to 06:00 next day
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 23, 59, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        # Should produce boxes for both Feb 16 and Feb 17
        assert len(boxes) == 2
        # The first box should start at 22:00 on the 16th
        assert "22:00" in boxes[0]["start_time"]

    def test_horizon_clipping(self):
        jobs = [
            {
                "entity_id": "switch.pump",
                "ac_power": 1.0,
                "dc_power": 0,
                "force": False,
                "benefit": 0,
                "enabled": True,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "06:00",
                    "time_window_end": "22:00",
                    "maximum_duration": "4h",
                },
            }
        ]
        # Horizon starts at 10:00, so the window should be clipped
        start = datetime(2026, 2, 16, 10, 0, tzinfo=UTC)
        end = datetime(2026, 2, 16, 18, 0, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        assert len(boxes) == 1
        assert boxes[0]["start_time"] == start.isoformat()
        assert boxes[0]["finish_time"] == end.isoformat()

    def test_disabled_job_skipped(self):
        jobs = [
            {
                "entity_id": "switch.pump",
                "ac_power": 1.0,
                "enabled": False,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "09:00",
                    "time_window_end": "17:00",
                    "maximum_duration": "3h",
                },
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        assert boxes == []

    def test_one_shot_job(self):
        jobs = [
            {
                "entity_id": "switch.heater",
                "ac_power": 2.0,
                "dc_power": 0,
                "force": True,
                "benefit": 5,
                "enabled": True,
                "recurrence": None,
                "start": "2026-02-16T14:00:00+00:00",
                "finish": "2026-02-16T18:00:00+00:00",
                "maximum_duration": "2h",
                "minimum_duration": "30m",
                "minimum_burst": "15m",
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        assert len(boxes) == 1
        assert boxes[0]["entity"] == "switch.heater"
        assert boxes[0]["force"] is True
        assert boxes[0]["maximum_duration"] == "2h"

    def test_one_shot_outside_horizon_skipped(self):
        jobs = [
            {
                "entity_id": "switch.heater",
                "ac_power": 2.0,
                "enabled": True,
                "recurrence": None,
                "start": "2026-02-20T14:00:00+00:00",
                "finish": "2026-02-20T18:00:00+00:00",
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = expand_recurring_jobs(jobs, start, end, UTC)
        assert boxes == []
