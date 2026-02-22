"""Tests for sensor.py — Erg sensor entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.erg.sensor import (
    ErgGlobalSensor,
    ErgJobEnergyCostSensor,
    ErgJobNextStartSensor,
    ErgJobRunTimeSensor,
    GLOBAL_SENSORS,
    _find_next_job_entity,
    _get_assignment_for_entity,
    async_setup_entry,
)


def _make_coordinator(data=None):
    """Create a mock coordinator with given data."""
    coordinator = MagicMock()
    coordinator.data = data
    coordinator.last_update_success_time = None
    return coordinator


def _make_entry(entry_id="test_entry", options=None):
    """Create a mock config entry."""
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.options = options or {}
    return entry


class TestGlobalSensorDescriptions:
    """Tests for the global sensor description definitions."""

    def test_seven_global_sensors_defined(self):
        assert len(GLOBAL_SENSORS) == 7

    def test_net_value_extracts_from_data(self):
        desc = next(d for d in GLOBAL_SENSORS if d.key == "net_value")
        assert desc.value_fn({"net_value": 1.85}) == 1.85

    def test_total_cost_extracts_from_data(self):
        desc = next(d for d in GLOBAL_SENSORS if d.key == "total_cost")
        assert desc.value_fn({"total_cost": 0.45}) == 0.45

    def test_battery_soc_forecast_returns_last_entry(self):
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        data = {
            "battery_profile": [
                {"soc_kwh": 5.0},
                {"soc_kwh": 7.5},
                {"soc_kwh": 3.2},
            ]
        }
        assert desc.value_fn(data) == 3.2

    def test_battery_soc_forecast_returns_none_when_empty(self):
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        assert desc.value_fn({"battery_profile": []}) is None
        assert desc.value_fn({}) is None


class TestFindNextJobEntity:
    """Tests for _find_next_job_entity helper."""

    def test_finds_nearest_future_entity(self):
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=timezone(timedelta(hours=10)))
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": [
                        "2025-01-15T10:00:00+10:00",
                        "2025-01-15T10:05:00+10:00",
                    ],
                },
            ]
        }
        result = _find_next_job_entity(data, now)
        assert result == "switch.pool_pump"

    def test_skips_dunder_entities(self):
        now = datetime(2025, 1, 15, 8, 0, 0, tzinfo=timezone(timedelta(hours=10)))
        data = {
            "assignments": [
                {
                    "entity": "__solar__",
                    "slots": ["2025-01-15T09:00:00+10:00"],
                },
            ]
        }
        result = _find_next_job_entity(data, now)
        assert result is None

    def test_returns_none_when_all_slots_past(self):
        now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=timezone(timedelta(hours=10)))
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        result = _find_next_job_entity(data, now)
        assert result is None


class TestGetAssignmentForEntity:
    """Tests for _get_assignment_for_entity helper."""

    def test_finds_matching_assignment(self):
        data = {
            "assignments": [
                {"entity": "switch.pool_pump", "energy_cost": 0.15},
                {"entity": "switch.ev_charger", "energy_cost": 0.50},
            ]
        }
        result = _get_assignment_for_entity(data, "switch.ev_charger")
        assert result["energy_cost"] == 0.50

    def test_returns_none_when_not_found(self):
        data = {"assignments": [{"entity": "switch.pool_pump"}]}
        assert _get_assignment_for_entity(data, "switch.missing") is None


class TestGlobalSensorNativeValue:
    """Tests for ErgGlobalSensor.native_value."""

    def test_returns_none_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "net_value")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.native_value is None

    def test_schedule_age_returns_minutes(self):
        now = datetime(2025, 1, 15, 10, 15, 0, tzinfo=timezone(timedelta(hours=10)))
        last = datetime(2025, 1, 15, 10, 0, 0, tzinfo=timezone(timedelta(hours=10)))
        coordinator = _make_coordinator(data={"some": "data"})
        coordinator.last_update_success_time = last
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "schedule_age")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        with patch("custom_components.erg.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            value = sensor.native_value
        assert value == 15.0


class TestPerJobSensors:
    """Tests for per-job sensor entities."""

    def test_run_time_returns_hours(self, sample_schedule_data):
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry()
        sensor = ErgJobRunTimeSensor(coordinator, entry, "switch.pool_pump")
        assert sensor.native_value == 900 / 3600

    def test_energy_cost_returns_value(self, sample_schedule_data):
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry()
        sensor = ErgJobEnergyCostSensor(coordinator, entry, "switch.pool_pump")
        assert sensor.native_value == 0.15

    def test_run_time_returns_none_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry()
        sensor = ErgJobRunTimeSensor(coordinator, entry, "switch.pool_pump")
        assert sensor.native_value is None

    def test_energy_cost_returns_none_when_entity_missing(self, sample_schedule_data):
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry()
        sensor = ErgJobEnergyCostSensor(coordinator, entry, "switch.missing")
        assert sensor.native_value is None


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_global_and_per_job_entities(self, sample_schedule_data):
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry(
            options={
                "jobs": [
                    {"entity_id": "switch.pool_pump"},
                    {"entity_id": "__solar__"},
                ]
            }
        )
        hass = MagicMock()
        hass.data = {"erg": {entry.entry_id: {"coordinator": coordinator}}}

        added = []
        await async_setup_entry(hass, entry, added.extend)

        # 7 global + 3 per-job (only pool_pump, __solar__ filtered)
        assert len(added) == 10

    @pytest.mark.asyncio
    async def test_filters_dunder_entities(self, sample_schedule_data):
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry(
            options={
                "jobs": [
                    {"entity_id": "__solar__"},
                    {"entity_id": "__battery__"},
                ]
            }
        )
        hass = MagicMock()
        hass.data = {"erg": {entry.entry_id: {"coordinator": coordinator}}}

        added = []
        await async_setup_entry(hass, entry, added.extend)

        # Only 7 global sensors, no per-job (all filtered)
        assert len(added) == 7
