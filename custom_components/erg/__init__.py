"""The Erg Energy Scheduler integration."""

from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ErgApiClient
from .const import CONF_API_KEY, CONF_API_KEY_ID, DEFAULT_SLOT_DURATION, DOMAIN, PLATFORMS
from .services import async_register_services, async_unregister_services, create_job_entity, delete_job_entity


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up Erg Energy Scheduler from a config entry."""
    from .coordinator import ErgScheduleCoordinator
    from .executor import ScheduleExecutor

    host = entry.data[CONF_HOST]
    port = entry.data[CONF_PORT]
    use_ssl = entry.data.get("use_ssl", False)
    token = entry.data.get("api_key") or entry.data.get("session_token") or entry.data.get("api_token")

    scheme = "https" if use_ssl else "http"
    base_url = f"{scheme}://{host}:{port}"

    session = async_get_clientsession(hass)
    api_client = ErgApiClient(session, base_url, token)

    # Migrate session token to API key if the server supports it
    if entry.data.get("session_token") and not entry.data.get("api_key"):
        try:
            location = hass.config.location_name or "Home Assistant"
            key_data = await api_client.create_api_key(
                name=f"Home Assistant ({location})", scope="schedule"
            )
            if key_data and key_data.get("token"):
                new_data = {**entry.data}
                new_data[CONF_API_KEY] = key_data["token"]
                new_data[CONF_API_KEY_ID] = key_data.get("id")
                hass.config_entries.async_update_entry(entry, data=new_data)
                # Recreate client with the new API key
                api_client = ErgApiClient(session, base_url, key_data["token"])
        except Exception:  # noqa: BLE001
            pass  # Server may not support keys yet — keep session token

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
    """Handle config entry updates — options changes and subentry addition/deletion."""
    from datetime import timedelta
    from .const import DEFAULT_SLOT_DURATION, DEFAULT_UPDATE_INTERVAL_MINUTES
    from .executor import ScheduleExecutor

    entry_data = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if entry_data is None:
        return

    # Detect option changes (update_interval, slot_duration, etc.)
    prev_opts = entry_data.get("entry_options", {})
    new_opts = dict(entry.options)
    needs_refresh = False

    new_interval = new_opts.get("update_interval", DEFAULT_UPDATE_INTERVAL_MINUTES)
    old_interval = prev_opts.get("update_interval", DEFAULT_UPDATE_INTERVAL_MINUTES)
    if new_interval != old_interval:
        coordinator = entry_data.get("coordinator")
        if coordinator:
            coordinator.update_interval = timedelta(minutes=new_interval)
        needs_refresh = True

    new_slot = new_opts.get("slot_duration", DEFAULT_SLOT_DURATION)
    old_slot = prev_opts.get("slot_duration", DEFAULT_SLOT_DURATION)
    if new_slot != old_slot:
        executor = entry_data.get("executor")
        if executor:
            executor.stop()
        coordinator = entry_data.get("coordinator")
        new_executor = ScheduleExecutor(hass, coordinator, new_slot)
        new_executor.start()
        entry_data["executor"] = new_executor
        needs_refresh = True

    # Any other option change should trigger a refresh so the new
    # settings (horizon, battery, tariffs, etc.) take effect immediately.
    if prev_opts != new_opts:
        needs_refresh = True

    entry_data["entry_options"] = new_opts

    # Detect subentry changes
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

    if added or removed or needs_refresh:
        coordinator = entry_data.get("coordinator")
        if coordinator:
            await coordinator.async_request_refresh()
