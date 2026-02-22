"""Sensor platform for the Erg Energy Scheduler integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN


class ErgSensorEntityDescription:
    """Describes an Erg sensor entity."""

    def __init__(
        self,
        *,
        key: str,
        name: str,
        device_class: Any = None,
        state_class: Any = None,
        native_unit_of_measurement: str | None = None,
        value_fn: Any = None,
    ) -> None:
        self.key = key
        self.name = name
        self.device_class = device_class
        self.state_class = state_class
        self.native_unit_of_measurement = native_unit_of_measurement
        self.value_fn = value_fn


GLOBAL_SENSORS: tuple[ErgSensorEntityDescription, ...] = (
    ErgSensorEntityDescription(
        key="net_value",
        name="Erg Net Value",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("net_value"),
    ),
    ErgSensorEntityDescription(
        key="total_cost",
        name="Erg Total Cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("total_cost"),
    ),
    ErgSensorEntityDescription(
        key="total_benefit",
        name="Erg Total Benefit",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("total_benefit"),
    ),
    ErgSensorEntityDescription(
        key="export_revenue",
        name="Erg Export Revenue",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("export_revenue"),
    ),
    ErgSensorEntityDescription(
        key="battery_soc_forecast",
        name="Erg Battery SoC Forecast",
        device_class=SensorDeviceClass.ENERGY_STORAGE,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kWh",
        value_fn=lambda data: (
            data["battery_profile"][-1]["soc_kwh"]
            if data.get("battery_profile")
            else None
        ),
    ),
    ErgSensorEntityDescription(
        key="next_job",
        name="Erg Next Job",
        value_fn=None,  # handled specially
    ),
    ErgSensorEntityDescription(
        key="schedule_age",
        name="Erg Schedule Age",
        device_class=SensorDeviceClass.DURATION,
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="min",
        value_fn=None,  # handled specially
    ),
)


def _sanitize_entity(entity_id: str) -> str:
    """Replace dots with underscores for unique ID usage."""
    return entity_id.replace(".", "_")


def _find_next_job_entity(data: dict[str, Any], now: datetime) -> str | None:
    """Find the entity_id of the nearest future scheduled job."""
    earliest_entity = None
    earliest_time = None

    for assignment in data.get("assignments", []):
        entity = assignment.get("entity", "")
        if entity.startswith("__"):
            continue
        for slot_str in assignment.get("slots", []):
            slot_time = datetime.fromisoformat(slot_str)
            if slot_time > now:
                if earliest_time is None or slot_time < earliest_time:
                    earliest_time = slot_time
                    earliest_entity = entity
                break  # slots are ordered, first future slot is earliest for this entity

    return earliest_entity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg sensors from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]

    entities: list[SensorEntity] = []

    # Global sensors
    for description in GLOBAL_SENSORS:
        entities.append(ErgGlobalSensor(coordinator, entry, description))

    # Per-job sensors
    jobs = entry.options.get("jobs", [])
    for job in jobs:
        entity_id = job.get("entity_id", "")
        if entity_id.startswith("__"):
            continue
        entities.append(ErgJobNextStartSensor(coordinator, entry, entity_id))
        entities.append(ErgJobRunTimeSensor(coordinator, entry, entity_id))
        entities.append(ErgJobEnergyCostSensor(coordinator, entry, entity_id))

    async_add_entities(entities)


class ErgGlobalSensor(CoordinatorEntity, SensorEntity):
    """A global Erg schedule sensor."""

    entity_description: ErgSensorEntityDescription

    def __init__(self, coordinator, entry: ConfigEntry, description: ErgSensorEntityDescription) -> None:
        super().__init__(coordinator)
        self.entity_description = description
        self._attr_unique_id = f"{entry.entry_id}_erg_{description.key}"
        self._entry = entry

    @property
    def name(self) -> str:
        return self.entity_description.name

    @property
    def device_class(self):
        return getattr(self.entity_description, "device_class", None)

    @property
    def state_class(self):
        return getattr(self.entity_description, "state_class", None)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return getattr(self.entity_description, "native_unit_of_measurement", None)

    @property
    def native_value(self):
        data = self.coordinator.data
        if data is None:
            return None

        key = self.entity_description.key

        if key == "next_job":
            now = datetime.now().astimezone()
            return _find_next_job_entity(data, now)

        if key == "schedule_age":
            last = getattr(self.coordinator, "last_update_success_time", None)
            if last is None:
                return None
            now = datetime.now().astimezone()
            delta = now - last
            return round(delta.total_seconds() / 60, 1)

        if self.entity_description.value_fn is not None:
            return self.entity_description.value_fn(data)

        return None


def _get_assignment_for_entity(data: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    """Find the assignment dict for a given entity_id."""
    for assignment in data.get("assignments", []):
        if assignment.get("entity") == entity_id:
            return assignment
    return None


class ErgJobNextStartSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing the next scheduled start time for a job."""

    def __init__(self, coordinator, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_erg_{sanitized}_next_start"

    @property
    def name(self) -> str:
        return f"Erg {self._entity_id} Next Start"

    @property
    def native_value(self) -> str | None:
        data = self.coordinator.data
        if data is None:
            return None
        assignment = _get_assignment_for_entity(data, self._entity_id)
        if assignment is None:
            return None
        now = datetime.now().astimezone()
        for slot_str in assignment.get("slots", []):
            slot_time = datetime.fromisoformat(slot_str)
            if slot_time > now:
                return slot_str
        return None


class ErgJobRunTimeSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing total run time in hours for a job."""

    def __init__(self, coordinator, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_erg_{sanitized}_run_time"

    @property
    def name(self) -> str:
        return f"Erg {self._entity_id} Run Time"

    @property
    def native_unit_of_measurement(self) -> str:
        return "h"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        assignment = _get_assignment_for_entity(data, self._entity_id)
        if assignment is None:
            return None
        return assignment.get("run_time_seconds", 0) / 3600


class ErgJobEnergyCostSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing energy cost for a job."""

    def __init__(self, coordinator, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_erg_{sanitized}_energy_cost"

    @property
    def name(self) -> str:
        return f"Erg {self._entity_id} Energy Cost"

    @property
    def device_class(self):
        return SensorDeviceClass.MONETARY

    @property
    def native_unit_of_measurement(self) -> str:
        return "$"

    @property
    def native_value(self) -> float | None:
        data = self.coordinator.data
        if data is None:
            return None
        assignment = _get_assignment_for_entity(data, self._entity_id)
        if assignment is None:
            return None
        return assignment.get("energy_cost")
