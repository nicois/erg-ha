"""The Erg Energy Scheduler integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ErgApiClient
from .const import DEFAULT_SLOT_DURATION, DOMAIN, PLATFORMS
from .services import async_register_services, async_unregister_services, create_job_entity, delete_job_entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Erg Energy Scheduler from a config entry."""
    from .coordinator import ErgScheduleCoordinator
    from .executor import ScheduleExecutor

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    use_ssl = entry.data.get("use_ssl", False)
    token = entry.data.get("session_token") or entry.data.get("api_token")

    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}"

    session = async_get_clientsession(hass)
    api_client = ErgApiClient(session, base_url, token)

    coordinator = ErgScheduleCoordinator(hass, entry, api_client)
    await coordinator.async_config_entry_first_refresh()

    slot_duration = entry.options.get("slot_duration", DEFAULT_SLOT_DURATION)
    executor = ScheduleExecutor(hass, coordinator, slot_duration)
    executor.start()

    entry_data = {
        "coordinator": coordinator,
        "executor": executor,
        "job_entities": {},
        "per_job_sensors": {},
        "per_job_binary_sensors": {},
        "per_job_controls": {},
        "entry_options": dict(entry.options),
        "base_url": base_url,
    }

    # Migration: if jobs exist in config options, store for sensor platform to consume
    if "jobs" in entry.options:
        entry_data["pending_job_migration"] = list(entry.options["jobs"])

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = entry_data

    # Build subentry tracking structures BEFORE platform setup so that
    # platform async_setup_entry functions can look up subentry IDs.
    subentry_jobs: set[str] = set()
    subentry_id_map: dict[str, str] = {}
    for sub in entry.subentries.values():
        if sub.subentry_type == "job":
            eid = sub.data.get("entity_id")
            if eid:
                subentry_jobs.add(eid)
                subentry_id_map[eid] = sub.subentry_id
    entry_data["_subentry_jobs"] = subentry_jobs
    entry_data["_subentry_id_map"] = subentry_id_map

    # Register services (idempotent — only registers once per domain)
    if not hass.services.has_service(DOMAIN, "create_job"):
        async_register_services(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    # Create job entities for subentries not yet in the entity registry
    # (handles first load after HA restart if entity registry was cleared)
    for sub in entry.subentries.values():
        if sub.subentry_type == "job":
            eid = sub.data.get("entity_id")
            if eid and eid not in entry_data["job_entities"]:
                create_job_entity(
                    entry.entry_id, entry_data, dict(sub.data),
                    subentry_id=sub.subentry_id,
                )

    # Register update listener for subentry deletion detection
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    # The first coordinator refresh (above) ran before platforms loaded, so
    # job entities were not yet restored from the entity registry.  Now that
    # the sensor platform has populated entry_data["job_entities"], refresh
    # again to produce a schedule that includes all jobs.
    await coordinator.async_refresh()

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload an Erg config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        entry_data["executor"].stop()

        # Unregister services if no entries remain
        if not hass.data[DOMAIN]:
            async_unregister_services(hass)

    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle config entry updates — detect subentry addition and deletion."""
    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    prev = entry_data.get("_subentry_jobs", set())
    current = {
        sub.data["entity_id"]
        for sub in entry.subentries.values()
        if sub.subentry_type == "job" and "entity_id" in sub.data
    }

    # Handle additions (e.g. from the config flow)
    added = current - prev
    subentry_id_map = entry_data.setdefault("_subentry_id_map", {})
    for entity_id in added:
        for sub in entry.subentries.values():
            if sub.subentry_type == "job" and sub.data.get("entity_id") == entity_id:
                subentry_id_map[entity_id] = sub.subentry_id
                if entity_id not in entry_data["job_entities"]:
                    create_job_entity(
                        entry.entry_id, entry_data, dict(sub.data),
                        subentry_id=sub.subentry_id,
                    )
                break

    # Handle removals
    removed = prev - current
    for entity_id in removed:
        await delete_job_entity(entry_data, entity_id)
        subentry_id_map.pop(entity_id, None)

    entry_data["_subentry_jobs"] = current

    if added or removed:
        coordinator = entry_data.get("coordinator")
        if coordinator:
            await coordinator.async_request_refresh()
