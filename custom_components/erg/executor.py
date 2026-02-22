"""Schedule executor for the Erg Energy Scheduler integration.

Turns HA entities on/off according to the optimized schedule at each slot tick.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import DEFAULT_SLOT_DURATION, parse_slot_duration_seconds

_LOGGER = logging.getLogger(__name__)


class ScheduleExecutor:
    """Executes the schedule by turning HA entities on/off at each slot tick."""

    def __init__(
        self,
        hass: HomeAssistant,
        coordinator: DataUpdateCoordinator,
        slot_duration_str: str = DEFAULT_SLOT_DURATION,
    ) -> None:
        self._hass = hass
        self._coordinator = coordinator
        self._slot_duration_str = slot_duration_str
        self._slot_seconds = parse_slot_duration_seconds(slot_duration_str)
        self._slot_duration = timedelta(seconds=self._slot_seconds)
        self._unsub = None
        self._paused = False

    def start(self) -> None:
        """Register the periodic tick callback."""
        if self._unsub is not None:
            return
        self._unsub = async_track_time_interval(
            self._hass,
            self._async_tick,
            self._slot_duration,
        )

    def stop(self) -> None:
        """Unsubscribe the periodic tick callback."""
        if self._unsub is not None:
            self._unsub()
            self._unsub = None

    def pause(self) -> None:
        """Pause execution without unsubscribing."""
        self._paused = True

    def resume(self) -> None:
        """Resume execution after pause."""
        self._paused = False

    async def _async_tick(self, now: datetime | None = None) -> None:
        """Evaluate the schedule and turn entities on/off as needed."""
        if self._paused:
            return

        data = self._coordinator.data
        if data is None:
            return

        if now is None:
            now = datetime.now().astimezone()

        for assignment in data.get("assignments", []):
            entity_id = assignment.get("entity", "")
            if entity_id.startswith("__"):
                continue

            should_be_on = self._is_slot_active(assignment, now)
            await self._apply_state(entity_id, should_be_on)

    def _is_slot_active(self, assignment: dict[str, Any], now: datetime) -> bool:
        """Check if now falls within any slot for this assignment."""
        for slot_str in assignment.get("slots", []):
            slot_start = datetime.fromisoformat(slot_str)
            slot_end = slot_start + self._slot_duration
            if slot_start <= now < slot_end:
                return True
        return False

    async def _apply_state(self, entity_id: str, should_be_on: bool) -> None:
        """Turn an entity on or off if its current state doesn't match."""
        state = self._hass.states.get(entity_id)
        if state is None:
            return
        if state.state in ("unavailable", "unknown"):
            return

        current_on = state.state == "on"
        if should_be_on and not current_on:
            _LOGGER.debug("Turning on %s", entity_id)
            await self._hass.services.async_call(
                "homeassistant", "turn_on", {"entity_id": entity_id}
            )
        elif not should_be_on and current_on:
            _LOGGER.debug("Turning off %s", entity_id)
            await self._hass.services.async_call(
                "homeassistant", "turn_off", {"entity_id": entity_id}
            )
