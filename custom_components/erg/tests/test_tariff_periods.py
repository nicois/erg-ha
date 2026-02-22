"""Tests for tariff_periods.py — recurring tariff expansion."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.erg.tariff_periods import expand_recurring_tariffs

UTC = timezone.utc


class TestExpandRecurringTariffs:
    """Tests for expand_recurring_tariffs."""

    def test_empty_defs_returns_empty(self):
        result = expand_recurring_tariffs(
            [],
            datetime(2026, 2, 16, 0, 0, tzinfo=UTC),
            datetime(2026, 2, 17, 0, 0, tzinfo=UTC),
            UTC,
        )
        assert result == []

    def test_daily_tariff_produces_period_per_day(self):
        defs = [
            {
                "name": "Off-Peak",
                "import_price": 0.12,
                "feed_in_price": 0.05,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "22:00",
                    "time_window_end": "06:00",
                },
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 19, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        # Days 16, 17, 18 match; day 19 is end_day but 22:00 > horizon_end
        # Day 16: 22:00-06:00(17th), clipped to horizon → 22:00-06:00 ✓
        # Day 17: 22:00-06:00(18th) ✓
        # Day 18: 22:00-06:00(19th), end clipped to 00:00 on 19th ✓
        assert len(periods) == 3
        for p in periods:
            assert p["import_price"] == 0.12
            assert p["feed_in_price"] == 0.05

    def test_weekdays_tariff_filters_weekends(self):
        defs = [
            {
                "name": "Peak",
                "import_price": 0.35,
                "feed_in_price": 0.03,
                "recurrence": {
                    "frequency": "weekdays",
                    "time_window_start": "14:00",
                    "time_window_end": "20:00",
                },
            }
        ]
        # Mon 16 Feb to Sun 22 Feb (7 days, 5 weekdays)
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 5

    def test_weekends_tariff(self):
        defs = [
            {
                "name": "Weekend",
                "import_price": 0.15,
                "feed_in_price": 0.04,
                "recurrence": {
                    "frequency": "weekends",
                    "time_window_start": "00:00",
                    "time_window_end": "23:59",
                },
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 2

    def test_overnight_window(self):
        defs = [
            {
                "name": "Off-Peak",
                "import_price": 0.10,
                "feed_in_price": 0.05,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "22:00",
                    "time_window_end": "07:00",
                },
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 23, 59, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        # Day 16: 22:00→07:00(17th) ✓
        # Day 17: 22:00→07:00(18th), clipped end to 23:59 ✓
        assert len(periods) == 2
        assert "22:00" in periods[0]["start"]

    def test_horizon_clipping(self):
        defs = [
            {
                "name": "Peak",
                "import_price": 0.30,
                "feed_in_price": 0.02,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "06:00",
                    "time_window_end": "22:00",
                },
            }
        ]
        # Horizon starts at 10:00 — window should be clipped
        start = datetime(2026, 2, 16, 10, 0, tzinfo=UTC)
        end = datetime(2026, 2, 16, 18, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 1
        assert periods[0]["start"] == start.isoformat()
        assert periods[0]["end"] == end.isoformat()

    def test_weekly_tariff(self):
        defs = [
            {
                "name": "Wednesday Special",
                "import_price": 0.08,
                "feed_in_price": 0.06,
                "recurrence": {
                    "frequency": "weekly",
                    "day_of_week": 2,  # Wednesday
                    "time_window_start": "10:00",
                    "time_window_end": "16:00",
                },
            }
        ]
        # Mon 16 to Sun 22 — only Wed 18 matches
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 1
        assert "2026-02-18" in periods[0]["start"]

    def test_custom_days_tariff(self):
        defs = [
            {
                "name": "Custom",
                "import_price": 0.20,
                "feed_in_price": 0.04,
                "recurrence": {
                    "frequency": "custom",
                    "days_of_week": [0, 4],  # Monday, Friday
                    "time_window_start": "08:00",
                    "time_window_end": "12:00",
                },
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 23, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 2  # Mon 16 + Fri 20

    def test_no_recurrence_without_start_end_skipped(self):
        defs = [
            {
                "name": "Legacy",
                "import_price": 0.25,
                "feed_in_price": 0.03,
                "recurrence": None,
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert periods == []

    def test_absolute_tariff_passed_through(self):
        """Pre-existing absolute tariff periods (no recurrence, with start/end)
        should be passed through unchanged."""
        defs = [
            {
                "start": "2026-02-16T14:00:00+00:00",
                "end": "2026-02-16T20:00:00+00:00",
                "import_price": 0.35,
                "feed_in_price": 0.03,
            }
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 1
        assert periods[0]["start"] == "2026-02-16T14:00:00+00:00"
        assert periods[0]["end"] == "2026-02-16T20:00:00+00:00"
        assert periods[0]["import_price"] == 0.35
        assert periods[0]["feed_in_price"] == 0.03

    def test_mixed_absolute_and_recurring(self):
        """Absolute and recurring tariffs can coexist."""
        defs = [
            {
                "start": "2026-02-16T00:00:00+00:00",
                "end": "2026-02-16T06:00:00+00:00",
                "import_price": 0.10,
                "feed_in_price": 0.05,
            },
            {
                "name": "Peak",
                "import_price": 0.35,
                "feed_in_price": 0.03,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "14:00",
                    "time_window_end": "20:00",
                },
            },
        ]
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC)
        assert len(periods) == 2
        # First is the absolute passthrough
        assert periods[0]["start"] == "2026-02-16T00:00:00+00:00"
        # Second is the expanded recurring
        assert periods[1]["import_price"] == 0.35
