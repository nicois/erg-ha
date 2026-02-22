"""Tests for config_flow.py — dict builders, schema builders, and flow navigation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.config_flow import (
    ErgOptionsFlow,
    _build_job_attrs,
    _build_tariff_dict,
    _job_schema,
    _parse_days_of_week_str,
    _tariff_schema,
)
from custom_components.erg.job_entities import ErgJobEntity


# ── _parse_days_of_week_str ─────────────────────────────────────────────


class TestParseDaysOfWeekStr:
    def test_empty_string(self):
        assert _parse_days_of_week_str("") == []

    def test_whitespace_only(self):
        assert _parse_days_of_week_str("   ") == []

    def test_single_day(self):
        assert _parse_days_of_week_str("3") == [3]

    def test_multiple_days(self):
        assert _parse_days_of_week_str("0,2,4") == [0, 2, 4]

    def test_with_spaces(self):
        assert _parse_days_of_week_str(" 1 , 3 , 5 ") == [1, 3, 5]

    def test_ignores_non_digit(self):
        assert _parse_days_of_week_str("0,abc,4") == [0, 4]


# ── _build_tariff_dict ───────────────────────────────────────────────────


class TestBuildTariffDict:
    def test_daily_tariff(self):
        inp = {
            "name": "Off-Peak",
            "frequency": "daily",
            "time_window_start": "22:00",
            "time_window_end": "07:00",
            "import_price": 0.12,
            "feed_in_price": 0.05,
            "day_of_week": 0,
            "days_of_week_str": "",
        }
        result = _build_tariff_dict(inp)
        assert result["name"] == "Off-Peak"
        assert result["import_price"] == 0.12
        assert result["feed_in_price"] == 0.05
        assert result["recurrence"]["frequency"] == "daily"
        assert result["recurrence"]["time_window_start"] == "22:00"
        assert result["recurrence"]["time_window_end"] == "07:00"

    def test_weekly_tariff_sets_day_of_week(self):
        inp = {
            "name": "Wednesday Special",
            "frequency": "weekly",
            "time_window_start": "10:00",
            "time_window_end": "16:00",
            "import_price": 0.08,
            "feed_in_price": 0.06,
            "day_of_week": 2,
            "days_of_week_str": "",
        }
        result = _build_tariff_dict(inp)
        assert result["recurrence"]["day_of_week"] == 2

    def test_custom_tariff_parses_days(self):
        inp = {
            "name": "Custom",
            "frequency": "custom",
            "time_window_start": "08:00",
            "time_window_end": "12:00",
            "import_price": 0.20,
            "feed_in_price": 0.04,
            "day_of_week": 0,
            "days_of_week_str": "1,3,5",
        }
        result = _build_tariff_dict(inp)
        assert result["recurrence"]["days_of_week"] == [1, 3, 5]


# ── Schema builder tests ────────────────────────────────────────────────


class TestSchemaBuilders:
    def test_tariff_schema_defaults(self):
        schema = _tariff_schema()
        keys = {str(k) for k in schema.schema}
        assert "name" in keys
        assert "import_price" in keys
        assert "frequency" in keys


# ── Flow navigation tests (mocked HA) ───────────────────────────────────


ENTRY_ID = "test_entry_123"


def _make_options_flow(
    options: dict | None = None,
    job_entities: dict | None = None,
) -> ErgOptionsFlow:
    """Create an ErgOptionsFlow with a mocked config_entry.

    The stub OptionsFlow base class (from root conftest.py) already provides
    async_show_form and async_create_entry that return plain dicts.
    """
    entry = MagicMock()
    entry.options = options or {}
    entry.entry_id = ENTRY_ID

    flow = ErgOptionsFlow(entry)

    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    entry_data = {
        "coordinator": coordinator,
        "job_entities": job_entities if job_entities is not None else {},
        "add_job_sensors": MagicMock(),
        "add_per_job_sensors": MagicMock(),
        "add_job_binary_sensors": MagicMock(),
        "per_job_sensors": {},
        "per_job_binary_sensors": {},
        "entry_options": {},
    }
    flow.hass = MagicMock()
    flow.hass.data = {"erg": {ENTRY_ID: entry_data}}

    return flow


class TestOptionsFlowNavigation:
    @pytest.mark.asyncio
    async def test_init_shows_form_when_no_input(self):
        flow = _make_options_flow()
        result = await flow.async_step_init(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "init"

    @pytest.mark.asyncio
    async def test_init_with_input_advances_to_tariffs_menu(self):
        flow = _make_options_flow({"tariff_periods": []})
        result = await flow.async_step_init(
            user_input={"grid_import_limit": 10.0, "grid_export_limit": 5.0}
        )
        # Should show the tariffs_menu form (jobs step removed)
        assert result["type"] == "form"
        assert result["step_id"] == "tariffs_menu"

    @pytest.mark.asyncio
    async def test_tariffs_menu_add_goes_to_add_tariff(self):
        flow = _make_options_flow()
        flow._tariffs = []
        result = await flow.async_step_tariffs_menu(user_input={"action": "add"})
        assert result["type"] == "form"
        assert result["step_id"] == "add_tariff"

    @pytest.mark.asyncio
    async def test_tariffs_menu_delete_removes_tariff(self):
        flow = _make_options_flow()
        flow._tariffs = [{"name": "Peak"}, {"name": "Off-Peak"}]
        result = await flow.async_step_tariffs_menu(
            user_input={"action": "delete_1"}
        )
        assert len(flow._tariffs) == 1
        assert flow._tariffs[0]["name"] == "Peak"

    @pytest.mark.asyncio
    async def test_tariffs_menu_save_goes_to_jobs_menu(self):
        flow = _make_options_flow()
        flow._system_opts = {"grid_import_limit": 10.0}
        flow._tariffs = [{"name": "Peak", "import_price": 0.35}]
        result = await flow.async_step_tariffs_menu(user_input={"action": "save"})
        # "save" in tariffs_menu now routes to jobs_menu, not final save
        assert result["type"] == "form"
        assert result["step_id"] == "jobs_menu"

    @pytest.mark.asyncio
    async def test_add_tariff_appends_and_returns_to_menu(self):
        flow = _make_options_flow()
        flow._tariffs = []
        result = await flow.async_step_add_tariff(
            user_input={
                "name": "Off-Peak",
                "frequency": "daily",
                "time_window_start": "22:00",
                "time_window_end": "07:00",
                "import_price": 0.12,
                "feed_in_price": 0.05,
                "day_of_week": 0,
                "days_of_week_str": "",
            }
        )
        assert len(flow._tariffs) == 1
        assert flow._tariffs[0]["name"] == "Off-Peak"
        assert result["step_id"] == "tariffs_menu"

    @pytest.mark.asyncio
    async def test_edit_tariff_updates_in_place(self):
        flow = _make_options_flow()
        flow._tariffs = [
            {
                "name": "Old",
                "import_price": 0.10,
                "feed_in_price": 0.02,
                "recurrence": {
                    "frequency": "daily",
                    "time_window_start": "00:00",
                    "time_window_end": "23:59",
                },
            }
        ]
        flow._edit_index = 0
        result = await flow.async_step_edit_tariff(
            user_input={
                "name": "Updated",
                "frequency": "weekdays",
                "time_window_start": "14:00",
                "time_window_end": "20:00",
                "import_price": 0.35,
                "feed_in_price": 0.03,
                "day_of_week": 0,
                "days_of_week_str": "",
            }
        )
        assert flow._tariffs[0]["name"] == "Updated"
        assert flow._tariffs[0]["import_price"] == 0.35
        assert result["step_id"] == "tariffs_menu"


# ── Job schema / dict builder tests ──────────────────────────────────────


class TestJobSchemaBuilders:
    def test_job_schema_defaults(self):
        schema = _job_schema()
        keys = {str(k) for k in schema.schema}
        assert "entity_id" in keys
        assert "job_type" in keys
        assert "ac_power" in keys
        assert "start" in keys
        assert "finish" in keys

    def test_job_schema_with_defaults(self):
        defaults = {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.5,
            "days_of_week": [0, 2, 4],
        }
        schema = _job_schema(defaults)
        # Just verifies it builds without error
        assert schema is not None


class TestBuildJobAttrs:
    def test_basic_recurring_job(self):
        inp = {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.5,
            "dc_power": 0.0,
            "force": False,
            "enabled": True,
            "frequency": "daily",
            "time_window_start": "09:00",
            "time_window_end": "17:00",
            "maximum_duration": "3h",
            "minimum_duration": "1h",
            "minimum_burst": "30m",
            "day_of_week": 0,
            "days_of_week_str": "",
            "start": "",
            "finish": "",
        }
        result = _build_job_attrs(inp)
        assert result["entity_id"] == "switch.pool_pump"
        assert result["job_type"] == "recurring"
        assert result["ac_power"] == 1.5

    def test_days_of_week_str_parsed(self):
        inp = {
            "entity_id": "switch.heater",
            "job_type": "recurring",
            "days_of_week_str": "1,3,5",
        }
        result = _build_job_attrs(inp)
        assert result["days_of_week"] == [1, 3, 5]

    def test_empty_days_of_week_str_omitted(self):
        inp = {
            "entity_id": "switch.heater",
            "job_type": "recurring",
            "days_of_week_str": "",
        }
        result = _build_job_attrs(inp)
        assert "days_of_week" not in result


# ── Jobs menu flow navigation tests ─────────────────────────────────────


class TestJobsMenuNavigation:
    @pytest.mark.asyncio
    async def test_jobs_menu_shows_existing_jobs(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })
        flow = _make_options_flow(job_entities={"switch.pool_pump": entity})
        result = await flow.async_step_jobs_menu(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "jobs_menu"
        # The schema should contain edit/delete actions for the existing job
        schema_dict = result["data_schema"].schema
        action_choices = schema_dict["action"]
        assert "edit_switch.pool_pump" in action_choices
        assert "delete_switch.pool_pump" in action_choices
        assert "add" in action_choices
        assert "save" in action_choices

    @pytest.mark.asyncio
    async def test_jobs_menu_add_goes_to_add_job(self):
        flow = _make_options_flow()
        result = await flow.async_step_jobs_menu(user_input={"action": "add"})
        assert result["type"] == "form"
        assert result["step_id"] == "add_job"

    @pytest.mark.asyncio
    async def test_add_job_creates_entity_and_returns(self):
        flow = _make_options_flow()
        entry_data = flow.hass.data["erg"][ENTRY_ID]

        result = await flow.async_step_add_job(
            user_input={
                "entity_id": "switch.pool_pump",
                "job_type": "recurring",
                "ac_power": 1.5,
                "dc_power": 0.0,
                "force": False,
                "enabled": True,
                "frequency": "daily",
                "time_window_start": "09:00",
                "time_window_end": "17:00",
                "maximum_duration": "3h",
                "minimum_duration": "1h",
                "minimum_burst": "30m",
                "day_of_week": 0,
                "days_of_week_str": "",
                "start": "",
                "finish": "",
            }
        )
        # Should return to jobs_menu
        assert result["step_id"] == "jobs_menu"
        # Entity should have been created
        assert "switch.pool_pump" in entry_data["job_entities"]
        entity = entry_data["job_entities"]["switch.pool_pump"]
        assert isinstance(entity, ErgJobEntity)
        assert entity.extra_state_attributes["ac_power"] == 1.5
        entry_data["coordinator"].async_request_refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_jobs_menu_edit_goes_to_edit_job(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.0,
        })
        entity.async_write_ha_state = MagicMock()
        flow = _make_options_flow(job_entities={"switch.pool_pump": entity})
        result = await flow.async_step_jobs_menu(
            user_input={"action": "edit_switch.pool_pump"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "edit_job"
        assert flow._edit_job_id == "switch.pool_pump"

    @pytest.mark.asyncio
    async def test_edit_job_updates_and_returns(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.0,
        })
        entity.async_write_ha_state = MagicMock()
        flow = _make_options_flow(job_entities={"switch.pool_pump": entity})
        flow._edit_job_id = "switch.pool_pump"

        result = await flow.async_step_edit_job(
            user_input={
                "entity_id": "switch.pool_pump",
                "job_type": "recurring",
                "ac_power": 2.5,
                "dc_power": 0.0,
                "force": True,
                "enabled": True,
                "frequency": "daily",
                "time_window_start": "09:00",
                "time_window_end": "17:00",
                "maximum_duration": "3h",
                "minimum_duration": "1h",
                "minimum_burst": "30m",
                "day_of_week": 0,
                "days_of_week_str": "",
                "start": "",
                "finish": "",
            }
        )
        assert result["step_id"] == "jobs_menu"
        assert entity.extra_state_attributes["ac_power"] == 2.5
        assert entity.extra_state_attributes["force"] is True
        entry_data = flow.hass.data["erg"][ENTRY_ID]
        entry_data["coordinator"].async_request_refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_jobs_menu_delete_removes_entity(self):
        entity = MagicMock()
        entity.async_remove = AsyncMock()
        flow = _make_options_flow(job_entities={"switch.pool_pump": entity})
        entry_data = flow.hass.data["erg"][ENTRY_ID]

        result = await flow.async_step_jobs_menu(
            user_input={"action": "delete_switch.pool_pump"}
        )
        # Should return to jobs_menu
        assert result["step_id"] == "jobs_menu"
        # Entity should have been removed
        assert "switch.pool_pump" not in entry_data["job_entities"]
        entity.async_remove.assert_awaited_once()
        entry_data["coordinator"].async_request_refresh.assert_awaited()

    @pytest.mark.asyncio
    async def test_jobs_menu_save_commits_all(self):
        flow = _make_options_flow()
        flow._system_opts = {"grid_import_limit": 10.0}
        flow._tariffs = [{"name": "Peak", "import_price": 0.35}]
        result = await flow.async_step_jobs_menu(user_input={"action": "save"})
        assert result["type"] == "create_entry"
        data = result["data"]
        assert data["grid_import_limit"] == 10.0
        assert len(data["tariff_periods"]) == 1
        assert "jobs" not in data
