"""Tests for number.py — ErgJobElapsedNumber restore behaviour."""

from __future__ import annotations

from datetime import datetime, timezone, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.number import ErgJobElapsedNumber


def _make_coordinator():
    coordinator = MagicMock()
    coordinator.get_elapsed = MagicMock(return_value=0)
    coordinator.set_elapsed = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    return coordinator


def _make_state(state_value, last_updated):
    state = MagicMock()
    state.state = str(state_value)
    state.last_updated = last_updated
    return state


class TestErgJobElapsedNumberRestore:
    """Tests for elapsed restore on startup."""

    @pytest.mark.asyncio
    async def test_restores_elapsed_from_today(self):
        coordinator = _make_coordinator()
        entity = ErgJobElapsedNumber(coordinator, "entry1", "switch.ev")

        now = datetime(2026, 2, 27, 14, 0, 0, tzinfo=timezone(timedelta(hours=11)))
        saved_state = _make_state(45.0, now - timedelta(hours=1))  # same day

        with patch.object(entity, "async_get_last_state", new=AsyncMock(return_value=saved_state), create=True):
            with patch("custom_components.erg.number.datetime") as mock_dt:
                mock_dt.now.return_value = now
                await entity.async_added_to_hass()

        coordinator.set_elapsed.assert_called_once_with("switch.ev", 45.0 * 60.0)

    @pytest.mark.asyncio
    async def test_skips_restore_from_previous_day(self):
        coordinator = _make_coordinator()
        entity = ErgJobElapsedNumber(coordinator, "entry1", "switch.ev")

        now = datetime(2026, 2, 27, 8, 0, 0, tzinfo=timezone(timedelta(hours=11)))
        yesterday = now - timedelta(days=1)
        saved_state = _make_state(120.0, yesterday)

        with patch.object(entity, "async_get_last_state", new=AsyncMock(return_value=saved_state), create=True):
            with patch("custom_components.erg.number.datetime") as mock_dt:
                mock_dt.now.return_value = now
                await entity.async_added_to_hass()

        coordinator.set_elapsed.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_restore_when_no_state(self):
        coordinator = _make_coordinator()
        entity = ErgJobElapsedNumber(coordinator, "entry1", "switch.ev")

        with patch.object(entity, "async_get_last_state", new=AsyncMock(return_value=None), create=True):
            await entity.async_added_to_hass()

        coordinator.set_elapsed.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_restore_when_unavailable(self):
        coordinator = _make_coordinator()
        entity = ErgJobElapsedNumber(coordinator, "entry1", "switch.ev")

        state = MagicMock()
        state.state = "unavailable"

        with patch.object(entity, "async_get_last_state", new=AsyncMock(return_value=state), create=True):
            await entity.async_added_to_hass()

        coordinator.set_elapsed.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_restore_when_zero(self):
        coordinator = _make_coordinator()
        entity = ErgJobElapsedNumber(coordinator, "entry1", "switch.ev")

        now = datetime(2026, 2, 27, 14, 0, 0, tzinfo=timezone(timedelta(hours=11)))
        saved_state = _make_state(0.0, now - timedelta(minutes=30))

        with patch.object(entity, "async_get_last_state", new=AsyncMock(return_value=saved_state), create=True):
            with patch("custom_components.erg.number.datetime") as mock_dt:
                mock_dt.now.return_value = now
                await entity.async_added_to_hass()

        coordinator.set_elapsed.assert_not_called()

    @pytest.mark.asyncio
    async def test_skips_restore_when_invalid_state(self):
        coordinator = _make_coordinator()
        entity = ErgJobElapsedNumber(coordinator, "entry1", "switch.ev")

        now = datetime(2026, 2, 27, 14, 0, 0, tzinfo=timezone(timedelta(hours=11)))
        saved_state = _make_state("not_a_number", now - timedelta(minutes=30))

        with patch.object(entity, "async_get_last_state", new=AsyncMock(return_value=saved_state), create=True):
            with patch("custom_components.erg.number.datetime") as mock_dt:
                mock_dt.now.return_value = now
                await entity.async_added_to_hass()

        coordinator.set_elapsed.assert_not_called()
