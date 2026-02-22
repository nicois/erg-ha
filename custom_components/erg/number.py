"""Number platform for Erg job control entities."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.restore_state import RestoreEntity

from .const import DOMAIN, make_job_device_info
from .job_entities import ErgJobEntity


def _sanitize_entity(entity_id: str) -> str:
    return entity_id.replace(".", "_")


class ErgJobNumber(NumberEntity):
    """Number entity for an Erg job numeric attribute."""

    _attr_entity_category = EntityCategory.CONFIG
    _attr_mode = NumberMode.BOX

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
        native_min: float,
        native_max: float,
        native_step: float,
        unit: str,
    ) -> None:
        self._job_entity = job_entity
        self._coordinator = coordinator
        self._entity_id = entity_id
        self._attr_key = attr
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry_id}_erg_{sanitized}_{suffix}"
        self._attr_name = f"Erg {entity_id} {name_suffix}"
        self._attr_icon = icon
        self._attr_native_min_value = native_min
        self._attr_native_max_value = native_max
        self._attr_native_step = native_step
        self._attr_native_unit_of_measurement = unit

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

    @property
    def native_value(self) -> float | None:
        val = self._job_entity.extra_state_attributes.get(self._attr_key)
        if val is None:
            return None
        return float(val)

    async def async_set_native_value(self, value: float) -> None:
        self._job_entity.update_attributes({self._attr_key: value})
        await self._coordinator.async_request_refresh()


class ErgJobElapsedNumber(RestoreEntity, NumberEntity):
    """Number entity exposing elapsed scheduled time today for a job.

    Reads and writes the coordinator's elapsed tracking directly,
    allowing manual adjustment via the UI or automations.
    The value is displayed in minutes.

    Extends RestoreEntity so the elapsed value survives HA restarts.
    On startup, the restored value re-seeds the coordinator's tracking,
    preventing the scheduler from re-allocating time already used today.
    """

    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: Any,
        entry_id: str,
        entity_id: str,
    ) -> None:
        self._coordinator = coordinator
        self._entity_id = entity_id
        sanitized = _sanitize_entity(entity_id)
        self._attr_unique_id = f"{entry_id}_erg_{sanitized}_elapsed_today"
        self._attr_name = f"Erg {entity_id} Elapsed Today"
        self._attr_icon = "mdi:timer-outline"
        self._attr_native_min_value = 0
        self._attr_native_max_value = 1440
        self._attr_native_step = 1
        self._attr_native_unit_of_measurement = "min"

    @property
    def device_info(self):
        return make_job_device_info(self._entity_id)

    @property
    def native_value(self) -> float:
        return self._coordinator.get_elapsed(self._entity_id) / 60.0

    async def async_set_native_value(self, value: float) -> None:
        self._coordinator.set_elapsed(self._entity_id, value * 60.0)
        await self._coordinator.async_request_refresh()

    async def async_added_to_hass(self) -> None:
        """Restore elapsed value from before restart and re-seed the coordinator."""
        last_state = await self.async_get_last_state()
        if last_state is None or last_state.state in ("unknown", "unavailable"):
            return

        # Only restore if the saved state is from today; stale values from
        # a previous day must not carry over.
        now = datetime.now().astimezone()
        if last_state.last_updated.date() != now.date():
            return

        try:
            minutes = float(last_state.state)
        except (ValueError, TypeError):
            return

        if minutes > 0:
            self._coordinator.set_elapsed(self._entity_id, minutes * 60.0)


def create_job_numbers(
    job_entity: ErgJobEntity,
    coordinator: Any,
    entry_id: str,
    entity_id: str,
) -> list[NumberEntity]:
    """Create AC power, DC power, benefit, and elapsed number entities for a job."""
    return [
        ErgJobNumber(
            job_entity, coordinator, entry_id, entity_id,
            attr="ac_power", suffix="ac_power", name_suffix="AC Power",
            icon="mdi:flash", native_min=-100, native_max=100,
            native_step=0.1, unit="kW",
        ),
        ErgJobNumber(
            job_entity, coordinator, entry_id, entity_id,
            attr="dc_power", suffix="dc_power", name_suffix="DC Power",
            icon="mdi:flash-outline", native_min=-100, native_max=100,
            native_step=0.1, unit="kW",
        ),
        ErgJobNumber(
            job_entity, coordinator, entry_id, entity_id,
            attr="benefit", suffix="benefit", name_suffix="Benefit",
            icon="mdi:currency-usd", native_min=0, native_max=10000,
            native_step=0.01, unit="$",
        ),
        ErgJobElapsedNumber(coordinator, entry_id, entity_id),
    ]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg job number entities from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    coordinator = entry_data["coordinator"]

    entry_data["add_job_numbers"] = async_add_entities

    subentry_id_map = entry_data.get("_subentry_id_map", {})
    no_subentry: list[NumberEntity] = []
    by_subentry: dict[str, list[NumberEntity]] = {}
    for eid, job_entity in entry_data["job_entities"].items():
        if eid.startswith("__"):
            continue
        sid = subentry_id_map.get(eid)
        numbers = create_job_numbers(job_entity, coordinator, entry.entry_id, eid)
        entry_data.setdefault("per_job_controls", {}).setdefault(eid, []).extend(numbers)
        if sid is None:
            no_subentry.extend(numbers)
        else:
            by_subentry.setdefault(sid, []).extend(numbers)

    async_add_entities(no_subentry)
    for sid, entities in by_subentry.items():
        async_add_entities(entities, config_subentry_id=sid)
