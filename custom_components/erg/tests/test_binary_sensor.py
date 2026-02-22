"""Tests for binary_sensor.py — Erg binary sensor entities."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.erg.binary_sensor import (
    ErgScheduledBinarySensor,
    _is_entity_scheduled_now,
    async_setup_entry,
)


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


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_one_sensor_per_job(self):
        coordinator = _make_coordinator()
        entry = _make_entry(
            options={
                "jobs": [
                    {"entity_id": "switch.pool_pump"},
                    {"entity_id": "switch.ev_charger"},
                ]
            }
        )
        hass = MagicMock()
        hass.data = {"erg": {entry.entry_id: {"coordinator": coordinator}}}

        added = []
        await async_setup_entry(hass, entry, added.extend)
        assert len(added) == 2

    @pytest.mark.asyncio
    async def test_filters_dunder_entities(self):
        coordinator = _make_coordinator()
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
        assert len(added) == 1
