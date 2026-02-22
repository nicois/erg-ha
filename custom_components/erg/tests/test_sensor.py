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
from custom_components.erg.const import DOMAIN
from custom_components.erg.job_entities import ErgJobEntity


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

    def test_global_sensors_defined(self):
        assert len(GLOBAL_SENSORS) == 8

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


class TestBatterySocForecastAttributes:
    """Tests for battery_soc_forecast extra_state_attributes."""

    def test_returns_forecast_list(self):
        data = {
            "battery_profile": [
                {"time": "2025-01-15T09:00:00+10:00", "soc_kwh": 5.0},
                {"time": "2025-01-15T12:00:00+10:00", "soc_kwh": 7.5},
                {"time": "2025-01-15T18:00:00+10:00", "soc_kwh": 3.2},
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        attrs = sensor.extra_state_attributes
        assert attrs is not None
        forecast = attrs["forecast"]
        assert len(forecast) == 3
        # Each entry is [epoch_ms, soc_kwh]
        assert forecast[0][1] == 5.0
        assert forecast[1][1] == 7.5
        assert forecast[2][1] == 3.2
        # Timestamps are integers (epoch milliseconds)
        assert isinstance(forecast[0][0], int)
        # Verify ordering preserved
        assert forecast[0][0] < forecast[1][0] < forecast[2][0]

    def test_returns_none_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.extra_state_attributes is None

    def test_returns_none_when_profile_empty(self):
        coordinator = _make_coordinator(data={"battery_profile": []})
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.extra_state_attributes is None

    def test_returns_none_when_profile_missing(self):
        coordinator = _make_coordinator(data={})
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.extra_state_attributes is None

    def test_non_battery_sensor_returns_none(self):
        coordinator = _make_coordinator(data={"net_value": 1.0})
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "net_value")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.extra_state_attributes is None

    def test_skips_entries_with_missing_fields(self):
        data = {
            "battery_profile": [
                {"time": "2025-01-15T09:00:00+10:00", "soc_kwh": 5.0},
                {"time": "2025-01-15T12:00:00+10:00"},  # missing soc_kwh
                {"soc_kwh": 3.2},  # missing time
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry()
        desc = next(d for d in GLOBAL_SENSORS if d.key == "battery_soc_forecast")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        attrs = sensor.extra_state_attributes
        assert len(attrs["forecast"]) == 1
        assert attrs["forecast"][0][1] == 5.0


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

    def test_aggregates_multiple_assignments_for_same_entity(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.ev_charger",
                    "slots": ["2026-02-27T14:30:00+11:00", "2026-02-27T14:45:00+11:00"],
                    "run_time_seconds": 1800,
                    "energy_cost": 0.10,
                },
                {
                    "entity": "switch.ev_charger",
                    "slots": ["2026-02-28T11:00:00+11:00", "2026-02-28T11:15:00+11:00"],
                    "run_time_seconds": 1800,
                    "energy_cost": 0.15,
                },
            ]
        }
        result = _get_assignment_for_entity(data, "switch.ev_charger")
        assert result["run_time_seconds"] == 3600
        assert result["energy_cost"] == 0.25
        assert len(result["slots"]) == 4

    def test_single_assignment_unchanged(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2026-02-27T09:00:00+11:00"],
                    "run_time_seconds": 900,
                    "energy_cost": 0.05,
                },
            ]
        }
        result = _get_assignment_for_entity(data, "switch.pool_pump")
        assert result["run_time_seconds"] == 900
        assert result["energy_cost"] == 0.05
        assert len(result["slots"]) == 1


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

    def test_schedule_view_url_returns_url(self):
        coordinator = _make_coordinator(data={"some": "data"})
        coordinator.hass = MagicMock()
        entry = _make_entry()
        coordinator.hass.data = {
            DOMAIN: {entry.entry_id: {"base_url": "http://192.168.1.10:8234"}}
        }
        desc = next(d for d in GLOBAL_SENSORS if d.key == "schedule_view_url")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.native_value == "http://192.168.1.10:8234/api/v1/schedule/view"

    def test_schedule_view_url_returns_none_when_no_base_url(self):
        coordinator = _make_coordinator(data={"some": "data"})
        coordinator.hass = MagicMock()
        entry = _make_entry()
        coordinator.hass.data = {DOMAIN: {entry.entry_id: {}}}
        desc = next(d for d in GLOBAL_SENSORS if d.key == "schedule_view_url")
        sensor = ErgGlobalSensor(coordinator, entry, desc)
        assert sensor.native_value is None


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

    def test_next_start_device_info(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        sensor = ErgJobNextStartSensor(coordinator, entry, "switch.pool_pump")
        info = sensor.device_info
        assert (DOMAIN, "switch.pool_pump") in info["identifiers"]

    def test_run_time_device_info(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        sensor = ErgJobRunTimeSensor(coordinator, entry, "switch.pool_pump")
        info = sensor.device_info
        assert (DOMAIN, "switch.pool_pump") in info["identifiers"]

    def test_run_time_aggregates_multi_day(self):
        data = {
            "assignments": [
                {"entity": "switch.ev", "run_time_seconds": 3600, "energy_cost": 0.10,
                 "slots": ["2026-02-27T14:30:00+11:00"]},
                {"entity": "switch.ev", "run_time_seconds": 3600, "energy_cost": 0.15,
                 "slots": ["2026-02-28T11:00:00+11:00"]},
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry()
        sensor = ErgJobRunTimeSensor(coordinator, entry, "switch.ev")
        assert sensor.native_value == 7200 / 3600

    def test_energy_cost_aggregates_multi_day(self):
        data = {
            "assignments": [
                {"entity": "switch.ev", "run_time_seconds": 3600, "energy_cost": 0.10,
                 "slots": ["2026-02-27T14:30:00+11:00"]},
                {"entity": "switch.ev", "run_time_seconds": 3600, "energy_cost": 0.15,
                 "slots": ["2026-02-28T11:00:00+11:00"]},
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry()
        sensor = ErgJobEnergyCostSensor(coordinator, entry, "switch.ev")
        assert sensor.native_value == 0.25

    def test_next_start_finds_slot_in_later_assignment(self):
        """When first assignment's slots are all past, next_start checks later ones."""
        data = {
            "assignments": [
                {"entity": "switch.ev",
                 "slots": ["2026-02-27T14:30:00+11:00"]},
                {"entity": "switch.ev",
                 "slots": ["2026-02-28T11:00:00+11:00"]},
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry()
        sensor = ErgJobNextStartSensor(coordinator, entry, "switch.ev")
        # "now" is after the first slot but before the second
        now = datetime(2026, 2, 28, 0, 0, 0, tzinfo=timezone(timedelta(hours=11)))
        with patch("custom_components.erg.sensor.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            value = sensor.native_value
        assert value == "2026-02-28T11:00:00+11:00"


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_global_and_per_job_entities_from_migration(self, sample_schedule_data):
        """Migration path: jobs in options are converted to job entities."""
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry(
            options={
                "jobs": [
                    {"entity_id": "switch.pool_pump", "recurrence": {"frequency": "daily", "time_window_start": "09:00", "time_window_end": "17:00", "maximum_duration": "3h"}},
                    {"entity_id": "__solar__", "recurrence": {"frequency": "daily", "time_window_start": "06:00", "time_window_end": "18:00", "maximum_duration": "12h"}},
                ]
            }
        )
        hass = MagicMock()
        entry_data = {
            "coordinator": coordinator,
            "job_entities": {},
            "per_job_sensors": {},
        }
        # Pre-populate migration data
        entry_data["pending_job_migration"] = list(entry.options["jobs"])
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)

        # 8 global + 1 job entity (pool_pump, __solar__ filtered) + 3 per-job sensors
        assert len(added) == 12

    @pytest.mark.asyncio
    async def test_creates_sensors_from_existing_job_entities(self, sample_schedule_data):
        """Non-migration path: job entities already exist."""
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry(options={})

        # Pre-existing job entity
        job_entity = ErgJobEntity(entry.entry_id, {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        hass = MagicMock()
        entry_data = {
            "coordinator": coordinator,
            "job_entities": {"switch.pool_pump": job_entity},
            "per_job_sensors": {},
        }
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)

        # 8 global + 1 job entity + 3 per-job sensors
        assert len(added) == 12

    @pytest.mark.asyncio
    async def test_filters_dunder_entities(self, sample_schedule_data):
        coordinator = _make_coordinator(data=sample_schedule_data)
        entry = _make_entry(options={})

        hass = MagicMock()
        entry_data = {
            "coordinator": coordinator,
            "job_entities": {},
            "per_job_sensors": {},
        }
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)

        # Only 8 global sensors, no per-job (no job entities)
        assert len(added) == 8
