"""Binary sensor platform for the Erg Energy Scheduler integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_SLOT_DURATION, DOMAIN, parse_slot_duration_seconds


def _sanitize_entity(entity_id: str) -> str:
    """Replace dots with underscores for unique ID usage."""
    return entity_id.replace(".", "_")


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg binary sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[BinarySensorEntity] = []
    jobs = entry.options.get("jobs", [])
    for job in jobs:
        entity_id = job.get("entity_id", "")
        if entity_id.startswith("__"):
            continue
        entities.append(ErgScheduledBinarySensor(coordinator, entry, entity_id))

    async_add_entities(entities)


class ErgScheduledBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor indicating whether a device is scheduled to run now."""

    def __init__(self, coordinator, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_erg_{sanitized}_scheduled"
        self._entry = entry

    @property
    def name(self) -> str:
        return f"Erg {self._entity_id} Scheduled"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None

        slot_duration_str = self._entry.options.get("slot_duration", DEFAULT_SLOT_DURATION)
        slot_seconds = parse_slot_duration_seconds(slot_duration_str)
        slot_duration = timedelta(seconds=slot_seconds)

        now = datetime.now().astimezone()
        return _is_entity_scheduled_now(data, self._entity_id, now, slot_duration)


def _is_entity_scheduled_now(
    data: dict[str, Any],
    entity_id: str,
    now: datetime,
    slot_duration: timedelta,
) -> bool:
    """Check if now falls within any scheduled slot for the given entity."""
    for assignment in data.get("assignments", []):
        if assignment.get("entity") != entity_id:
            continue
        for slot_str in assignment.get("slots", []):
            slot_start = datetime.fromisoformat(slot_str)
            slot_end = slot_start + slot_duration
            if slot_start <= now < slot_end:
                return True
    return False
