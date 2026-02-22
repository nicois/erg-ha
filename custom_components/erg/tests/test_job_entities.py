"""Tests for job_entities.py — ErgJobEntity and job_entity_to_dict."""

from __future__ import annotations

import pytest

from custom_components.erg.job_entities import ErgJobEntity, job_entity_to_dict
from custom_components.erg.const import DOMAIN


ENTRY_ID = "test_entry_123"


class TestErgJobEntityInit:
    """Tests for ErgJobEntity construction."""

    def test_unique_id_from_entity_id(self):
        attrs = {"entity_id": "switch.pool_pump", "enabled": True}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        assert entity._attr_unique_id == f"{ENTRY_ID}_job_switch_pool_pump"

    def test_name_from_entity_id(self):
        attrs = {"entity_id": "switch.pool_pump"}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        assert entity._attr_name == "Erg Job switch.pool_pump"

    def test_icon(self):
        attrs = {"entity_id": "switch.pool_pump"}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        assert entity._attr_icon == "mdi:briefcase-clock"

    def test_native_value_enabled(self):
        attrs = {"entity_id": "switch.pool_pump", "enabled": True}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        assert entity.native_value == "enabled"

    def test_native_value_disabled(self):
        attrs = {"entity_id": "switch.pool_pump", "enabled": False}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        assert entity.native_value == "disabled"

    def test_native_value_defaults_to_enabled(self):
        attrs = {"entity_id": "switch.pool_pump"}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        assert entity.native_value == "enabled"

    def test_extra_state_attributes_returns_copy(self):
        attrs = {"entity_id": "switch.pool_pump", "ac_power": 1.5}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        result = entity.extra_state_attributes
        assert result == attrs
        # Should be a copy
        result["ac_power"] = 999
        assert entity.extra_state_attributes["ac_power"] == 1.5

    def test_device_info_has_correct_identifiers(self):
        attrs = {"entity_id": "switch.pool_pump"}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        info = entity.device_info
        assert (DOMAIN, "switch.pool_pump") in info["identifiers"]

    def test_device_info_name(self):
        attrs = {"entity_id": "switch.pool_pump"}
        entity = ErgJobEntity(ENTRY_ID, attrs)
        info = entity.device_info
        assert info["name"] == "Erg Job: Pool Pump"


class TestErgJobEntityFromJobDict:
    """Tests for from_job_dict class method — migration from nested dicts."""

    def test_recurring_daily_job(self):
        job = {
            "entity_id": "switch.pool_pump",
            "ac_power": 1.5,
            "dc_power": 0.0,
            "force": False,
            "benefit": 0.0,
            "enabled": True,
            "recurrence": {
                "frequency": "daily",
                "time_window_start": "09:00",
                "time_window_end": "17:00",
                "maximum_duration": "3h",
                "minimum_duration": "1h",
                "minimum_burst": "30m",
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        attrs = entity.extra_state_attributes
        assert attrs["job_type"] == "recurring"
        assert attrs["frequency"] == "daily"
        assert attrs["time_window_start"] == "09:00"
        assert attrs["time_window_end"] == "17:00"
        assert attrs["maximum_duration"] == "3h"
        assert attrs["minimum_duration"] == "1h"
        assert attrs["minimum_burst"] == "30m"
        assert "day_of_week" not in attrs
        assert "days_of_week" not in attrs

    def test_recurring_weekly_job_has_day_of_week(self):
        job = {
            "entity_id": "switch.ev",
            "recurrence": {
                "frequency": "weekly",
                "time_window_start": "22:00",
                "time_window_end": "06:00",
                "maximum_duration": "6h",
                "day_of_week": 3,
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        attrs = entity.extra_state_attributes
        assert attrs["job_type"] == "recurring"
        assert attrs["frequency"] == "weekly"
        assert attrs["day_of_week"] == 3

    def test_recurring_custom_job_has_days_of_week(self):
        job = {
            "entity_id": "switch.ev",
            "recurrence": {
                "frequency": "custom",
                "time_window_start": "08:00",
                "time_window_end": "18:00",
                "maximum_duration": "4h",
                "days_of_week": [0, 2, 4],
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        attrs = entity.extra_state_attributes
        assert attrs["job_type"] == "recurring"
        assert attrs["frequency"] == "custom"
        assert attrs["days_of_week"] == [0, 2, 4]

    def test_oneshot_job(self):
        job = {
            "entity_id": "switch.heater",
            "ac_power": 2.0,
            "dc_power": 0.0,
            "force": True,
            "benefit": 5.0,
            "enabled": True,
            "recurrence": None,
            "start": "2026-02-16T14:00:00+00:00",
            "finish": "2026-02-16T18:00:00+00:00",
            "maximum_duration": "2h",
            "minimum_duration": "30m",
            "minimum_burst": "15m",
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        attrs = entity.extra_state_attributes
        assert attrs["job_type"] == "oneshot"
        assert attrs["start"] == "2026-02-16T14:00:00+00:00"
        assert attrs["finish"] == "2026-02-16T18:00:00+00:00"
        assert attrs["maximum_duration"] == "2h"
        assert attrs["force"] is True

    def test_oneshot_job_defaults(self):
        job = {
            "entity_id": "switch.heater",
            "recurrence": None,
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        attrs = entity.extra_state_attributes
        assert attrs["job_type"] == "oneshot"
        assert attrs["ac_power"] == 0.0
        assert attrs["dc_power"] == 0.0
        assert attrs["force"] is False
        assert attrs["benefit"] == 0.0
        assert attrs["enabled"] is True
        assert attrs["start"] == ""
        assert attrs["finish"] == ""
        assert attrs["maximum_duration"] == "1h"
        assert attrs["minimum_duration"] == "0s"
        assert attrs["minimum_burst"] == "0s"


class TestJobEntityToDict:
    """Tests for job_entity_to_dict — reconstruct nested dict from entity."""

    def test_recurring_daily_round_trip(self):
        job = {
            "entity_id": "switch.pool_pump",
            "ac_power": 1.5,
            "dc_power": 0.0,
            "force": False,
            "benefit": 0.0,
            "enabled": True,
            "recurrence": {
                "frequency": "daily",
                "time_window_start": "09:00",
                "time_window_end": "17:00",
                "maximum_duration": "3h",
                "minimum_duration": "1h",
                "minimum_burst": "30m",
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        result = job_entity_to_dict(entity)
        assert result["entity_id"] == "switch.pool_pump"
        assert result["ac_power"] == 1.5
        assert result["recurrence"] is not None
        assert result["recurrence"]["frequency"] == "daily"
        assert result["recurrence"]["time_window_start"] == "09:00"
        assert result["recurrence"]["time_window_end"] == "17:00"
        assert result["recurrence"]["maximum_duration"] == "3h"
        assert result["recurrence"]["minimum_duration"] == "1h"
        assert result["recurrence"]["minimum_burst"] == "30m"

    def test_recurring_weekly_round_trip(self):
        job = {
            "entity_id": "switch.ev",
            "ac_power": 7.0,
            "recurrence": {
                "frequency": "weekly",
                "time_window_start": "22:00",
                "time_window_end": "06:00",
                "maximum_duration": "6h",
                "minimum_duration": "2h",
                "minimum_burst": "1h",
                "day_of_week": 3,
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        result = job_entity_to_dict(entity)
        assert result["recurrence"]["frequency"] == "weekly"
        assert result["recurrence"]["day_of_week"] == 3

    def test_recurring_custom_round_trip(self):
        job = {
            "entity_id": "switch.ev",
            "recurrence": {
                "frequency": "custom",
                "time_window_start": "08:00",
                "time_window_end": "18:00",
                "maximum_duration": "4h",
                "days_of_week": [0, 2, 4],
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        result = job_entity_to_dict(entity)
        assert result["recurrence"]["frequency"] == "custom"
        assert result["recurrence"]["days_of_week"] == [0, 2, 4]

    def test_oneshot_round_trip(self):
        job = {
            "entity_id": "switch.heater",
            "ac_power": 2.0,
            "dc_power": 0.0,
            "force": True,
            "benefit": 5.0,
            "enabled": True,
            "recurrence": None,
            "start": "2026-02-16T14:00:00+00:00",
            "finish": "2026-02-16T18:00:00+00:00",
            "maximum_duration": "2h",
            "minimum_duration": "30m",
            "minimum_burst": "15m",
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        result = job_entity_to_dict(entity)
        assert result["recurrence"] is None
        assert result["entity_id"] == "switch.heater"
        assert result["start"] == "2026-02-16T14:00:00+00:00"
        assert result["finish"] == "2026-02-16T18:00:00+00:00"
        assert result["maximum_duration"] == "2h"
        assert result["minimum_duration"] == "30m"
        assert result["minimum_burst"] == "15m"
        assert result["force"] is True
        assert result["benefit"] == 5.0

    def test_disabled_entity_round_trip(self):
        job = {
            "entity_id": "switch.disabled_pump",
            "enabled": False,
            "recurrence": {
                "frequency": "daily",
                "time_window_start": "09:00",
                "time_window_end": "17:00",
                "maximum_duration": "1h",
            },
        }
        entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
        assert entity.native_value == "disabled"
        result = job_entity_to_dict(entity)
        assert result["enabled"] is False

    def test_full_round_trip_with_sample_jobs(self, sample_jobs):
        """Round-trip every sample job through entity → dict."""
        for job in sample_jobs:
            entity = ErgJobEntity.from_job_dict(ENTRY_ID, job)
            result = job_entity_to_dict(entity)
            assert result["entity_id"] == job["entity_id"]
            assert result["ac_power"] == job["ac_power"]
            assert result["force"] == job["force"]
            if job["recurrence"] is not None:
                assert result["recurrence"]["frequency"] == job["recurrence"]["frequency"]
