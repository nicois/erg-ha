"""Select platform for Erg job control entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .const import DOMAIN, FREQUENCY_CHOICES, make_job_device_info
from .job_entities import ErgJobEntity


def _sanitize_entity(entity_id: str) -> str:
    return entity_id.replace(".", "_")


class ErgJobFrequencySelect(SelectEntity):
    """Select entity for an Erg job's scheduling frequency."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:calendar-clock"
    _attr_options = list(FREQUENCY_CHOICES.keys())

    def __init__(
        self,
        job_entity: ErgJobEntity,
        coordinator: Any,
        entry_id: str,
        entity_id: str,
    ) -> None:
        self._job_entity = job_entity
        self._coordinator = coordinator
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry_id}_erg_{sanitized}_frequency"
        self._attr_name = f"Erg {entity_id} Frequency"

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

    @property
    def current_option(self) -> str | None:
        return self._job_entity.extra_state_attributes.get("frequency")

    async def async_select_option(self, option: str) -> None:
        self._job_entity.update_attributes({"frequency": option})
        await self._coordinator.async_request_refresh()


def create_job_selects(
    job_entity: ErgJobEntity,
    coordinator: Any,
    entry_id: str,
    entity_id: str,
) -> list[ErgJobFrequencySelect]:
    """Create frequency select for recurring jobs only."""
    if job_entity.extra_state_attributes.get("job_type") != "recurring":
        return []
    return [
        ErgJobFrequencySelect(job_entity, coordinator, entry_id, entity_id),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg job select entities from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    entry_data["add_job_selects"] = async_add_entities

    subentry_id_map = entry_data.get("_subentry_id_map", {})
    no_subentry: list[ErgJobFrequencySelect] = []
    by_subentry: dict[str, list[ErgJobFrequencySelect]] = {}
    for eid, job_entity in entry_data["job_entities"].items():
        if eid.startswith("__"):
            continue
        sid = subentry_id_map.get(eid)
        selects = create_job_selects(job_entity, coordinator, entry.entry_id, eid)
        entry_data.setdefault("per_job_controls", {}).setdefault(eid, []).extend(selects)
        if sid is None:
            no_subentry.extend(selects)
        else:
            by_subentry.setdefault(sid, []).extend(selects)

    async_add_entities(no_subentry)
    for sid, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=sid)
