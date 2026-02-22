"""Tests for binary_sensor.py — Erg binary sensor entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.erg.binary_sensor import (
    ErgForceChargeSensor,
    ErgForceDischargeSensor,
    ErgScheduledBinarySensor,
    _get_current_grid_power,
    _get_running_load_ac,
    _get_running_solar_dc,
    _is_entity_scheduled_now,
    async_setup_entry,
)
from custom_components.erg.const import DOMAIN


AEST = timezone(timedelta(hours=10))


def _make_coordinator(data=None):
    coordinator = MagicMock()
    coordinator.data = data
    return coordinator


def _make_entry(entry_id="test_entry", options=None):
    entry = MagicMock()
    entry.entry_id = entry_id
    entry.options = options or {}
    return entry


class TestIsEntityScheduledNow:
    """Tests for _is_entity_scheduled_now helper."""

    def test_returns_true_when_now_in_slot(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        slot_duration = timedelta(minutes=5)
        assert _is_entity_scheduled_now(data, "switch.pool_pump", now, slot_duration) is True

    def test_returns_false_when_now_after_slot(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        now = datetime(2025, 1, 15, 10, 6, 0, tzinfo=AEST)
        slot_duration = timedelta(minutes=5)
        assert _is_entity_scheduled_now(data, "switch.pool_pump", now, slot_duration) is False

    def test_returns_false_when_now_before_slot(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        now = datetime(2025, 1, 15, 9, 59, 0, tzinfo=AEST)
        slot_duration = timedelta(minutes=5)
        assert _is_entity_scheduled_now(data, "switch.pool_pump", now, slot_duration) is False

    def test_half_open_interval_excludes_end(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        # Exactly at slot end (10:05:00) should be False
        now = datetime(2025, 1, 15, 10, 5, 0, tzinfo=AEST)
        slot_duration = timedelta(minutes=5)
        assert _is_entity_scheduled_now(data, "switch.pool_pump", now, slot_duration) is False

    def test_returns_false_for_different_entity(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        slot_duration = timedelta(minutes=5)
        assert _is_entity_scheduled_now(data, "switch.ev_charger", now, slot_duration) is False

    def test_returns_true_for_second_slot(self):
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
        now = datetime(2025, 1, 15, 10, 7, 0, tzinfo=AEST)
        slot_duration = timedelta(minutes=5)
        assert _is_entity_scheduled_now(data, "switch.pool_pump", now, slot_duration) is True


class TestErgScheduledBinarySensor:
    """Tests for ErgScheduledBinarySensor entity."""

    def test_unique_id_format(self):
        coordinator = _make_coordinator()
        entry = _make_entry(entry_id="abc123")
        sensor = ErgScheduledBinarySensor(coordinator, entry, "switch.pool_pump")
        assert sensor._attr_unique_id == "abc123_erg_switch_pool_pump_scheduled"

    def test_name(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        sensor = ErgScheduledBinarySensor(coordinator, entry, "switch.pool_pump")
        assert sensor.name == "Erg switch.pool_pump Scheduled"

    def test_is_on_returns_none_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgScheduledBinarySensor(coordinator, entry, "switch.pool_pump")
        assert sensor.is_on is None

    def test_device_info_has_correct_identifiers(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        sensor = ErgScheduledBinarySensor(coordinator, entry, "switch.pool_pump")
        info = sensor.device_info
        assert (DOMAIN, "switch.pool_pump") in info["identifiers"]


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_one_sensor_per_job_entity(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        hass = MagicMock()

        from custom_components.erg.job_entities import ErgJobEntity
        job1 = ErgJobEntity(entry.entry_id, {"entity_id": "switch.pool_pump", "job_type": "recurring"})
        job2 = ErgJobEntity(entry.entry_id, {"entity_id": "switch.ev_charger", "job_type": "recurring"})

        entry_data = {
            "coordinator": coordinator,
            "job_entities": {
                "switch.pool_pump": job1,
                "switch.ev_charger": job2,
            },
            "per_job_binary_sensors": {},
        }
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)
        # 2 per-job + 2 global (force charge, force discharge)
        assert len(added) == 4

    @pytest.mark.asyncio
    async def test_filters_dunder_entities(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        hass = MagicMock()

        from custom_components.erg.job_entities import ErgJobEntity
        job1 = ErgJobEntity(entry.entry_id, {"entity_id": "switch.pool_pump", "job_type": "recurring"})
        job2 = ErgJobEntity(entry.entry_id, {"entity_id": "__solar__", "job_type": "recurring"})

        entry_data = {
            "coordinator": coordinator,
            "job_entities": {
                "switch.pool_pump": job1,
                "__solar__": job2,
            },
            "per_job_binary_sensors": {},
        }
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)
        # 1 per-job + 2 global
        assert len(added) == 3

    @pytest.mark.asyncio
    async def test_no_entities_when_no_jobs(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        hass = MagicMock()
        entry_data = {
            "coordinator": coordinator,
            "job_entities": {},
            "per_job_binary_sensors": {},
        }
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)
        # 0 per-job + 2 global
        assert len(added) == 2

    @pytest.mark.asyncio
    async def test_creates_global_battery_sensors(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        hass = MagicMock()

        from custom_components.erg.job_entities import ErgJobEntity
        job1 = ErgJobEntity(entry.entry_id, {"entity_id": "switch.pool_pump", "job_type": "recurring"})

        entry_data = {
            "coordinator": coordinator,
            "job_entities": {"switch.pool_pump": job1},
            "per_job_binary_sensors": {},
        }
        hass.data = {"erg": {entry.entry_id: entry_data}}

        added = []
        await async_setup_entry(hass, entry, added.extend)
        types = {type(s) for s in added}
        assert ErgForceChargeSensor in types
        assert ErgForceDischargeSensor in types


class TestGetCurrentGridPower:
    """Tests for _get_current_grid_power helper."""

    def test_returns_import_and_export(self):
        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 3.0, "grid_export": 0.0},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_current_grid_power(data, now, timedelta(minutes=5)) == (3.0, 0.0)

    def test_returns_zeros_when_no_matching_slot(self):
        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 3.0, "grid_export": 0.0},
            ]
        }
        now = datetime(2025, 1, 15, 11, 0, 0, tzinfo=AEST)
        assert _get_current_grid_power(data, now, timedelta(minutes=5)) == (0.0, 0.0)

    def test_returns_zeros_when_no_battery_profile(self):
        data = {}
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_current_grid_power(data, now, timedelta(minutes=5)) == (0.0, 0.0)

    def test_half_open_interval_excludes_end(self):
        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 3.0, "grid_export": 1.0},
            ]
        }
        now = datetime(2025, 1, 15, 10, 5, 0, tzinfo=AEST)
        assert _get_current_grid_power(data, now, timedelta(minutes=5)) == (0.0, 0.0)


class TestGetRunningLoadAC:
    """Tests for _get_running_load_ac helper."""

    def test_sums_ac_of_running_loads(self):
        data = {
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T10:00:00+10:00"]},
                {"entity": "switch.ev_charger", "ac_power": 7.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_load_ac(data, now, timedelta(minutes=5)) == 9.0

    def test_excludes_dunder_entities(self):
        data = {
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T10:00:00+10:00"]},
                {"entity": "__solar__", "ac_power": 0.0, "dc_power": -3.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_load_ac(data, now, timedelta(minutes=5)) == 2.0

    def test_excludes_jobs_not_in_current_slot(self):
        data = {
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T11:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_load_ac(data, now, timedelta(minutes=5)) == 0.0

    def test_returns_zero_when_no_assignments(self):
        data = {}
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_load_ac(data, now, timedelta(minutes=5)) == 0.0


class TestGetRunningSolarDC:
    """Tests for _get_running_solar_dc helper."""

    def test_returns_abs_dc_power_of_solar(self):
        data = {
            "assignments": [
                {"entity": "__solar__", "dc_power": -3.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_solar_dc(data, now, timedelta(minutes=5)) == 3.0

    def test_ignores_non_solar_entities(self):
        data = {
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T10:00:00+10:00"]},
                {"entity": "__solar__", "dc_power": -3.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_solar_dc(data, now, timedelta(minutes=5)) == 3.0

    def test_returns_zero_when_solar_not_in_slot(self):
        data = {
            "assignments": [
                {"entity": "__solar__", "dc_power": -3.0, "slots": ["2025-01-15T11:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_solar_dc(data, now, timedelta(minutes=5)) == 0.0

    def test_returns_zero_when_no_solar(self):
        data = {
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ]
        }
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        assert _get_running_solar_dc(data, now, timedelta(minutes=5)) == 0.0


class TestErgForceChargeSensor:
    """Tests for ErgForceChargeSensor entity."""

    def test_unique_id(self):
        coordinator = _make_coordinator()
        entry = _make_entry(entry_id="abc123")
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor._attr_unique_id == "abc123_erg_force_charge"

    def test_name(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor.name == "Erg Force Charge"

    def test_is_on_returns_none_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor.is_on is None

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_true_when_grid_import_exceeds_loads(self, mock_dt):
        """grid_import=5kW, load=2kW → 3kW excess charges battery."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 5.0, "grid_export": 0.0},
            ],
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor.is_on is True

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_false_when_grid_import_equals_loads(self, mock_dt):
        """grid_import=2kW, load=2kW → no excess, just powering loads."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 2.0, "grid_export": 0.0},
            ],
            "assignments": [
                {"entity": "switch.pool_pump", "ac_power": 2.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor.is_on is False

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_true_when_no_loads_but_grid_import(self, mock_dt):
        """grid_import=3kW, no loads → all import charges battery."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 3.0, "grid_export": 0.0},
            ],
            "assignments": [],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor.is_on is True

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_false_when_no_grid_import(self, mock_dt):
        """grid_import=0 → no charging from grid."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 0.0, "grid_export": 2.0},
            ],
            "assignments": [],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceChargeSensor(coordinator, entry)
        assert sensor.is_on is False


class TestErgForceDischargeSensor:
    """Tests for ErgForceDischargeSensor entity."""

    def test_unique_id(self):
        coordinator = _make_coordinator()
        entry = _make_entry(entry_id="abc123")
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor._attr_unique_id == "abc123_erg_force_discharge"

    def test_name(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor.name == "Erg Force Discharge"

    def test_is_on_returns_none_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor.is_on is None

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_true_when_export_exceeds_solar(self, mock_dt):
        """grid_export=5kW, solar_dc=3kW → 2kW from battery."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 0.0, "grid_export": 5.0},
            ],
            "assignments": [
                {"entity": "__solar__", "dc_power": -3.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor.is_on is True

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_false_when_export_equals_solar(self, mock_dt):
        """grid_export=3kW, solar_dc=3kW → just solar export."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 0.0, "grid_export": 3.0},
            ],
            "assignments": [
                {"entity": "__solar__", "dc_power": -3.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor.is_on is False

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_true_when_export_with_no_solar(self, mock_dt):
        """grid_export=2kW, no solar → all from battery."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 0.0, "grid_export": 2.0},
            ],
            "assignments": [],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor.is_on is True

    @patch("custom_components.erg.binary_sensor.datetime")
    def test_is_on_false_when_no_export(self, mock_dt):
        """grid_export=0 → no discharge to grid."""
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        mock_dt.now.return_value.astimezone.return_value = now
        mock_dt.fromisoformat = datetime.fromisoformat

        data = {
            "battery_profile": [
                {"time": "2025-01-15T10:00:00+10:00", "grid_import": 3.0, "grid_export": 0.0},
            ],
            "assignments": [
                {"entity": "__solar__", "dc_power": -3.0, "slots": ["2025-01-15T10:00:00+10:00"]},
            ],
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        sensor = ErgForceDischargeSensor(coordinator, entry)
        assert sensor.is_on is False
