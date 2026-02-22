"""Tests for entity-linked tariff periods and price threshold computation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock

import pytest

from custom_components.erg.tariff_periods import (
    _align_price_intervals,
    _merge_entity_into_window,
    expand_recurring_tariffs,
    read_entity_forecasts,
)

UTC = timezone.utc


def _make_hass_state(
    state_value: str,
    attributes: dict[str, Any] | None = None,
) -> MagicMock:
    """Create a mock HA state object."""
    mock_state = MagicMock()
    mock_state.state = state_value
    mock_state.attributes = attributes or {}
    return mock_state


def _make_hass(states: dict[str, Any]) -> MagicMock:
    """Create a mock hass with given entity states."""
    hass = MagicMock()

    def get_state(entity_id: str):
        return states.get(entity_id)

    hass.states.get = get_state
    return hass


class TestReadEntityForecasts:
    """Tests for read_entity_forecasts."""

    def test_unavailable_entity_returns_empty(self):
        hass = _make_hass({})
        result = read_entity_forecasts(
            hass,
            "sensor.amber_general_price",
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        )
        assert result == []

    def test_unknown_state_returns_empty(self):
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state("unknown"),
        })
        result = read_entity_forecasts(
            hass,
            "sensor.amber_general_price",
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        )
        assert result == []

    def test_current_interval_only(self):
        """When no forecasts attribute, use only the current state."""
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state(
                "0.25",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T08:30:00+00:00",
                },
            ),
        })
        result = read_entity_forecasts(
            hass,
            "sensor.amber_general_price",
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        )
        assert len(result) == 1
        assert result[0]["price"] == 0.25
        assert result[0]["start"] == datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        assert result[0]["end"] == datetime(2026, 3, 1, 8, 30, tzinfo=UTC)

    def test_current_plus_forecasts(self):
        """Current interval + forecast list."""
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state(
                "0.25",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T08:30:00+00:00",
                    "forecasts": [
                        {
                            "start_time": "2026-03-01T08:30:00+00:00",
                            "end_time": "2026-03-01T09:00:00+00:00",
                            "per_kwh": 0.30,
                        },
                        {
                            "start_time": "2026-03-01T09:00:00+00:00",
                            "end_time": "2026-03-01T09:30:00+00:00",
                            "per_kwh": 0.15,
                        },
                    ],
                },
            ),
        })
        result = read_entity_forecasts(
            hass,
            "sensor.amber_general_price",
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        )
        assert len(result) == 3
        assert result[0]["price"] == 0.25
        assert result[1]["price"] == 0.30
        assert result[2]["price"] == 0.15

    def test_negative_prices_normalized(self):
        """Feed-in entities may report negative prices; abs() is applied."""
        hass = _make_hass({
            "sensor.amber_feed_in_price": _make_hass_state(
                "-0.08",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T08:30:00+00:00",
                    "forecasts": [
                        {
                            "start_time": "2026-03-01T08:30:00+00:00",
                            "end_time": "2026-03-01T09:00:00+00:00",
                            "per_kwh": -0.05,
                        },
                    ],
                },
            ),
        })
        result = read_entity_forecasts(
            hass,
            "sensor.amber_feed_in_price",
            datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
            datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        )
        assert len(result) == 2
        assert result[0]["price"] == 0.08
        assert result[1]["price"] == 0.05

    def test_horizon_clipping(self):
        """Intervals outside the horizon are clipped or excluded."""
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state(
                "0.20",
                {
                    "start_time": "2026-03-01T07:00:00+00:00",
                    "end_time": "2026-03-01T08:00:00+00:00",
                    "forecasts": [
                        {
                            "start_time": "2026-03-01T08:00:00+00:00",
                            "end_time": "2026-03-01T09:00:00+00:00",
                            "per_kwh": 0.30,
                        },
                        {
                            "start_time": "2026-03-01T21:00:00+00:00",
                            "end_time": "2026-03-01T22:00:00+00:00",
                            "per_kwh": 0.40,
                        },
                    ],
                },
            ),
        })
        result = read_entity_forecasts(
            hass,
            "sensor.amber_general_price",
            datetime(2026, 3, 1, 7, 30, tzinfo=UTC),
            datetime(2026, 3, 1, 20, 0, tzinfo=UTC),
        )
        assert len(result) == 2
        # First interval clipped to start at 07:30
        assert result[0]["start"] == datetime(2026, 3, 1, 7, 30, tzinfo=UTC)
        assert result[0]["end"] == datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        # Third interval entirely outside horizon (21:00 > 20:00) — excluded
        assert result[1]["price"] == 0.30


class TestMergeEntityIntoWindow:
    """Tests for _merge_entity_into_window."""

    def test_no_entity_intervals_uses_fallback(self):
        window_start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 1, 14, 0, tzinfo=UTC)
        result = _merge_entity_into_window([], window_start, window_end, 0.30)
        assert len(result) == 1
        assert result[0]["price"] == 0.30
        assert result[0]["start"] == window_start
        assert result[0]["end"] == window_end

    def test_full_coverage_no_gaps(self):
        window_start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        intervals = [
            {"start": datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 8, 30, tzinfo=UTC), "price": 0.20},
            {"start": datetime(2026, 3, 1, 8, 30, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 9, 0, tzinfo=UTC), "price": 0.25},
        ]
        result = _merge_entity_into_window(intervals, window_start, window_end, 0.30)
        assert len(result) == 2
        assert result[0]["price"] == 0.20
        assert result[1]["price"] == 0.25

    def test_gap_at_start_filled_with_fallback(self):
        window_start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        intervals = [
            {"start": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 10, 0, tzinfo=UTC), "price": 0.25},
        ]
        result = _merge_entity_into_window(intervals, window_start, window_end, 0.30)
        assert len(result) == 2
        assert result[0]["price"] == 0.30  # fallback for gap
        assert result[0]["end"] == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)
        assert result[1]["price"] == 0.25

    def test_gap_at_end_filled_with_fallback(self):
        window_start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        window_end = datetime(2026, 3, 1, 10, 0, tzinfo=UTC)
        intervals = [
            {"start": datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 9, 0, tzinfo=UTC), "price": 0.20},
        ]
        result = _merge_entity_into_window(intervals, window_start, window_end, 0.30)
        assert len(result) == 2
        assert result[0]["price"] == 0.20
        assert result[1]["price"] == 0.30  # fallback for gap
        assert result[1]["start"] == datetime(2026, 3, 1, 9, 0, tzinfo=UTC)


class TestAlignPriceIntervals:
    """Tests for _align_price_intervals."""

    def test_same_boundaries(self):
        import_ivs = [
            {"start": datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 9, 0, tzinfo=UTC), "price": 0.30},
        ]
        feedin_ivs = [
            {"start": datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 9, 0, tzinfo=UTC), "price": 0.05},
        ]
        result = _align_price_intervals(import_ivs, feedin_ivs)
        assert len(result) == 1
        assert result[0]["import_price"] == 0.30
        assert result[0]["feed_in_price"] == 0.05

    def test_different_boundaries_splits(self):
        import_ivs = [
            {"start": datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 10, 0, tzinfo=UTC), "price": 0.30},
        ]
        feedin_ivs = [
            {"start": datetime(2026, 3, 1, 8, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 9, 0, tzinfo=UTC), "price": 0.05},
            {"start": datetime(2026, 3, 1, 9, 0, tzinfo=UTC),
             "end": datetime(2026, 3, 1, 10, 0, tzinfo=UTC), "price": 0.08},
        ]
        result = _align_price_intervals(import_ivs, feedin_ivs)
        assert len(result) == 2
        # First period: 08:00-09:00, import=0.30, feedin=0.05
        assert result[0]["import_price"] == 0.30
        assert result[0]["feed_in_price"] == 0.05
        # Second period: 09:00-10:00, import=0.30, feedin=0.08
        assert result[1]["import_price"] == 0.30
        assert result[1]["feed_in_price"] == 0.08


class TestExpandRecurringTariffsWithEntities:
    """Tests for expand_recurring_tariffs with entity-linked tariff definitions."""

    def test_static_tariff_unchanged_with_hass(self):
        """Existing static tariffs work the same when hass is provided."""
        hass = _make_hass({})
        defs = [
            {
                "name": "Peak",
                "import_price": 0.35,
                "feed_in_price": 0.03,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "14:00",
                    "time_window_end": "20:00",
                },
            }
        ]
        start = datetime(2026, 3, 1, 0, 0, tzinfo=UTC)
        end = datetime(2026, 3, 2, 0, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC, hass)
        assert len(periods) == 1
        assert periods[0]["import_price"] == 0.35
        assert periods[0]["feed_in_price"] == 0.03

    def test_entity_linked_import_only(self):
        """Entity for import, static for feed-in."""
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state(
                "0.25",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T08:30:00+00:00",
                    "forecasts": [
                        {
                            "start_time": "2026-03-01T08:30:00+00:00",
                            "end_time": "2026-03-01T09:00:00+00:00",
                            "per_kwh": 0.30,
                        },
                    ],
                },
            ),
        })
        defs = [
            {
                "name": "Amber Import",
                "import_price": 0.20,  # fallback
                "feed_in_price": 0.05,
                "import_price_entity": "sensor.amber_general_price",
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "08:00",
                    "time_window_end": "10:00",
                },
            }
        ]
        start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC, hass)

        # Should have 3 periods: 08:00-08:30 (entity), 08:30-09:00 (entity),
        # 09:00-10:00 (fallback)
        assert len(periods) == 3
        assert periods[0]["import_price"] == 0.25  # from entity
        assert periods[0]["feed_in_price"] == 0.05  # static
        assert periods[1]["import_price"] == 0.30  # from entity
        assert periods[2]["import_price"] == 0.20  # fallback

    def test_entity_linked_both_channels(self):
        """Entity for both import and feed-in."""
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state(
                "0.25",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T09:00:00+00:00",
                },
            ),
            "sensor.amber_feed_in_price": _make_hass_state(
                "0.08",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T09:00:00+00:00",
                },
            ),
        })
        defs = [
            {
                "name": "Amber Spot",
                "import_price": 0.20,
                "feed_in_price": 0.05,
                "import_price_entity": "sensor.amber_general_price",
                "feed_in_price_entity": "sensor.amber_feed_in_price",
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "08:00",
                    "time_window_end": "09:00",
                },
            }
        ]
        start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC, hass)
        assert len(periods) == 1
        assert periods[0]["import_price"] == 0.25
        assert periods[0]["feed_in_price"] == 0.08

    def test_entity_unavailable_falls_back_to_static(self):
        """When entity is unavailable, the static price is used."""
        hass = _make_hass({})  # no entities available
        defs = [
            {
                "name": "Amber Spot",
                "import_price": 0.20,
                "feed_in_price": 0.05,
                "import_price_entity": "sensor.amber_general_price",
                "feed_in_price_entity": "sensor.amber_feed_in_price",
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "08:00",
                    "time_window_end": "10:00",
                },
            }
        ]
        start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC, hass)
        # Falls back to static prices for the whole window
        assert len(periods) == 1
        assert periods[0]["import_price"] == 0.20
        assert periods[0]["feed_in_price"] == 0.05

    def test_no_hass_falls_back_to_static(self):
        """When hass is None, entity-linked tariffs fall back to static."""
        defs = [
            {
                "name": "Amber Spot",
                "import_price": 0.20,
                "feed_in_price": 0.05,
                "import_price_entity": "sensor.amber_general_price",
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "08:00",
                    "time_window_end": "10:00",
                },
            }
        ]
        start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC, hass=None)
        assert len(periods) == 1
        assert periods[0]["import_price"] == 0.20

    def test_mixed_static_and_entity_tariffs(self):
        """Static and entity-linked tariffs coexist."""
        hass = _make_hass({
            "sensor.amber_general_price": _make_hass_state(
                "0.25",
                {
                    "start_time": "2026-03-01T08:00:00+00:00",
                    "end_time": "2026-03-01T09:00:00+00:00",
                },
            ),
        })
        defs = [
            {
                "name": "Static Peak",
                "import_price": 0.35,
                "feed_in_price": 0.03,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "14:00",
                    "time_window_end": "20:00",
                },
            },
            {
                "name": "Amber Spot",
                "import_price": 0.20,
                "feed_in_price": 0.05,
                "import_price_entity": "sensor.amber_general_price",
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "08:00",
                    "time_window_end": "10:00",
                },
            },
        ]
        start = datetime(2026, 3, 1, 8, 0, tzinfo=UTC)
        end = datetime(2026, 3, 1, 20, 0, tzinfo=UTC)
        periods = expand_recurring_tariffs(defs, start, end, UTC, hass)
        # First tariff: 1 static period (14:00-20:00)
        # Second tariff: entity covers 08:00-09:00, fallback 09:00-10:00
        assert len(periods) == 3


class TestComputePriceThresholds:
    """Tests for coordinator._compute_price_thresholds logic.

    Since _compute_price_thresholds is a method on the coordinator class,
    we test the logic directly by importing it.
    """

    def test_import_threshold_is_max_import_price(self):
        from custom_components.erg.coordinator import ErgScheduleCoordinator

        # We can't easily instantiate the coordinator, so test the method
        # by calling it on a partially mocked instance
        coord = object.__new__(ErgScheduleCoordinator)

        schedule_data = {
            "battery_profile": [
                {"time": "2026-03-01T08:00:00+00:00", "grid_import": 1.5, "grid_export": 0},
                {"time": "2026-03-01T08:30:00+00:00", "grid_import": 0.5, "grid_export": 0},
                {"time": "2026-03-01T09:00:00+00:00", "grid_import": 0, "grid_export": 2.0},
            ]
        }
        tariff_periods = [
            {"start": "2026-03-01T08:00:00+00:00", "end": "2026-03-01T08:30:00+00:00",
             "import_price": 0.25, "feed_in_price": 0.05},
            {"start": "2026-03-01T08:30:00+00:00", "end": "2026-03-01T09:00:00+00:00",
             "import_price": 0.15, "feed_in_price": 0.05},
            {"start": "2026-03-01T09:00:00+00:00", "end": "2026-03-01T09:30:00+00:00",
             "import_price": 0.35, "feed_in_price": 0.08},
        ]

        import_t, export_t = coord._compute_price_thresholds(schedule_data, tariff_periods)
        # Import at 0.25 and 0.15 → max is 0.25
        assert import_t == 0.25
        # Export at 0.08
        assert export_t == 0.08

    def test_no_import_activity(self):
        from custom_components.erg.coordinator import ErgScheduleCoordinator

        coord = object.__new__(ErgScheduleCoordinator)
        schedule_data = {
            "battery_profile": [
                {"time": "2026-03-01T08:00:00+00:00", "grid_import": 0, "grid_export": 1.0},
            ]
        }
        tariff_periods = [
            {"start": "2026-03-01T08:00:00+00:00", "end": "2026-03-01T09:00:00+00:00",
             "import_price": 0.30, "feed_in_price": 0.05},
        ]
        import_t, export_t = coord._compute_price_thresholds(schedule_data, tariff_periods)
        assert import_t is None
        assert export_t == 0.05

    def test_no_export_activity(self):
        from custom_components.erg.coordinator import ErgScheduleCoordinator

        coord = object.__new__(ErgScheduleCoordinator)
        schedule_data = {
            "battery_profile": [
                {"time": "2026-03-01T08:00:00+00:00", "grid_import": 2.0, "grid_export": 0},
            ]
        }
        tariff_periods = [
            {"start": "2026-03-01T08:00:00+00:00", "end": "2026-03-01T09:00:00+00:00",
             "import_price": 0.30, "feed_in_price": 0.05},
        ]
        import_t, export_t = coord._compute_price_thresholds(schedule_data, tariff_periods)
        assert import_t == 0.30
        assert export_t is None

    def test_empty_battery_profile(self):
        from custom_components.erg.coordinator import ErgScheduleCoordinator

        coord = object.__new__(ErgScheduleCoordinator)
        import_t, export_t = coord._compute_price_thresholds(
            {"battery_profile": []}, [{"start": "x", "end": "y"}]
        )
        assert import_t is None
        assert export_t is None

    def test_empty_tariff_periods(self):
        from custom_components.erg.coordinator import ErgScheduleCoordinator

        coord = object.__new__(ErgScheduleCoordinator)
        import_t, export_t = coord._compute_price_thresholds(
            {"battery_profile": [{"time": "2026-03-01T08:00:00+00:00", "grid_import": 1.0}]},
            [],
        )
        assert import_t is None
        assert export_t is None

    def test_export_threshold_is_min_feedin_price(self):
        from custom_components.erg.coordinator import ErgScheduleCoordinator

        coord = object.__new__(ErgScheduleCoordinator)
        schedule_data = {
            "battery_profile": [
                {"time": "2026-03-01T08:00:00+00:00", "grid_import": 0, "grid_export": 1.0},
                {"time": "2026-03-01T08:30:00+00:00", "grid_import": 0, "grid_export": 2.0},
                {"time": "2026-03-01T09:00:00+00:00", "grid_import": 0, "grid_export": 0.5},
            ]
        }
        tariff_periods = [
            {"start": "2026-03-01T08:00:00+00:00", "end": "2026-03-01T08:30:00+00:00",
             "import_price": 0.30, "feed_in_price": 0.10},
            {"start": "2026-03-01T08:30:00+00:00", "end": "2026-03-01T09:00:00+00:00",
             "import_price": 0.30, "feed_in_price": 0.05},
            {"start": "2026-03-01T09:00:00+00:00", "end": "2026-03-01T09:30:00+00:00",
             "import_price": 0.30, "feed_in_price": 0.08},
        ]
        import_t, export_t = coord._compute_price_thresholds(schedule_data, tariff_periods)
        assert import_t is None
        # Export at 0.10, 0.05, 0.08 → min is 0.05
        assert export_t == 0.05
