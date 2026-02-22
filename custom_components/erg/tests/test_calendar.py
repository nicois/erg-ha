"""Tests for calendar.py — Erg calendar entity."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

from custom_components.erg.calendar import (
    ErgScheduleCalendar,
    _friendly_name,
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
    entry.options = options or {"slot_duration": "5m"}
    return entry


class TestFriendlyName:
    """Tests for _friendly_name helper."""

    def test_converts_entity_id(self):
        assert _friendly_name("switch.pool_pump") == "Pool Pump"

    def test_handles_no_domain(self):
        assert _friendly_name("pool_pump") == "Pool Pump"

    def test_handles_multiple_underscores(self):
        assert _friendly_name("switch.my_ev_charger") == "My Ev Charger"


class TestErgScheduleCalendar:
    """Tests for ErgScheduleCalendar entity."""

    def test_unique_id(self):
        coordinator = _make_coordinator()
        entry = _make_entry(entry_id="abc123")
        cal = ErgScheduleCalendar(coordinator, entry)
        assert cal._attr_unique_id == "abc123_erg_schedule_calendar"

    def test_name(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        cal = ErgScheduleCalendar(coordinator, entry)
        assert cal.name == "Erg Schedule"

    def test_build_events_returns_empty_when_no_data(self):
        coordinator = _make_coordinator(data=None)
        entry = _make_entry()
        cal = ErgScheduleCalendar(coordinator, entry)
        assert cal._build_events() == []

    def test_build_events_groups_contiguous_slots(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": [
                        "2025-01-15T10:00:00+10:00",
                        "2025-01-15T10:05:00+10:00",
                        "2025-01-15T10:10:00+10:00",
                    ],
                    "run_time_seconds": 900,
                    "energy_cost": 0.15,
                    "energy_benefit": 1.5,
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        cal = ErgScheduleCalendar(coordinator, entry)
        events = cal._build_events()

        assert len(events) == 1
        assert events[0].summary == "Pool Pump"
        expected_start = datetime(2025, 1, 15, 10, 0, 0, tzinfo=AEST)
        expected_end = datetime(2025, 1, 15, 10, 15, 0, tzinfo=AEST)
        assert events[0].start == expected_start
        assert events[0].end == expected_end

    def test_build_events_splits_on_gap(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": [
                        "2025-01-15T10:00:00+10:00",
                        "2025-01-15T10:05:00+10:00",
                        # Gap here — next slot is 10:15, not 10:10
                        "2025-01-15T10:15:00+10:00",
                    ],
                    "run_time_seconds": 900,
                    "energy_cost": 0.15,
                    "energy_benefit": 1.5,
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        cal = ErgScheduleCalendar(coordinator, entry)
        events = cal._build_events()

        assert len(events) == 2
        # First group: 10:00 - 10:10
        assert events[0].start == datetime(2025, 1, 15, 10, 0, 0, tzinfo=AEST)
        assert events[0].end == datetime(2025, 1, 15, 10, 10, 0, tzinfo=AEST)
        # Second group: 10:15 - 10:20
        assert events[1].start == datetime(2025, 1, 15, 10, 15, 0, tzinfo=AEST)
        assert events[1].end == datetime(2025, 1, 15, 10, 20, 0, tzinfo=AEST)

    def test_build_events_filters_dunder_entities(self):
        data = {
            "assignments": [
                {
                    "entity": "__solar__",
                    "slots": ["2025-01-15T09:00:00+10:00"],
                    "run_time_seconds": 300,
                    "energy_cost": 0,
                    "energy_benefit": 0,
                },
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                    "run_time_seconds": 300,
                    "energy_cost": 0.05,
                    "energy_benefit": 0.5,
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        cal = ErgScheduleCalendar(coordinator, entry)
        events = cal._build_events()

        assert len(events) == 1
        assert events[0].summary == "Pool Pump"

    def test_event_property_returns_next_upcoming(self):
        now = datetime(2025, 1, 15, 9, 58, 0, tzinfo=AEST)
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                    "run_time_seconds": 300,
                    "energy_cost": 0.05,
                    "energy_benefit": 0.5,
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        cal = ErgScheduleCalendar(coordinator, entry)

        with patch("custom_components.erg.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            event = cal.event

        assert event is not None
        assert event.summary == "Pool Pump"

    def test_event_property_returns_none_when_all_past(self):
        now = datetime(2025, 1, 15, 12, 0, 0, tzinfo=AEST)
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                    "run_time_seconds": 300,
                    "energy_cost": 0.05,
                    "energy_benefit": 0.5,
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        cal = ErgScheduleCalendar(coordinator, entry)

        with patch("custom_components.erg.calendar.datetime") as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.fromisoformat = datetime.fromisoformat
            event = cal.event

        assert event is None

    @pytest.mark.asyncio
    async def test_async_get_events_filters_by_range(self):
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": [
                        "2025-01-15T10:00:00+10:00",
                        "2025-01-15T14:00:00+10:00",
                    ],
                    "run_time_seconds": 600,
                    "energy_cost": 0.10,
                    "energy_benefit": 1.0,
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        entry = _make_entry(options={"slot_duration": "5m"})
        cal = ErgScheduleCalendar(coordinator, entry)

        hass = MagicMock()
        start = datetime(2025, 1, 15, 13, 0, 0, tzinfo=AEST)
        end = datetime(2025, 1, 15, 15, 0, 0, tzinfo=AEST)

        events = await cal.async_get_events(hass, start, end)
        # Only the 14:00 slot is within the range
        assert len(events) == 1
        assert events[0].start == datetime(2025, 1, 15, 14, 0, 0, tzinfo=AEST)


class TestAsyncSetupEntry:
    """Tests for async_setup_entry."""

    @pytest.mark.asyncio
    async def test_creates_one_calendar_entity(self):
        coordinator = _make_coordinator()
        entry = _make_entry()
        hass = MagicMock()
        hass.data = {"erg": {entry.entry_id: {"coordinator": coordinator}}}

        added = []
        await async_setup_entry(hass, entry, added.extend)
        assert len(added) == 1
        assert isinstance(added[0], ErgScheduleCalendar)
