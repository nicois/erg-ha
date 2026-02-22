"""Device actions for Erg job devices.

Exposes actions like set_force, set_benefit, etc. so that HA automations
can modify job properties via the device selector UI.
"""

from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.const import CONF_DEVICE_ID, CONF_DOMAIN, CONF_TYPE
from homeassistant.core import Context, HomeAssistant
from homeassistant.helpers import device_registry as dr

from .const import DOMAIN, validate_duration, validate_time_str

_LOGGER = logging.getLogger(__name__)

ACTION_TYPES = [
    "set_force",
    "set_enabled",
    "set_benefit",
    "set_ac_power",
    "set_dc_power",
    "set_maximum_duration",
    "set_minimum_duration",
    "set_minimum_burst",
    "set_time_window",
]


def _get_job_entity_id_from_device(
    hass: HomeAssistant, device_id: str
) -> str | None:
    """Resolve a device_id to the job's entity_id via the device registry."""
    registry = dr.async_get(hass)
    device = registry.async_get(device_id)
    if device is None:
        return None

    for domain, identifier in device.identifiers:
        if domain == DOMAIN:
            return identifier
    return None


async def async_get_actions(
    hass: HomeAssistant, device_id: str
) -> list[dict[str, str]]:
    """Return the list of available actions for an erg job device."""
    entity_id = _get_job_entity_id_from_device(hass, device_id)
    if entity_id is None:
        return []

    return [
        {
            CONF_DOMAIN: DOMAIN,
            CONF_DEVICE_ID: device_id,
            CONF_TYPE: action_type,
        }
        for action_type in ACTION_TYPES
    ]


async def async_get_action_capabilities(
    hass: HomeAssistant, config: dict[str, Any]
) -> dict[str, Any]:
    """Return the extra_fields schema for a given action type."""
    action_type = config[CONF_TYPE]

    if action_type in ("set_force", "set_enabled"):
        return {
            "extra_fields": vol.Schema(
                {vol.Required("value"): bool}
            )
        }

    if action_type in ("set_benefit", "set_ac_power", "set_dc_power"):
        return {
            "extra_fields": vol.Schema(
                {vol.Required("value"): vol.Coerce(float)}
            )
        }

    if action_type in ("set_maximum_duration", "set_minimum_duration", "set_minimum_burst"):
        return {
            "extra_fields": vol.Schema(
                {vol.Required("value"): str}
            )
        }

    if action_type == "set_time_window":
        return {
            "extra_fields": vol.Schema(
                {
                    vol.Required("time_window_start"): str,
                    vol.Required("time_window_end"): str,
                }
            )
        }

    return {}


# Mapping from action type to the attribute key(s) to set.
_ACTION_ATTR_MAP: dict[str, str | None] = {
    "set_force": "force",
    "set_enabled": "enabled",
    "set_benefit": "benefit",
    "set_ac_power": "ac_power",
    "set_dc_power": "dc_power",
    "set_maximum_duration": "maximum_duration",
    "set_minimum_duration": "minimum_duration",
    "set_minimum_burst": "minimum_burst",
    "set_time_window": None,  # handled specially
}


async def async_call_action_from_config(
    hass: HomeAssistant,
    config: dict[str, Any],
    variables: dict[str, Any],
    context: Context | None,
) -> None:
    """Execute a device action — update the job entity attributes."""
    device_id = config[CONF_DEVICE_ID]
    action_type = config[CONF_TYPE]

    entity_id = _get_job_entity_id_from_device(hass, device_id)
    if entity_id is None:
        _LOGGER.warning("Device %s not found or not an erg job device", device_id)
        return

    # Find the job entity across all config entries
    domain_data = hass.data.get(DOMAIN, {})
    job_entity = None
    coordinator = None
    for entry_id, entry_data in domain_data.items():
        if not isinstance(entry_data, dict) or "job_entities" not in entry_data:
            continue
        job_entity = entry_data["job_entities"].get(entity_id)
        if job_entity is not None:
            coordinator = entry_data.get("coordinator")
            break

    if job_entity is None:
        _LOGGER.warning("Job entity %s not found in hass.data", entity_id)
        return

    # Validate string inputs before applying
    if action_type == "set_time_window":
        validate_time_str(config["time_window_start"])
        validate_time_str(config["time_window_end"])
    elif action_type in ("set_maximum_duration", "set_minimum_duration", "set_minimum_burst"):
        validate_duration(config["value"])

    # Build the attribute update dict
    attr_key = _ACTION_ATTR_MAP.get(action_type)
    if action_type == "set_time_window":
        attrs = {
            "time_window_start": config["time_window_start"],
            "time_window_end": config["time_window_end"],
        }
    elif attr_key is not None:
        attrs = {attr_key: config["value"]}
    else:
        _LOGGER.warning("Unknown action type: %s", action_type)
        return

    job_entity.update_attributes(attrs)

    if coordinator is not None:
        await coordinator.async_request_refresh()
