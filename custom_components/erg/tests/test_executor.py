"""Tests for executor.py — ScheduleExecutor."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.executor import ScheduleExecutor


AEST = timezone(timedelta(hours=10))


def _make_coordinator(data=None):
    coordinator = MagicMock()
    coordinator.data = data
    return coordinator


def _make_hass(entity_states=None):
    """Create a mock hass with optional entity states."""
    hass = MagicMock()
    states = {}
    for entity_id, state_val in (entity_states or {}).items():
        state = MagicMock()
        state.state = state_val
        states[entity_id] = state

    def get_state(entity_id):
        return states.get(entity_id)

    hass.states.get = get_state
    hass.services.async_call = AsyncMock()
    return hass


class TestScheduleExecutorStartStop:
    """Tests for start/stop lifecycle."""

    def test_start_registers_interval(self):
        hass = _make_hass()
        coordinator = _make_coordinator()
        with patch("custom_components.erg.executor.async_track_time_interval") as mock_track:
            mock_track.return_value = MagicMock()
            executor = ScheduleExecutor(hass, coordinator, "5m")
            executor.start()
            mock_track.assert_called_once()

    def test_stop_unsubscribes(self):
        hass = _make_hass()
        coordinator = _make_coordinator()
        unsub = MagicMock()
        with patch("custom_components.erg.executor.async_track_time_interval", return_value=unsub):
            executor = ScheduleExecutor(hass, coordinator, "5m")
            executor.start()
            executor.stop()
            unsub.assert_called_once()

    def test_stop_when_not_started_is_noop(self):
        hass = _make_hass()
        coordinator = _make_coordinator()
        executor = ScheduleExecutor(hass, coordinator, "5m")
        executor.stop()  # Should not raise

    def test_start_twice_only_registers_once(self):
        hass = _make_hass()
        coordinator = _make_coordinator()
        with patch("custom_components.erg.executor.async_track_time_interval") as mock_track:
            mock_track.return_value = MagicMock()
            executor = ScheduleExecutor(hass, coordinator, "5m")
            executor.start()
            executor.start()
            assert mock_track.call_count == 1


class TestScheduleExecutorPauseResume:
    """Tests for pause/resume."""

    @pytest.mark.asyncio
    async def test_paused_tick_does_nothing(self):
        hass = _make_hass({"switch.pool_pump": "off"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")
        executor.pause()

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_resume_allows_tick(self):
        hass = _make_hass({"switch.pool_pump": "off"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")
        executor.pause()
        executor.resume()

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)
        hass.services.async_call.assert_called_once()


class TestScheduleExecutorTick:
    """Tests for _async_tick behavior."""

    @pytest.mark.asyncio
    async def test_tick_with_no_data_is_noop(self):
        hass = _make_hass()
        coordinator = _make_coordinator(data=None)
        executor = ScheduleExecutor(hass, coordinator, "5m")
        await executor._async_tick(datetime.now(tz=AEST))
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_turns_on_entity_when_scheduled_and_off(self):
        hass = _make_hass({"switch.pool_pump": "off"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_called_once_with(
            "homeassistant", "turn_on", {"entity_id": "switch.pool_pump"}
        )

    @pytest.mark.asyncio
    async def test_turns_off_entity_when_not_scheduled_and_on(self):
        hass = _make_hass({"switch.pool_pump": "on"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        # Now is outside all slots
        now = datetime(2025, 1, 15, 11, 0, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_called_once_with(
            "homeassistant", "turn_off", {"entity_id": "switch.pool_pump"}
        )

    @pytest.mark.asyncio
    async def test_no_call_when_state_matches_schedule(self):
        hass = _make_hass({"switch.pool_pump": "on"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        # Now is within the slot and entity is already on
        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_unavailable_entity(self):
        hass = _make_hass({"switch.pool_pump": "unavailable"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_unknown_entity(self):
        hass = _make_hass({"switch.pool_pump": "unknown"})
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_entity_not_in_hass(self):
        hass = _make_hass({})  # No entities registered
        data = {
            "assignments": [
                {
                    "entity": "switch.pool_pump",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_dunder_entities(self):
        hass = _make_hass({"__solar__": "off"})
        data = {
            "assignments": [
                {
                    "entity": "__solar__",
                    "slots": ["2025-01-15T10:00:00+10:00"],
                },
            ]
        }
        coordinator = _make_coordinator(data=data)
        executor = ScheduleExecutor(hass, coordinator, "5m")

        now = datetime(2025, 1, 15, 10, 2, 0, tzinfo=AEST)
        await executor._async_tick(now)

        hass.services.async_call.assert_not_called()
