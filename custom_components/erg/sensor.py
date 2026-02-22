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
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, make_job_device_info
from .job_entities import ErgJobEntity


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
        suggested_unit_of_measurement: str | None = None,
        value_fn: Any = None,
        entity_registry_enabled_default: bool = True,
        entity_registry_visible_default: bool = True,
        entity_category: Any = None,
    ) -> None:
        self.key = key
        self.name = name
        self.device_class = device_class
        self.state_class = state_class
        self.native_unit_of_measurement = native_unit_of_measurement
        self.suggested_unit_of_measurement = suggested_unit_of_measurement
        self.value_fn = value_fn
        self.entity_registry_enabled_default = entity_registry_enabled_default
        self.entity_registry_visible_default = entity_registry_visible_default
        self.entity_category = entity_category


GLOBAL_SENSORS: tuple[ErgSensorEntityDescription, ...] = (
    ErgSensorEntityDescription(
        key="net_value",
        name="Erg Net Value",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("net_value"),
    ),
    ErgSensorEntityDescription(
        key="total_cost",
        name="Erg Total Cost",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("total_cost"),
    ),
    ErgSensorEntityDescription(
        key="total_benefit",
        name="Erg Total Benefit",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("total_benefit"),
    ),
    ErgSensorEntityDescription(
        key="export_revenue",
        name="Erg Export Revenue",
        device_class=SensorDeviceClass.MONETARY,
        state_class=SensorStateClass.TOTAL,
        native_unit_of_measurement="$",
        value_fn=lambda data: data.get("export_revenue"),
    ),
    ErgSensorEntityDescription(
        key="battery_soc_forecast",
        name="Erg Battery SoC Forecast",
        state_class=SensorStateClass.MEASUREMENT,
        native_unit_of_measurement="kWh",
        value_fn=lambda data: (
            data["battery_profile"][-1].get("soc_kwh")
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
    ErgSensorEntityDescription(
        key="schedule_view_url",
        name="Erg Schedule View URL",
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
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    # Store callbacks for dynamic entity creation by services
    entry_data["add_job_sensors"] = async_add_entities
    entry_data["add_per_job_sensors"] = async_add_entities

    # Global sensors (not associated with any subentry)
    global_entities: list[SensorEntity] = []
    for description in GLOBAL_SENSORS:
        global_entities.append(ErgGlobalSensor(coordinator, entry, description))

    # Subentry ID map (built in __init__.py before platform setup)
    subentry_id_map = entry_data.get("_subentry_id_map", {})

    # Migration: create job entities from pending migration data
    pending_jobs = entry_data.pop("pending_job_migration", None)
    if pending_jobs:
        for job in pending_jobs:
            entity_id = job.get("entity_id", "")
            if entity_id.startswith("__"):
                continue
            job_entity = ErgJobEntity.from_job_dict(entry.entry_id, job)
            entry_data["job_entities"][entity_id] = job_entity

        # Remove jobs from config options after migration
        new_opts = dict(entry.options)
        new_opts.pop("jobs", None)
        hass.config_entries.async_update_entry(entry, options=new_opts)

    # Restore job entities from entity registry (survives reload)
    registry = er.async_get(hass)
    job_prefix = f"{entry.entry_id}_job_"
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if not reg_entry.unique_id.startswith(job_prefix):
            continue
        sanitized = reg_entry.unique_id[len(job_prefix):]
        entity_id = sanitized.replace("_", ".", 1)
        if entity_id in entry_data["job_entities"]:
            continue  # already created by migration
        job_entity = ErgJobEntity(entry.entry_id, {"entity_id": entity_id})
        entry_data["job_entities"][entity_id] = job_entity

    # Group job entities + per-job sensors by subentry
    no_subentry: list[SensorEntity] = []
    by_subentry: dict[str, list[SensorEntity]] = {}
    for entity_id in list(entry_data["job_entities"]):
        if entity_id.startswith("__"):
            continue
        sid = subentry_id_map.get(entity_id)
        job_entity = entry_data["job_entities"][entity_id]
        sensors = [
            ErgJobNextStartSensor(coordinator, entry, entity_id),
            ErgJobRunTimeSensor(coordinator, entry, entity_id),
            ErgJobEnergyCostSensor(coordinator, entry, entity_id),
        ]
        entry_data.setdefault("per_job_sensors", {})[entity_id] = sensors
        group = [job_entity] + sensors
        if sid is None:
            no_subentry.extend(group)
        else:
            by_subentry.setdefault(sid, []).extend(group)

    # Add global + non-subentry entities
    async_add_entities(global_entities + no_subentry)
    # Add subentry-associated entities with their subentry ID
    for sid, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=sid)


class ErgGlobalSensor(CoordinatorEntity, SensorEntity):
    """A global Erg schedule sensor."""

    _description: ErgSensorEntityDescription

    def __init__(self, coordinator, entry: ConfigEntry, description: ErgSensorEntityDescription) -> None:
        super().__init__(coordinator)
        self._description = description
        self._attr_unique_id = f"{entry.entry_id}_erg_{description.key}"
        self._entry = entry

    @property
    def name(self) -> str:
        return self._description.name

    @property
    def device_class(self):
        return getattr(self._description, "device_class", None)

    @property
    def state_class(self):
        return getattr(self._description, "state_class", None)

    @property
    def native_unit_of_measurement(self) -> str | None:
        return getattr(self._description, "native_unit_of_measurement", None)

    @property
    def native_value(self):
        data = self.coordinator.data
        if data is None:
            return None

        key = self._description.key

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

        if key == "schedule_view_url":
            entry_data = self.coordinator.hass.data.get(DOMAIN, {}).get(
                self._entry.entry_id, {}
            )
            base_url = entry_data.get("base_url")
            if base_url:
                return f"{base_url}/api/v1/schedule/view"
            return None

        if self._description.value_fn is not None:
            return self._description.value_fn(data)

        return None

    @property
    def extra_state_attributes(self) -> dict[str, Any] | None:
        if self._description.key != "battery_soc_forecast":
            return None
        data = self.coordinator.data
        if data is None:
            return None
        profile = data.get("battery_profile")
        if not profile:
            return None
        forecast = []
        for entry in profile:
            ts = entry.get("time")
            soc = entry.get("soc_kwh")
            if ts is None or soc is None:
                continue
            epoch_ms = int(datetime.fromisoformat(ts).timestamp() * 1000)
            forecast.append([epoch_ms, soc])
        return {"forecast": forecast}


def _get_assignment_for_entity(data: dict[str, Any], entity_id: str) -> dict[str, Any] | None:
    """Find and aggregate all assignment dicts for a given entity_id.

    Recurring jobs that span multiple days produce one assignment per day.
    This merges them into a single dict so sensors report totals.
    """
    merged = None
    for assignment in data.get("assignments", []):
        if assignment.get("entity") != entity_id:
            continue
        if merged is None:
            merged = dict(assignment)
            merged["slots"] = list(merged.get("slots", []))
        else:
            merged["slots"].extend(assignment.get("slots", []))
            merged["run_time_seconds"] = (
                merged.get("run_time_seconds", 0)
                + assignment.get("run_time_seconds", 0)
            )
            merged["energy_cost"] = (
                merged.get("energy_cost", 0)
                + assignment.get("energy_cost", 0)
            )
    return merged


class ErgJobNextStartSensor(CoordinatorEntity, SensorEntity):
    """Sensor showing the next scheduled start time for a job."""

    def __init__(self, coordinator, entry: ConfigEntry, entity_id: str) -> None:
        super().__init__(coordinator)
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry.entry_id}_erg_{sanitized}_next_start"

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

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
    def device_info(self):
        return make_job_device_info(self._entity_id)

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
    def device_info(self):
        return make_job_device_info(self._entity_id)

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
