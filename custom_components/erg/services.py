"""Service handlers for Erg job management (create/update/delete)."""

from __future__ import annotations

import logging
from types import MappingProxyType
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigSubentry
from homeassistant.core import HomeAssistant, ServiceCall

from .const import DOMAIN, FREQUENCY_CHOICES, validate_duration, validate_time_str
from .job_entities import ErgJobEntity
from .number import create_job_numbers
from .select import create_job_selects
from .sensor import (
    ErgJobEnergyCostSensor,
    ErgJobNextStartSensor,
    ErgJobRunTimeSensor,
)
from .binary_sensor import ErgScheduledBinarySensor
from .switch import create_job_switches
from .text import create_job_texts

_LOGGER = logging.getLogger(__name__)

SERVICE_CREATE_JOB = "create_job"
SERVICE_UPDATE_JOB = "update_job"
SERVICE_DELETE_JOB = "delete_job"

CREATE_JOB_SCHEMA = vol.Schema(
    {
        vol.Required("entity_id"): str,
        vol.Required("job_type"): vol.In(["recurring", "oneshot"]),
        vol.Optional("ac_power", default=0.0): vol.Coerce(float),
        vol.Optional("dc_power", default=0.0): vol.Coerce(float),
        vol.Optional("force", default=False): bool,
        vol.Optional("benefit", default=0.0): vol.Coerce(float),
        vol.Optional("enabled", default=True): bool,
        # Recurring fields
        vol.Optional("frequency", default="daily"): vol.In(list(FREQUENCY_CHOICES)),
        vol.Optional("time_window_start", default="09:00"): vol.All(str, validate_time_str),
        vol.Optional("time_window_end", default="17:00"): vol.All(str, validate_time_str),
        vol.Optional("maximum_duration", default="1h"): vol.All(str, validate_duration),
        vol.Optional("minimum_duration", default="0s"): vol.All(str, validate_duration),
        vol.Optional("minimum_burst", default="0s"): vol.All(str, validate_duration),
        vol.Optional("day_of_week"): int,
        vol.Optional("days_of_week"): list,
        # One-shot fields
        vol.Optional("start"): str,
        vol.Optional("finish"): str,
    }
)

UPDATE_JOB_SCHEMA = vol.Schema(
    {
        vol.Required("job_entity_id"): str,
        vol.Optional("ac_power"): vol.Coerce(float),
        vol.Optional("dc_power"): vol.Coerce(float),
        vol.Optional("force"): bool,
        vol.Optional("benefit"): vol.Coerce(float),
        vol.Optional("enabled"): bool,
        vol.Optional("frequency"): vol.In(list(FREQUENCY_CHOICES)),
        vol.Optional("time_window_start"): vol.All(str, validate_time_str),
        vol.Optional("time_window_end"): vol.All(str, validate_time_str),
        vol.Optional("maximum_duration"): vol.All(str, validate_duration),
        vol.Optional("minimum_duration"): vol.All(str, validate_duration),
        vol.Optional("minimum_burst"): vol.All(str, validate_duration),
        vol.Optional("day_of_week"): int,
        vol.Optional("days_of_week"): list,
        vol.Optional("start"): str,
        vol.Optional("finish"): str,
    }
)

DELETE_JOB_SCHEMA = vol.Schema(
    {
        vol.Required("job_entity_id"): str,
    }
)


def _find_entry_data(hass: HomeAssistant) -> tuple[str, dict[str, Any]]:
    """Find the first config entry data dict for the erg domain."""
    domain_data = hass.data.get(DOMAIN, {})
    for entry_id, entry_data in domain_data.items():
        if isinstance(entry_data, dict) and "coordinator" in entry_data:
            return entry_id, entry_data
    raise ValueError("No Erg config entry found")


def create_job_entity(
    entry_id: str,
    entry_data: dict[str, Any],
    attrs: dict[str, Any],
    subentry_id: str | None = None,
) -> ErgJobEntity | None:
    """Create a job entity and per-job sensors.

    Returns the new entity, or None if the entity_id already exists.
    This is the shared core used by both the service handler and the options flow.
    """
    job_entities = entry_data["job_entities"]
    entity_id = attrs["entity_id"]

    if entity_id in job_entities:
        _LOGGER.warning("Job entity %s already exists, skipping create", entity_id)
        return None

    job_entity = ErgJobEntity(entry_id, dict(attrs))

    # Register with HA via stored callback
    add_job_sensors = entry_data.get("add_job_sensors")
    if add_job_sensors:
        add_job_sensors([job_entity], config_subentry_id=subentry_id)

    job_entities[entity_id] = job_entity

    # Create associated per-job sensors and control entities
    coordinator = entry_data["coordinator"]
    _create_per_job_entities(
        entry_data, coordinator, entry_id, entity_id, job_entity, subentry_id
    )

    return job_entity


async def delete_job_entity(entry_data: dict[str, Any], entity_id: str) -> bool:
    """Delete a job entity and associated sensors.

    Returns True if the entity was found and removed, False otherwise.
    This is the shared core used by both the service handler and the options flow.
    """
    job_entities = entry_data["job_entities"]
    per_job_sensors = entry_data.get("per_job_sensors", {})
    per_job_binary_sensors = entry_data.get("per_job_binary_sensors", {})
    per_job_controls = entry_data.get("per_job_controls", {})

    entity = job_entities.pop(entity_id, None)
    if entity is None:
        _LOGGER.warning("Job entity %s not found for delete", entity_id)
        return False

    await entity.async_remove()

    for sensor in per_job_sensors.pop(entity_id, []):
        await sensor.async_remove()

    for sensor in per_job_binary_sensors.pop(entity_id, []):
        await sensor.async_remove()

    for control in per_job_controls.pop(entity_id, []):
        await control.async_remove()

    return True


async def async_handle_create_job(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle erg.create_job service call."""
    data = dict(call.data)
    entry_id, entry_data = _find_entry_data(hass)
    coordinator = entry_data["coordinator"]
    entity_id = data["entity_id"]

    # Check for duplicates before creating anything
    if entity_id in entry_data["job_entities"]:
        _LOGGER.warning("Job entity %s already exists, skipping create", entity_id)
        return

    # Create the config sub-entry first so we have its ID for entity association
    entry = hass.config_entries.async_get_entry(entry_id)
    subentry = ConfigSubentry(
        data=MappingProxyType(data),
        subentry_type="job",
        title=entity_id,
        unique_id=entity_id,
    )
    hass.config_entries.async_add_subentry(entry, subentry)

    result = create_job_entity(
        entry_id, entry_data, data, subentry_id=subentry.subentry_id
    )
    if result is not None:
        # Track in _subentry_jobs set and subentry_id map
        subentry_jobs = entry_data.setdefault("_subentry_jobs", set())
        subentry_jobs.add(entity_id)
        subentry_id_map = entry_data.setdefault("_subentry_id_map", {})
        subentry_id_map[entity_id] = subentry.subentry_id

        await coordinator.async_request_refresh()


async def async_handle_update_job(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle erg.update_job service call."""
    data = dict(call.data)
    _, entry_data = _find_entry_data(hass)
    coordinator = entry_data["coordinator"]
    job_entities = entry_data["job_entities"]

    job_entity_id = data.pop("job_entity_id")
    entity = job_entities.get(job_entity_id)
    if entity is None:
        _LOGGER.warning("Job entity %s not found for update", job_entity_id)
        return

    entity.update_attributes(data)
    await coordinator.async_request_refresh()


async def async_handle_delete_job(hass: HomeAssistant, call: ServiceCall) -> None:
    """Handle erg.delete_job service call."""
    entry_id, entry_data = _find_entry_data(hass)
    coordinator = entry_data["coordinator"]

    job_entity_id = call.data["job_entity_id"]
    removed = await delete_job_entity(entry_data, job_entity_id)
    if removed:
        # Remove the matching config sub-entry
        entry = hass.config_entries.async_get_entry(entry_id)
        if entry is not None:
            for sub in list(entry.subentries.values()):
                if sub.data.get("entity_id") == job_entity_id:
                    hass.config_entries.async_remove_subentry(
                        entry, sub.subentry_id
                    )
                    break

        # Update tracking structures
        subentry_jobs = entry_data.get("_subentry_jobs")
        if subentry_jobs is not None:
            subentry_jobs.discard(job_entity_id)
        subentry_id_map = entry_data.get("_subentry_id_map")
        if subentry_id_map is not None:
            subentry_id_map.pop(job_entity_id, None)

        await coordinator.async_request_refresh()


def _create_per_job_entities(
    entry_data: dict[str, Any],
    coordinator: Any,
    entry_id: str,
    entity_id: str,
    job_entity: ErgJobEntity,
    subentry_id: str | None = None,
) -> None:
    """Create per-job sensor, binary sensor, and control entities for a job."""
    # Create per-job sensors (next_start, run_time, energy_cost)
    add_sensors_cb = entry_data.get("add_per_job_sensors")
    if add_sensors_cb:
        # We need to pass a mock entry with entry_id for constructing sensors
        entry_proxy = type("EntryProxy", (), {"entry_id": entry_id})()
        sensors = [
            ErgJobNextStartSensor(coordinator, entry_proxy, entity_id),
            ErgJobRunTimeSensor(coordinator, entry_proxy, entity_id),
            ErgJobEnergyCostSensor(coordinator, entry_proxy, entity_id),
        ]
        add_sensors_cb(sensors, config_subentry_id=subentry_id)
        entry_data.setdefault("per_job_sensors", {})[entity_id] = sensors

    # Create per-job binary sensor (scheduled)
    add_binary_cb = entry_data.get("add_job_binary_sensors")
    if add_binary_cb:
        entry_proxy = type("EntryProxy", (), {
            "entry_id": entry_id,
            "options": entry_data.get("entry_options", {}),
        })()
        binary_sensors = [
            ErgScheduledBinarySensor(coordinator, entry_proxy, entity_id),
        ]
        add_binary_cb(binary_sensors, config_subentry_id=subentry_id)
        entry_data.setdefault("per_job_binary_sensors", {})[entity_id] = binary_sensors

    # Create control entities (switches, numbers, selects, texts)
    controls: list[Any] = []

    add_switches = entry_data.get("add_job_switches")
    if add_switches:
        switches = create_job_switches(job_entity, coordinator, entry_id, entity_id)
        add_switches(switches, config_subentry_id=subentry_id)
        controls.extend(switches)

    add_numbers = entry_data.get("add_job_numbers")
    if add_numbers:
        numbers = create_job_numbers(job_entity, coordinator, entry_id, entity_id)
        add_numbers(numbers, config_subentry_id=subentry_id)
        controls.extend(numbers)

    add_selects = entry_data.get("add_job_selects")
    if add_selects:
        selects = create_job_selects(job_entity, coordinator, entry_id, entity_id)
        add_selects(selects, config_subentry_id=subentry_id)
        controls.extend(selects)

    add_texts = entry_data.get("add_job_texts")
    if add_texts:
        texts = create_job_texts(job_entity, coordinator, entry_id, entity_id)
        add_texts(texts, config_subentry_id=subentry_id)
        controls.extend(texts)

    entry_data.setdefault("per_job_controls", {})[entity_id] = controls


def async_register_services(hass: HomeAssistant) -> None:
    """Register Erg services with Home Assistant."""
    hass.services.async_register(
        DOMAIN, SERVICE_CREATE_JOB, lambda call: async_handle_create_job(hass, call),
        schema=CREATE_JOB_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_UPDATE_JOB, lambda call: async_handle_update_job(hass, call),
        schema=UPDATE_JOB_SCHEMA,
    )
    hass.services.async_register(
        DOMAIN, SERVICE_DELETE_JOB, lambda call: async_handle_delete_job(hass, call),
        schema=DELETE_JOB_SCHEMA,
    )


def async_unregister_services(hass: HomeAssistant) -> None:
    """Unregister Erg services."""
    hass.services.async_remove(DOMAIN, SERVICE_CREATE_JOB)
    hass.services.async_remove(DOMAIN, SERVICE_UPDATE_JOB)
    hass.services.async_remove(DOMAIN, SERVICE_DELETE_JOB)
