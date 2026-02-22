"""Binary sensor platform for the Erg Energy Scheduler integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_SLOT_DURATION, DOMAIN, make_job_device_info, parse_slot_duration_seconds


def _sanitize_entity(entity_id: str) -> str:
    """Replace dots with underscores for unique ID usage."""
    return entity_id.replace(".", "_")


def _get_current_grid_power(
    data: dict[str, Any],
    now: datetime,
    slot_duration: timedelta,
) -> tuple[float, float]:
    """Return (grid_import, grid_export) for the current time slot, or (0, 0)."""
    for entry in data.get("battery_profile", []):
        slot_start = datetime.fromisoformat(entry["time"])
        slot_end = slot_start + slot_duration
        if slot_start <= now < slot_end:
            return (
                float(entry.get("grid_import", 0)),
                float(entry.get("grid_export", 0)),
            )
    return (0.0, 0.0)


def _get_running_load_ac(
    data: dict[str, Any],
    now: datetime,
    slot_duration: timedelta,
) -> float:
    """Sum AC power of all non-solar (non-dunder) assignments running now."""
    total = 0.0
    for assignment in data.get("assignments", []):
        if assignment.get("entity", "").startswith("__"):
            continue
        for slot_str in assignment.get("slots", []):
            slot_start = datetime.fromisoformat(slot_str)
            if slot_start <= now < slot_start + slot_duration:
                total += float(assignment.get("ac_power", 0))
                break
    return total


def _get_running_solar_dc(
    data: dict[str, Any],
    now: datetime,
    slot_duration: timedelta,
) -> float:
    """Sum absolute DC power of solar (__solar__) assignments running now."""
    total = 0.0
    for assignment in data.get("assignments", []):
        if assignment.get("entity") != "__solar__":
            continue
        for slot_str in assignment.get("slots", []):
            slot_start = datetime.fromisoformat(slot_str)
            if slot_start <= now < slot_start + slot_duration:
                total += abs(float(assignment.get("dc_power", 0)))
                break
    return total


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg binary sensors from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    # Store callback for dynamic creation by services
    entry_data["add_job_binary_sensors"] = async_add_entities

    subentry_id_map = entry_data.get("_subentry_id_map", {})
    no_subentry: list[BinarySensorEntity] = []
    by_subentry: dict[str, list[BinarySensorEntity]] = {}

    # Derive binary sensors from live job entities
    job_entities = entry_data.get("job_entities", {})
    for entity_id in job_entities:
        if entity_id.startswith("__"):
            continue
        sid = subentry_id_map.get(entity_id)
        sensor = ErgScheduledBinarySensor(coordinator, entry, entity_id)
        entry_data.setdefault("per_job_binary_sensors", {})[entity_id] = [sensor]
        if sid is None:
            no_subentry.append(sensor)
        else:
            by_subentry.setdefault(sid, []).append(sensor)

    # Global battery binary sensors (not per-job)
    no_subentry.append(ErgForceChargeSensor(coordinator, entry))
    no_subentry.append(ErgForceDischargeSensor(coordinator, entry))

    async_add_entities(no_subentry)
    for sid, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=sid)


class ErgScheduledBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor indicating whether a device is scheduled to run now."""

    def __init__(self, coordinator, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_erg_{sanitized}_scheduled"
        self._entry = entry

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

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


class ErgForceChargeSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor ON when grid imports more than scheduled loads need (battery charging from grid)."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_erg_force_charge"

    @property
    def name(self) -> str:
        return "Erg Force Charge"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None

        slot_duration_str = self._entry.options.get("slot_duration", DEFAULT_SLOT_DURATION)
        slot_seconds = parse_slot_duration_seconds(slot_duration_str)
        slot_duration = timedelta(seconds=slot_seconds)

        now = datetime.now().astimezone()
        grid_import, _ = _get_current_grid_power(data, now, slot_duration)
        load_ac = _get_running_load_ac(data, now, slot_duration)
        return grid_import - load_ac > 0


class ErgForceDischargeSensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor ON when grid exports more than solar provides (battery discharging to grid)."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_erg_force_discharge"

    @property
    def name(self) -> str:
        return "Erg Force Discharge"

    @property
    def is_on(self) -> bool | None:
        data = self.coordinator.data
        if data is None:
            return None

        slot_duration_str = self._entry.options.get("slot_duration", DEFAULT_SLOT_DURATION)
        slot_seconds = parse_slot_duration_seconds(slot_duration_str)
        slot_duration = timedelta(seconds=slot_seconds)

        now = datetime.now().astimezone()
        _, grid_export = _get_current_grid_power(data, now, slot_duration)
        solar_dc = _get_running_solar_dc(data, now, slot_duration)
        return grid_export - solar_dc > 0


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
