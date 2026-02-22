"""Tests for solar.py — solar forecast to PowerBox conversion."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from custom_components.erg.solar import solar_forecast_to_boxes

UTC = timezone.utc


class TestSolarForecastToBoxes:
    """Tests for the solar_forecast_to_boxes function."""

    def test_empty_forecast_returns_empty(self):
        result = solar_forecast_to_boxes(
            {},
            datetime(2026, 2, 16, 6, 0, tzinfo=UTC),
            datetime(2026, 2, 16, 18, 0, tzinfo=UTC),
        )
        assert result == []

    def test_hourly_forecast_converts_to_kw(self):
        """1000 Wh over 1 hour = 1 kW."""
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 1000.0,
            "2026-02-16T11:00:00+00:00": 2000.0,
            "2026-02-16T12:00:00+00:00": 500.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 3
        # 1000 Wh / 1h = 1 kW
        assert boxes[0]["dc_power"] == pytest.approx(-1.0)
        # 2000 Wh / 1h = 2 kW
        assert boxes[1]["dc_power"] == pytest.approx(-2.0)
        # 500 Wh / 1h = 0.5 kW
        assert boxes[2]["dc_power"] == pytest.approx(-0.5)

    def test_all_boxes_are_forced_solar(self):
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 500.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 1
        assert boxes[0]["entity"] == "__solar__"
        assert boxes[0]["force"] is True
        assert boxes[0]["ac_power"] == 0
        assert boxes[0]["benefit"] == 0

    def test_zero_wh_skipped(self):
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 0.0,
            "2026-02-16T11:00:00+00:00": 500.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)
        assert len(boxes) == 1
        assert boxes[0]["dc_power"] == pytest.approx(-0.5)

    def test_negative_wh_skipped(self):
        wh_hours = {
            "2026-02-16T10:00:00+00:00": -100.0,
            "2026-02-16T11:00:00+00:00": 300.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)
        assert len(boxes) == 1

    def test_horizon_clips_edge_periods(self):
        """Periods outside the horizon should be excluded."""
        wh_hours = {
            "2026-02-16T05:00:00+00:00": 100.0,  # before horizon
            "2026-02-16T10:00:00+00:00": 1000.0,  # inside horizon
            "2026-02-16T18:00:00+00:00": 500.0,  # after horizon end
        }
        start = datetime(2026, 2, 16, 8, 0, tzinfo=UTC)
        end = datetime(2026, 2, 16, 15, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        # Only the 10:00 period is fully inside the horizon
        # The 05:00 period (05:00-10:00) partially overlaps, should be clipped
        # The 18:00 period is after horizon end
        assert len(boxes) == 2  # 05:00 clipped + 10:00 full

        # First box: clipped from 08:00 (horizon start) to 10:00 (next period)
        assert boxes[0]["start_time"] == "2026-02-16T08:00:00+00:00"
        assert boxes[0]["finish_time"] == "2026-02-16T10:00:00+00:00"
        # Original period 05:00–10:00 (5h), clipped to 08:00–10:00 (2h).
        # Power rate is preserved: 100 Wh / 5h / 1000 = 0.02 kW.
        assert boxes[0]["dc_power"] == pytest.approx(-0.02)
        assert boxes[0]["maximum_duration"] == "7200s"

        # Second box: 10:00 to 15:00 (clipped by horizon end from 18:00)
        assert boxes[1]["start_time"] == "2026-02-16T10:00:00+00:00"
        assert boxes[1]["finish_time"] == "2026-02-16T15:00:00+00:00"
        # Original period 10:00–18:00 (8h), clipped to 10:00–15:00 (5h).
        # Power rate: 1000 Wh / 8h / 1000 = 0.125 kW.
        assert boxes[1]["dc_power"] == pytest.approx(-0.125)
        assert boxes[1]["maximum_duration"] == "18000s"

    def test_duration_strings_match_effective_period(self):
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 1000.0,
            "2026-02-16T11:00:00+00:00": 500.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        # Each period is 1 hour = 3600 seconds
        assert boxes[0]["maximum_duration"] == "3600s"
        assert boxes[0]["minimum_duration"] == "3600s"
        assert boxes[0]["minimum_burst"] == "3600s"

    def test_non_canonical_timestamp_formats(self):
        """Timestamps with non-canonical formats (trailing zeros, Z suffix)
        should still produce correct per-period dc_power values."""
        wh_hours = {
            "2026-02-16T10:00:00.000000+00:00": 1000.0,
            "2026-02-16T11:00:00.000000+00:00": 2000.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 2
        assert boxes[0]["dc_power"] == pytest.approx(-1.0)
        assert boxes[1]["dc_power"] == pytest.approx(-2.0)

    def test_each_period_gets_distinct_power(self):
        """Verify each hourly period gets its own dc_power, not an average."""
        wh_hours = {
            "2026-02-16T06:00:00+00:00": 100.0,
            "2026-02-16T07:00:00+00:00": 500.0,
            "2026-02-16T08:00:00+00:00": 1200.0,
            "2026-02-16T09:00:00+00:00": 2000.0,
            "2026-02-16T10:00:00+00:00": 2500.0,
            "2026-02-16T11:00:00+00:00": 1800.0,
        }
        start = datetime(2026, 2, 16, 0, 0, tzinfo=UTC)
        end = datetime(2026, 2, 17, 0, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 6
        powers = [b["dc_power"] for b in boxes]
        # All values should be different (not flattened to a single average)
        assert len(set(powers)) == 6
        # Verify specific conversions
        assert powers[0] == pytest.approx(-0.1)   # 100 Wh
        assert powers[2] == pytest.approx(-1.2)   # 1200 Wh
        assert powers[4] == pytest.approx(-2.5)   # 2500 Wh

    def test_horizon_clip_preserves_total_energy(self):
        """When horizon clips a period, total energy in the box must be proportional.

        A 1-hour period with 1000 Wh clipped to 30 minutes should produce a box
        whose total energy is 500 Wh (= dc_power_kw * effective_hours * 1000).
        The power rate stays the same (1 kW) but the duration is halved.
        """
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 1000.0,
            "2026-02-16T11:00:00+00:00": 600.0,
        }
        # Horizon starts at 10:30, cutting the first period in half.
        # Second period is fully inside.
        start = datetime(2026, 2, 16, 10, 30, tzinfo=UTC)
        end = datetime(2026, 2, 16, 12, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 2

        # First box: 10:00–11:00 clipped to 10:30–11:00 (30 min of 60 min)
        b0 = boxes[0]
        assert b0["start_time"] == "2026-02-16T10:30:00+00:00"
        assert b0["finish_time"] == "2026-02-16T11:00:00+00:00"
        assert b0["maximum_duration"] == "1800s"  # 30 min
        # Power rate: 1000 Wh / 1h / 1000 = 1.0 kW
        assert b0["dc_power"] == pytest.approx(-1.0)
        # Total energy in box: 1.0 kW * 0.5h = 0.5 kWh = 500 Wh (half of 1000)
        effective_hours_0 = 0.5
        total_wh_0 = abs(b0["dc_power"]) * effective_hours_0 * 1000
        assert total_wh_0 == pytest.approx(500.0)

        # Second box: 11:00–12:00, fully inside horizon, no clipping
        b1 = boxes[1]
        assert b1["start_time"] == "2026-02-16T11:00:00+00:00"
        assert b1["finish_time"] == "2026-02-16T12:00:00+00:00"
        assert b1["maximum_duration"] == "3600s"
        assert b1["dc_power"] == pytest.approx(-0.6)
        effective_hours_1 = 1.0
        total_wh_1 = abs(b1["dc_power"]) * effective_hours_1 * 1000
        assert total_wh_1 == pytest.approx(600.0)

    def test_horizon_clip_both_sides(self):
        """A single period clipped on both start and end sides."""
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 1200.0,
        }
        # Period is 10:00–11:00 (1h, last period uses +1h default).
        # Horizon clips both sides: 10:15–10:45 = 30 min of 60 min.
        start = datetime(2026, 2, 16, 10, 15, tzinfo=UTC)
        end = datetime(2026, 2, 16, 10, 45, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 1
        b = boxes[0]
        assert b["start_time"] == "2026-02-16T10:15:00+00:00"
        assert b["finish_time"] == "2026-02-16T10:45:00+00:00"
        assert b["maximum_duration"] == "1800s"
        # Power rate: 1200 Wh / 1h / 1000 = 1.2 kW (unchanged)
        assert b["dc_power"] == pytest.approx(-1.2)
        # Total energy: 1.2 kW * 0.5h = 600 Wh (half of 1200)
        total_wh = abs(b["dc_power"]) * 0.5 * 1000
        assert total_wh == pytest.approx(600.0)

    def test_sub_hour_periods_clip_correctly(self):
        """30-minute forecast periods clipped by horizon scale correctly."""
        wh_hours = {
            "2026-02-16T10:00:00+00:00": 500.0,
            "2026-02-16T10:30:00+00:00": 800.0,
            "2026-02-16T11:00:00+00:00": 600.0,
        }
        # Horizon starts at 10:15, clipping the first 30-min period
        start = datetime(2026, 2, 16, 10, 15, tzinfo=UTC)
        end = datetime(2026, 2, 16, 12, 0, tzinfo=UTC)
        boxes = solar_forecast_to_boxes(wh_hours, start, end)

        assert len(boxes) == 3

        # First box: 10:00–10:30 clipped to 10:15–10:30 (15 min of 30 min)
        b0 = boxes[0]
        assert b0["start_time"] == "2026-02-16T10:15:00+00:00"
        assert b0["finish_time"] == "2026-02-16T10:30:00+00:00"
        assert b0["maximum_duration"] == "900s"  # 15 min
        # Power rate: 500 Wh / 0.5h / 1000 = 1.0 kW
        assert b0["dc_power"] == pytest.approx(-1.0)
        # Total energy: 1.0 kW * 0.25h = 250 Wh (half of 500)
        total_wh_0 = abs(b0["dc_power"]) * 0.25 * 1000
        assert total_wh_0 == pytest.approx(250.0)

        # Second box: 10:30–11:00, fully inside, no clipping
        b1 = boxes[1]
        assert b1["dc_power"] == pytest.approx(-1.6)  # 800 Wh / 0.5h / 1000
        total_wh_1 = abs(b1["dc_power"]) * 0.5 * 1000
        assert total_wh_1 == pytest.approx(800.0)
