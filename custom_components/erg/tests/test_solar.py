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

        # Second box: 10:00 to 15:00 (clipped by horizon end from 18:00)
        assert boxes[1]["start_time"] == "2026-02-16T10:00:00+00:00"
        assert boxes[1]["finish_time"] == "2026-02-16T15:00:00+00:00"

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
