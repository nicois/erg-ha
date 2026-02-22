"""Config flow for the Erg Energy Scheduler integration."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp
import voluptuous as vol

from homeassistant.config_entries import ConfigEntry, ConfigFlow, OptionsFlow
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import ErgApiClient, ErgAuthError, ErgConnectionError
from .const import (
    DEFAULT_HORIZON_HOURS,
    DEFAULT_PORT,
    DEFAULT_SLOT_DURATION,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

CONF_USE_SSL = "use_ssl"
CONF_API_TOKEN = "api_token"


class ErgConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Erg Energy Scheduler."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step — collect connection details."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input[CONF_HOST]
            port = user_input[CONF_PORT]
            use_ssl = user_input.get(CONF_USE_SSL, False)
            token = user_input.get(CONF_API_TOKEN) or None

            scheme = "https" if use_ssl else "http"
            base_url = f"{scheme}://{host}:{port}"

            # Check we haven't already configured this server
            await self.async_set_unique_id(base_url)
            self._abort_if_unique_id_configured()

            # Validate connection
            session = async_get_clientsession(self.hass)
            client = ErgApiClient(session, base_url, token)
            try:
                await client.health()
            except ErgAuthError:
                errors["base"] = "invalid_auth"
            except ErgConnectionError:
                errors["base"] = "cannot_connect"
            except Exception:
                _LOGGER.exception("Unexpected error during config validation")
                errors["base"] = "cannot_connect"
            else:
                return self.async_create_entry(
                    title=f"Erg ({host}:{port})",
                    data={
                        CONF_HOST: host,
                        CONF_PORT: port,
                        CONF_USE_SSL: use_ssl,
                        CONF_API_TOKEN: token,
                    },
                )

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default="localhost"): str,
                    vol.Required(CONF_PORT, default=DEFAULT_PORT): int,
                    vol.Optional(CONF_USE_SSL, default=False): bool,
                    vol.Optional(CONF_API_TOKEN, default=""): str,
                }
            ),
            errors=errors,
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ErgOptionsFlow:
        """Return the options flow handler."""
        return ErgOptionsFlow(config_entry)


class ErgOptionsFlow(OptionsFlow):
    """Handle options for the Erg integration."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage system parameters and data sources."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self._config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "grid_import_limit",
                        default=opts.get("grid_import_limit", 10.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "grid_export_limit",
                        default=opts.get("grid_export_limit", 5.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "inverter_power",
                        default=opts.get("inverter_power", 5.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_capacity",
                        default=opts.get("battery_capacity", 0.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_storage_value",
                        default=opts.get("battery_storage_value", 0.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_soc_entity",
                        default=opts.get("battery_soc_entity", ""),
                    ): str,
                    vol.Optional(
                        "solar_forecast_provider",
                        default=opts.get("solar_forecast_provider", "none"),
                    ): vol.In({"none": "None", "auto": "Auto-discover"}),
                    vol.Optional(
                        "update_interval",
                        default=opts.get(
                            "update_interval", DEFAULT_UPDATE_INTERVAL_MINUTES
                        ),
                    ): vol.Coerce(int),
                    vol.Optional(
                        "horizon_hours",
                        default=opts.get("horizon_hours", DEFAULT_HORIZON_HOURS),
                    ): vol.Coerce(int),
                    vol.Optional(
                        "slot_duration",
                        default=opts.get("slot_duration", DEFAULT_SLOT_DURATION),
                    ): str,
                }
            ),
        )
