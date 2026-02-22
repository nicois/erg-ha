"""The Erg Energy Scheduler integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ErgApiClient
from .const import DEFAULT_SLOT_DURATION, DOMAIN, PLATFORMS


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Erg Energy Scheduler from a config entry."""
    from .coordinator import ErgScheduleCoordinator
    from .executor import ScheduleExecutor

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    use_ssl = entry.data.get("use_ssl", False)
    token = entry.data.get("api_token")

    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}"

    session = async_get_clientsession(hass)
    api_client = ErgApiClient(session, base_url, token)

    coordinator = ErgScheduleCoordinator(hass, entry, api_client)
    await coordinator.async_config_entry_first_refresh()

    slot_duration = entry.options.get("slot_duration", DEFAULT_SLOT_DURATION)
    executor = ScheduleExecutor(hass, coordinator, slot_duration)
    executor.start()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = {
        "coordinator": coordinator,
        "executor": executor,
    }
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Erg config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        entry_data["executor"].stop()
    return unload_ok
