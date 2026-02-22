"""Text platform for Erg job control entities."""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.text import TextEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .const import DOMAIN, make_job_device_info, validate_duration, validate_time_str
from .job_entities import ErgJobEntity

_LOGGER = logging.getLogger(__name__)


def _sanitize_entity(entity_id: str) -> str:
    return entity_id.replace(".", "_")


class ErgJobText(TextEntity):
    """Text entity for an Erg job string attribute."""

    _attr_entity_category = EntityCategory.CONFIG

    def __init__(
        self,
        job_entity: ErgJobEntity,
        coordinator: Any,
        entry_id: str,
        entity_id: str,
        attr: str,
        suffix: str,
        name_suffix: str,
        icon: str,
        validator: Any | None = None,
        pattern: str | None = None,
    ) -> None:
        self._job_entity = job_entity
        self._coordinator = coordinator
        self._entity_id = entity_id
        self._attr_key = attr
        self._validator = validator
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry_id}_erg_{sanitized}_{suffix}"
        self._attr_name = f"Erg {entity_id} {name_suffix}"
        self._attr_icon = icon
        if pattern:
            self._attr_pattern = pattern

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

    @property
    def native_value(self) -> str | None:
        val = self._job_entity.extra_state_attributes.get(self._attr_key)
        if val is None:
            return None
        return str(val)

    async def async_set_value(self, value: str) -> None:
        if self._validator:
            try:
                self._validator(value)
            except vol.Invalid as err:
                _LOGGER.warning(
                    "Invalid value '%s' for %s: %s", value, self._attr_key, err
                )
                return
        self._job_entity.update_attributes({self._attr_key: value})
        await self._coordinator.async_request_refresh()


def create_job_texts(
    job_entity: ErgJobEntity,
    coordinator: Any,
    entry_id: str,
    entity_id: str,
) -> list[ErgJobText]:
    """Create text entities based on job type."""
    job_type = job_entity.extra_state_attributes.get("job_type", "recurring")
    texts: list[ErgJobText] = []

    # Duration entities are common to both types
    duration_entities = [
        ("maximum_duration", "max_duration", "Max Duration", "mdi:timer-outline"),
        ("minimum_duration", "min_duration", "Min Duration", "mdi:timer-sand"),
        ("minimum_burst", "min_burst", "Min Burst", "mdi:timer-sand-empty"),
    ]
    for attr, suffix, name_suffix, icon in duration_entities:
        texts.append(
            ErgJobText(
                job_entity, coordinator, entry_id, entity_id,
                attr=attr, suffix=suffix, name_suffix=name_suffix, icon=icon,
                validator=validate_duration, pattern=r"(\d+h)?(\d+m)?(\d+s)?",
            )
        )

    if job_type == "recurring":
        texts.append(
            ErgJobText(
                job_entity, coordinator, entry_id, entity_id,
                attr="time_window_start", suffix="time_window_start",
                name_suffix="Time Window Start", icon="mdi:clock-start",
                validator=validate_time_str, pattern=r"[0-2]\d:[0-5]\d",
            )
        )
        texts.append(
            ErgJobText(
                job_entity, coordinator, entry_id, entity_id,
                attr="time_window_end", suffix="time_window_end",
                name_suffix="Time Window End", icon="mdi:clock-end",
                validator=validate_time_str, pattern=r"[0-2]\d:[0-5]\d",
            )
        )
    else:
        texts.append(
            ErgJobText(
                job_entity, coordinator, entry_id, entity_id,
                attr="start", suffix="start", name_suffix="Start",
                icon="mdi:calendar-start",
            )
        )
        texts.append(
            ErgJobText(
                job_entity, coordinator, entry_id, entity_id,
                attr="finish", suffix="finish", name_suffix="Finish",
                icon="mdi:calendar-end",
            )
        )

    return texts


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg job text entities from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    entry_data["add_job_texts"] = async_add_entities

    subentry_id_map = entry_data.get("_subentry_id_map", {})
    no_subentry: list[ErgJobText] = []
    by_subentry: dict[str, list[ErgJobText]] = {}
    for eid, job_entity in entry_data["job_entities"].items():
        if eid.startswith("__"):
            continue
        sid = subentry_id_map.get(eid)
        texts = create_job_texts(job_entity, coordinator, entry.entry_id, eid)
        entry_data.setdefault("per_job_controls", {}).setdefault(eid, []).extend(texts)
        if sid is None:
            no_subentry.extend(texts)
        else:
            by_subentry.setdefault(sid, []).extend(texts)

    async_add_entities(no_subentry)
    for sid, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=sid)
