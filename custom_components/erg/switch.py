"""Switch platform for Erg job control entities."""

from __future__ import annotations

from typing import Any

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant

from .const import DOMAIN, make_job_device_info
from .job_entities import ErgJobEntity


def _sanitize_entity(entity_id: str) -> str:
    return entity_id.replace(".", "_")


class ErgJobSwitch(SwitchEntity):
    """Base switch for an Erg job boolean attribute."""

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
    ) -> None:
        self._job_entity = job_entity
        self._coordinator = coordinator
        self._entity_id = entity_id
        self._attr_key = attr
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry_id}_erg_{sanitized}_{suffix}"
        self._attr_name = f"Erg {entity_id} {name_suffix}"
        self._attr_icon = icon

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

    @property
    def is_on(self) -> bool | None:
        return self._job_entity.extra_state_attributes.get(self._attr_key)

    async def async_turn_on(self, **kwargs: Any) -> None:
        self._job_entity.update_attributes({self._attr_key: True})
        await self._coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        self._job_entity.update_attributes({self._attr_key: False})
        await self._coordinator.async_request_refresh()


def create_job_switches(
    job_entity: ErgJobEntity,
    coordinator: Any,
    entry_id: str,
    entity_id: str,
) -> list[ErgJobSwitch]:
    """Create enabled and force switches for a job."""
    return [
        ErgJobSwitch(
            job_entity, coordinator, entry_id, entity_id,
            attr="enabled", suffix="enabled", name_suffix="Enabled",
            icon="mdi:toggle-switch",
        ),
        ErgJobSwitch(
            job_entity, coordinator, entry_id, entity_id,
            attr="force", suffix="force", name_suffix="Force",
            icon="mdi:arrow-decision",
        ),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg job switches from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    entry_data["add_job_switches"] = async_add_entities

    subentry_id_map = entry_data.get("_subentry_id_map", {})
    no_subentry: list[ErgJobSwitch] = []
    by_subentry: dict[str, list[ErgJobSwitch]] = {}
    for eid, job_entity in entry_data["job_entities"].items():
        if eid.startswith("__"):
            continue
        sid = subentry_id_map.get(eid)
        switches = create_job_switches(job_entity, coordinator, entry.entry_id, eid)
        entry_data.setdefault("per_job_controls", {}).setdefault(eid, []).extend(switches)
        if sid is None:
            no_subentry.extend(switches)
        else:
            by_subentry.setdefault(sid, []).extend(switches)

    async_add_entities(no_subentry)
    for sid, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=sid)
