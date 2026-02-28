"""Config flow for the Erg Energy Scheduler integration."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import re

import aiohttp
import voluptuous as vol
import yaml

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigEntryState,
    ConfigFlow,
    ConfigSubentryFlow,
    OptionsFlow,
    SubentryFlowResult,
)
from homeassistant.const import CONF_HOST, CONF_PORT
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import TextSelector, TextSelectorConfig

from .api import ErgApiClient, ErgAuthError, ErgConnectionError
from .const import (
    CONF_SESSION_TOKEN,
    DAY_OF_WEEK_CHOICES,
    DEFAULT_EXTEND_TO_END_OF_DAY,
    DEFAULT_HORIZON_HOURS,
    DEFAULT_PORT,
    DEFAULT_SLOT_DURATION,
    DEFAULT_UPDATE_INTERVAL_MINUTES,
    DOMAIN,
    FREQUENCY_CHOICES,
    validate_duration,
    validate_time_str,
)

_LOGGER = logging.getLogger(__name__)

CONF_USE_SSL = "use_ssl"
CONF_API_TOKEN = "api_token"

# Polling interval and max attempts for OIDC auth status
_OIDC_POLL_INTERVAL = 2  # seconds
_OIDC_POLL_MAX_ATTEMPTS = 150  # 5 minutes at 2s intervals


class ErgConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Erg Energy Scheduler."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialize the config flow."""
        super().__init__()
        self._host: str = ""
        self._port: int = DEFAULT_PORT
        self._use_ssl: bool = False
        self._api_token: str | None = None
        self._base_url: str = ""
        self._providers: list[dict[str, str]] = []
        self._oidc_state: str = ""
        self._session_token: str | None = None
        self._oidc_user: dict[str, Any] | None = None

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
                # Store connection details for potential OIDC flow
                self._host = host
                self._port = port
                self._use_ssl = use_ssl
                self._api_token = token
                self._base_url = base_url

                # Check for OIDC providers
                try:
                    providers = await client.get_auth_providers()
                except Exception:
                    providers = []

                if providers:
                    self._providers = providers
                    return await self.async_step_auth_method()

                # No OIDC — create entry directly
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
                    vol.Required(CONF_HOST, default="erg.297108.xyz"): str,
                    vol.Required(CONF_PORT, default=443): int,
                    vol.Optional(CONF_USE_SSL, default=True): bool,
                    vol.Optional(CONF_API_TOKEN, default=""): str,
                }
            ),
            errors=errors,
        )

    # ── OIDC auth method choice ──────────────────────────────────────────

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose between bearer token only or OIDC sign-in."""
        if user_input is not None:
            method = user_input.get("auth_method", "token_only")
            if method == "token_only":
                return self.async_create_entry(
                    title=f"Erg ({self._host}:{self._port})",
                    data={
                        CONF_HOST: self._host,
                        CONF_PORT: self._port,
                        CONF_USE_SSL: self._use_ssl,
                        CONF_API_TOKEN: self._api_token,
                    },
                )
            # method is a provider name — start OIDC flow
            return await self._start_oidc_flow(method)

        choices: dict[str, str] = {"token_only": "Bearer token only"}
        for provider in self._providers:
            name = provider.get("name", "")
            display = provider.get("display_name", name)
            choices[name] = f"Sign in with {display}"

        return self.async_show_form(
            step_id="auth_method",
            data_schema=vol.Schema(
                {
                    vol.Required("auth_method", default="token_only"): vol.In(
                        choices
                    )
                }
            ),
        )

    async def _start_oidc_flow(self, provider: str) -> FlowResult:
        """Start the OIDC login flow and open the browser."""
        session = async_get_clientsession(self.hass)
        client = ErgApiClient(session, self._base_url, self._api_token)

        try:
            flow_data = await client.start_auth_flow(provider)
        except Exception:
            _LOGGER.exception("Failed to start OIDC auth flow")
            return self.async_abort(reason="oidc_flow_failed")

        self._oidc_state = flow_data.get("state", "")
        login_url = flow_data.get("login_url", "")

        # Start background polling — when auth completes, it will
        # call async_configure to advance the external step.
        self.hass.async_create_task(self._poll_oidc_completion())

        return self.async_external_step(step_id="oidc_login", url=login_url)

    async def _poll_oidc_completion(self) -> None:
        """Background task: poll auth status and advance the flow when done."""
        session = async_get_clientsession(self.hass)
        client = ErgApiClient(session, self._base_url, self._api_token)

        for _ in range(_OIDC_POLL_MAX_ATTEMPTS):
            await asyncio.sleep(_OIDC_POLL_INTERVAL)
            try:
                status_data = await client.poll_auth_status(self._oidc_state)
            except Exception:
                _LOGGER.debug("Error polling auth status, retrying")
                continue

            status = status_data.get("status", "expired")

            if status == "complete":
                self._session_token = status_data.get("session_token")
                self._oidc_user = status_data.get("user")
                await self.hass.config_entries.flow.async_configure(
                    flow_id=self.flow_id
                )
                return

            if status == "expired":
                await self.hass.config_entries.flow.async_configure(
                    flow_id=self.flow_id
                )
                return

        # Timed out — advance anyway so the step handler can abort
        await self.hass.config_entries.flow.async_configure(
            flow_id=self.flow_id
        )

    async def async_step_oidc_login(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Called when the background poller advances the flow."""
        if self._session_token:
            return self.async_external_step_done(next_step_id="oidc_done")
        return self.async_abort(reason="oidc_flow_expired")

    async def async_step_oidc_done(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Complete the OIDC flow and create the config entry."""
        user_display = ""
        if self._oidc_user:
            user_display = self._oidc_user.get(
                "display_name", self._oidc_user.get("email", "")
            )

        title = f"Erg ({self._host}:{self._port})"
        if user_display:
            title = f"Erg ({user_display})"

        return self.async_create_entry(
            title=title,
            data={
                CONF_HOST: self._host,
                CONF_PORT: self._port,
                CONF_USE_SSL: self._use_ssl,
                CONF_API_TOKEN: self._api_token,
                CONF_SESSION_TOKEN: self._session_token,
            },
        )

    # ── Reauth flow ──────────────────────────────────────────────────────

    async def async_step_reauth(
        self, entry_data: dict[str, Any]
    ) -> FlowResult:
        """Handle re-authentication when session expires."""
        self._host = entry_data[CONF_HOST]
        self._port = entry_data[CONF_PORT]
        self._use_ssl = entry_data.get(CONF_USE_SSL, False)
        self._api_token = entry_data.get(CONF_API_TOKEN)

        scheme = "https" if self._use_ssl else "http"
        self._base_url = f"{scheme}://{self._host}:{self._port}"

        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Confirm re-authentication — offer OIDC or new token."""
        errors: dict[str, str] = {}

        if user_input is not None:
            method = user_input.get("auth_method", "token")

            if method == "token":
                token = user_input.get(CONF_API_TOKEN) or None
                session = async_get_clientsession(self.hass)
                client = ErgApiClient(session, self._base_url, token)
                try:
                    await client.health()
                except ErgAuthError:
                    errors["base"] = "invalid_auth"
                except ErgConnectionError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    errors["base"] = "cannot_connect"
                else:
                    entry = self.hass.config_entries.async_get_entry(
                        self.context["entry_id"]
                    )
                    if entry:
                        new_data = {**entry.data, CONF_API_TOKEN: token}
                        new_data.pop(CONF_SESSION_TOKEN, None)
                        self.hass.config_entries.async_update_entry(
                            entry, data=new_data
                        )
                    return self.async_abort(reason="reauth_successful")
            else:
                # OIDC re-auth
                return await self._start_oidc_flow(method)

        # Check for OIDC providers
        session = async_get_clientsession(self.hass)
        client = ErgApiClient(session, self._base_url, self._api_token)
        try:
            providers = await client.get_auth_providers()
        except Exception:
            providers = []

        choices: dict[str, str] = {"token": "Enter new API token"}
        for provider in providers:
            name = provider.get("name", "")
            display = provider.get("display_name", name)
            choices[name] = f"Sign in with {display}"

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required("auth_method", default="token"): vol.In(
                        choices
                    ),
                    vol.Optional(CONF_API_TOKEN, default=""): str,
                }
            ),
            errors=errors,
        )

    @classmethod
    @callback
    def async_get_supported_subentry_types(
        cls, config_entry: ConfigEntry
    ) -> dict[str, type[ConfigSubentryFlow]]:
        """Return supported subentry types."""
        return {"job": JobSubentryFlowHandler}

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> ErgOptionsFlow:
        """Return the options flow handler."""
        return ErgOptionsFlow(config_entry)


class ErgOptionsFlow(OptionsFlow):
    """Handle options for the Erg integration.

    Multi-step wizard:
      init (system params) -> tariffs_menu -> save
    """

    def __init__(self, config_entry: ConfigEntry) -> None:
        self._config_entry = config_entry
        self._system_opts: dict[str, Any] = {}
        self._tariffs: list[dict[str, Any]] = []
        self._edit_index: int = 0

    # -- Step 1: System parameters -----------------------------------------

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage system parameters and data sources."""
        if user_input is not None:
            self._system_opts = user_input
            self._tariffs = list(self._config_entry.options.get("tariff_periods", []))
            return await self.async_step_tariffs_menu()

        opts = self._config_entry.options

        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "grid_import_limit",
                        default=opts.get("grid_import_limit", 14.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "grid_export_limit",
                        default=opts.get("grid_export_limit", 5.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "inverter_power",
                        default=opts.get("inverter_power", 10.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_capacity",
                        default=opts.get("battery_capacity", 42.0),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_storage_value",
                        default=opts.get("battery_storage_value", 0.1),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_preservation",
                        default=opts.get("battery_preservation", 0.03),
                    ): vol.Coerce(float),
                    vol.Optional(
                        "battery_soc_entity",
                        default=opts.get("battery_soc_entity", "sensor.foxess_bat_soc"),
                    ): str,
                    vol.Optional(
                        "solar_forecast_provider",
                        default=opts.get("solar_forecast_provider", "auto"),
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
                        "extend_to_end_of_day",
                        default=opts.get(
                            "extend_to_end_of_day", DEFAULT_EXTEND_TO_END_OF_DAY
                        ),
                    ): bool,
                    vol.Optional(
                        "slot_duration",
                        default=opts.get("slot_duration", DEFAULT_SLOT_DURATION),
                    ): str,
                }
            ),
        )

    # -- Step 2: Tariffs menu ----------------------------------------------

    async def async_step_tariffs_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Show tariffs list with Add / Edit / Delete / Save actions."""
        if user_input is not None:
            action = user_input.get("action", "save")
            if action == "add":
                return await self.async_step_add_tariff()
            if action == "import_yaml":
                return await self.async_step_import_tariffs_yaml()
            if action == "save":
                return self._save_all()
            if action.startswith("edit_"):
                self._edit_index = int(action.split("_", 1)[1])
                return await self.async_step_edit_tariff()
            if action.startswith("delete_"):
                idx = int(action.split("_", 1)[1])
                if 0 <= idx < len(self._tariffs):
                    self._tariffs.pop(idx)
                return await self.async_step_tariffs_menu()

        menu_choices: dict[str, str] = {"add": "Add new tariff period"}
        menu_choices["import_yaml"] = "Import tariffs from YAML"
        for i, tariff in enumerate(self._tariffs):
            label = tariff.get("name", f"Tariff {i}")
            menu_choices[f"edit_{i}"] = f"Edit: {label}"
            menu_choices[f"delete_{i}"] = f"Delete: {label}"
        menu_choices["save"] = "Save all settings"

        return self.async_show_form(
            step_id="tariffs_menu",
            data_schema=vol.Schema(
                {vol.Required("action", default="save"): vol.In(menu_choices)}
            ),
        )

    # -- Step 2a: Add tariff -----------------------------------------------

    async def async_step_add_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Collect fields for a new tariff period."""
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_tariff_input(user_input)
            if not errors:
                self._tariffs.append(_build_tariff_dict(user_input))
                return await self.async_step_tariffs_menu()

        return self.async_show_form(
            step_id="add_tariff",
            data_schema=_tariff_schema(user_input if user_input else None),
            errors=errors,
        )

    # -- Step 2b: Edit tariff ----------------------------------------------

    async def async_step_edit_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing tariff period."""
        idx = self._edit_index
        if idx < 0 or idx >= len(self._tariffs):
            return await self.async_step_tariffs_menu()

        errors: dict[str, str] = {}
        if user_input is not None:
            errors = _validate_tariff_input(user_input)
            if not errors:
                self._tariffs[idx] = _build_tariff_dict(user_input)
                return await self.async_step_tariffs_menu()

        defaults = user_input if user_input else self._tariffs[idx]
        return self.async_show_form(
            step_id="edit_tariff",
            data_schema=_tariff_schema(defaults),
            errors=errors,
        )

    # -- Step 2c: Import tariffs from YAML ----------------------------------

    async def async_step_import_tariffs_yaml(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Import tariff periods from pasted YAML."""
        errors: dict[str, str] = {}
        if user_input is not None:
            yaml_text = user_input.get("tariffs_yaml", "")
            parsed, error = _parse_tariff_yaml(yaml_text)
            if error:
                errors["tariffs_yaml"] = error
            else:
                self._tariffs = parsed
                return await self.async_step_tariffs_menu()

        return self.async_show_form(
            step_id="import_tariffs_yaml",
            data_schema=vol.Schema(
                {
                    vol.Required("tariffs_yaml", default=""): TextSelector(
                        TextSelectorConfig(multiline=True)
                    )
                }
            ),
            errors=errors,
        )

    # -- Final save --------------------------------------------------------

    def _save_all(self) -> FlowResult:
        """Commit system opts and tariffs in one entry."""
        data = dict(self._system_opts)
        data["tariff_periods"] = self._tariffs
        return self.async_create_entry(title="", data=data)


class JobSubentryFlowHandler(ConfigSubentryFlow):
    """Handle creation of a job subentry."""

    def __init__(self) -> None:
        """Initialize the subentry flow."""
        super().__init__()
        self._user_data: dict[str, Any] = {}

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 1: Collect basic job info."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._user_data = dict(user_input)
            job_type = user_input["job_type"]
            if job_type == "recurring":
                return await self.async_step_recurring()
            return await self.async_step_oneshot()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema(
                {
                    vol.Required("entity_id"): str,
                    vol.Required("job_type"): vol.In(
                        {"recurring": "Recurring", "oneshot": "One-shot"}
                    ),
                    vol.Optional("ac_power", default=0.0): vol.Coerce(float),
                    vol.Optional("dc_power", default=0.0): vol.Coerce(float),
                    vol.Optional("force", default=False): bool,
                    vol.Optional("benefit", default=0.0): vol.Coerce(float),
                    vol.Optional("enabled", default=True): bool,
                }
            ),
            errors=errors,
        )

    async def async_step_recurring(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2a: Recurring schedule parameters."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate time fields
            for field in ("time_window_start", "time_window_end"):
                try:
                    validate_time_str(user_input.get(field, ""))
                except vol.Invalid:
                    errors[field] = "invalid_time"

            # Validate duration fields
            for field in ("maximum_duration", "minimum_duration", "minimum_burst"):
                try:
                    validate_duration(user_input.get(field, ""))
                except vol.Invalid:
                    errors[field] = "invalid_duration"

            if not errors:
                return await self._create_job({**self._user_data, **user_input})

        return self.async_show_form(
            step_id="recurring",
            data_schema=vol.Schema(
                {
                    vol.Required("frequency", default="daily"): vol.In(
                        FREQUENCY_CHOICES
                    ),
                    vol.Required(
                        "time_window_start", default="09:00"
                    ): str,
                    vol.Required(
                        "time_window_end", default="17:00"
                    ): str,
                    vol.Required(
                        "maximum_duration", default="1h"
                    ): str,
                    vol.Optional(
                        "minimum_duration", default="0s"
                    ): str,
                    vol.Optional(
                        "minimum_burst", default="0s"
                    ): str,
                    vol.Optional("day_of_week"): vol.In(DAY_OF_WEEK_CHOICES),
                    vol.Optional("days_of_week_str", default=""): str,
                }
            ),
            errors=errors,
        )

    async def async_step_oneshot(
        self, user_input: dict[str, Any] | None = None
    ) -> SubentryFlowResult:
        """Step 2b: One-shot schedule parameters."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Validate duration fields
            for field in ("maximum_duration", "minimum_duration", "minimum_burst"):
                try:
                    validate_duration(user_input.get(field, ""))
                except vol.Invalid:
                    errors[field] = "invalid_duration"

            if not errors:
                return await self._create_job({**self._user_data, **user_input})

        return self.async_show_form(
            step_id="oneshot",
            data_schema=vol.Schema(
                {
                    vol.Optional("start", default=""): str,
                    vol.Optional("finish", default=""): str,
                    vol.Required(
                        "maximum_duration", default="1h"
                    ): str,
                    vol.Optional(
                        "minimum_duration", default="0s"
                    ): str,
                    vol.Optional(
                        "minimum_burst", default="0s"
                    ): str,
                }
            ),
            errors=errors,
        )

    async def _create_job(self, job_data: dict[str, Any]) -> SubentryFlowResult:
        """Validate and create the job subentry.

        Entity creation is handled by _async_update_listener when the
        subentry is persisted, ensuring entities get the correct
        config_subentry_id for device association.
        """
        config_entry = self._get_entry()

        # Check that the integration is loaded
        if config_entry.state is not ConfigEntryState.LOADED:
            return self.async_abort(reason="config_entry_not_loaded")

        entry_data = self.hass.data.get(DOMAIN, {}).get(config_entry.entry_id)
        if entry_data is None:
            return self.async_abort(reason="config_entry_not_loaded")

        entity_id = job_data["entity_id"]

        # Check for duplicate
        job_entities = entry_data.get("job_entities", {})
        if entity_id in job_entities:
            return self.async_abort(reason="already_configured")

        # Parse days_of_week_str into days_of_week list if present
        days_str = job_data.pop("days_of_week_str", "")
        if days_str and days_str.strip():
            job_data["days_of_week"] = _parse_days_of_week_str(days_str)

        return self.async_create_entry(
            title=entity_id,
            data=job_data,
            unique_id=entity_id,
        )


# -- Input validators -------------------------------------------------------


def _validate_tariff_input(user_input: dict[str, Any]) -> dict[str, str]:
    """Validate tariff form input, returning a field->error dict."""
    errors: dict[str, str] = {}
    for field in ("time_window_start", "time_window_end"):
        try:
            validate_time_str(user_input.get(field, ""))
        except vol.Invalid:
            errors[field] = "invalid_time"
    return errors



# -- Schema builders ---------------------------------------------------------


def _tariff_schema(
    defaults: dict[str, Any] | None = None,
) -> vol.Schema:
    """Build the voluptuous schema for a tariff period form."""
    d = defaults or {}
    rec = d.get("recurrence") or {}
    days_str = ",".join(str(x) for x in rec.get("days_of_week", []))

    return vol.Schema(
        {
            vol.Required("name", default=d.get("name", "")): str,
            vol.Required(
                "frequency", default=rec.get("frequency", "daily")
            ): vol.In(FREQUENCY_CHOICES),
            vol.Required(
                "time_window_start",
                default=rec.get("time_window_start", "00:00"),
            ): str,
            vol.Required(
                "time_window_end",
                default=rec.get("time_window_end", "23:59"),
            ): str,
            vol.Required(
                "import_price", default=d.get("import_price", 0.0)
            ): vol.Coerce(float),
            vol.Required(
                "feed_in_price", default=d.get("feed_in_price", 0.0)
            ): vol.Coerce(float),
            vol.Optional(
                "day_of_week", default=rec.get("day_of_week", 0)
            ): vol.In(DAY_OF_WEEK_CHOICES),
            vol.Optional("days_of_week_str", default=days_str): str,
        }
    )


# -- Dict builders -----------------------------------------------------------


def _parse_days_of_week_str(s: str) -> list[int]:
    """Parse a comma-separated string of day ints, e.g. '0,2,4'."""
    if not s or not s.strip():
        return []
    result = []
    for part in s.split(","):
        part = part.strip()
        if part.isdigit():
            result.append(int(part))
    return result


def _build_tariff_dict(user_input: dict[str, Any]) -> dict[str, Any]:
    """Convert flat form input into a tariff period dict."""
    recurrence: dict[str, Any] = {
        "frequency": user_input["frequency"],
        "time_window_start": user_input["time_window_start"],
        "time_window_end": user_input["time_window_end"],
    }
    freq = user_input["frequency"]
    if freq == "weekly":
        recurrence["day_of_week"] = user_input.get("day_of_week", 0)
    elif freq == "custom":
        recurrence["days_of_week"] = _parse_days_of_week_str(
            user_input.get("days_of_week_str", "")
        )

    return {
        "name": user_input["name"],
        "import_price": user_input["import_price"],
        "feed_in_price": user_input["feed_in_price"],
        "recurrence": recurrence,
    }


# -- YAML tariff import -----------------------------------------------------

_TIME_IMPORT_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def _parse_tariff_yaml(
    yaml_text: str,
) -> tuple[list[dict[str, Any]], str | None]:
    """Parse a YAML tariff definition into a list of tariff dicts.

    Returns (tariffs, error). On success error is None.
    On failure tariffs is an empty list and error is a user-facing message.

    Expected YAML format::

        periods:
          - start: "00:00"
            end: "07:00"
            import_price: 0.12
            feed_in_price: 0.05
          - start: "07:00"
            end: "22:00"
            import_price: 0.36
            feed_in_price: 0.03

    Alternatively the YAML may be a bare list (without the ``periods`` key).
    """
    if not yaml_text or not yaml_text.strip():
        return [], "invalid_yaml"

    try:
        data = yaml.safe_load(yaml_text)
    except yaml.YAMLError:
        return [], "invalid_yaml"

    if data is None:
        return [], "invalid_yaml"

    # Accept either {"periods": [...]} or a bare list.
    if isinstance(data, dict):
        periods = data.get("periods")
        if periods is None:
            return [], "invalid_yaml"
    elif isinstance(data, list):
        periods = data
    else:
        return [], "invalid_yaml"

    if not isinstance(periods, list) or len(periods) == 0:
        return [], "invalid_yaml"

    tariffs: list[dict[str, Any]] = []
    for i, p in enumerate(periods):
        if not isinstance(p, dict):
            return [], "invalid_yaml"

        start = str(p.get("start", "")).strip()
        end = str(p.get("end", "")).strip()

        if not _TIME_IMPORT_RE.match(start) or not _TIME_IMPORT_RE.match(end):
            return [], "invalid_yaml_time"

        try:
            import_price = float(p.get("import_price", 0))
            feed_in_price = float(p.get("feed_in_price", 0))
        except (TypeError, ValueError):
            return [], "invalid_yaml_price"

        name = str(p.get("name", "")).strip()
        if not name:
            name = f"Tariff {i + 1} ({start}-{end})"

        tariffs.append(
            {
                "name": name,
                "import_price": import_price,
                "feed_in_price": feed_in_price,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": start,
                    "time_window_end": end,
                },
            }
        )

    return tariffs, None
