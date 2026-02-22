"""Button platform for Erg — manual solve trigger."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN


class ErgSolveNowButton(ButtonEntity):
    """Button that triggers an immediate schedule re-solve."""

    _attr_name = "Erg Solve Now"
    _attr_icon = "mdi:refresh"

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        self._coordinator = coordinator
        self._attr_unique_id = f"{entry.entry_id}_erg_solve_now"

    async def async_press(self) -> None:
        await self._coordinator.async_request_refresh()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg button from a config entry."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([ErgSolveNowButton(entry_data["coordinator"], entry)])
