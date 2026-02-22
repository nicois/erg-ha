"""Tests for config_flow.py — dict builders, schema builders, and flow navigation."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.config_flow import (
    ErgOptionsFlow,
    _build_tariff_dict,
    _parse_days_of_week_str,
    _tariff_schema,
)


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
    async def test_init_with_input_advances_to_scheduling(self):
        flow = _make_options_flow({"tariff_periods": []})
        result = await flow.async_step_init(
            user_input={"grid_import_limit": 10.0, "grid_export_limit": 5.0}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "scheduling"

    @pytest.mark.asyncio
    async def test_scheduling_with_input_advances_to_advanced(self):
        flow = _make_options_flow({"tariff_periods": []})
        flow._system_opts = {"grid_import_limit": 10.0}
        result = await flow.async_step_scheduling(
            user_input={"tariff_source": "manual", "slot_duration": "5m"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "advanced"

    @pytest.mark.asyncio
    async def test_advanced_with_input_advances_to_tariffs_menu(self):
        flow = _make_options_flow({"tariff_periods": []})
        flow._system_opts = {"grid_import_limit": 10.0}
        result = await flow.async_step_advanced(
            user_input={"battery_storage_value": 0.1, "solar_confidence": 1.0}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "tariffs_menu"

    @pytest.mark.asyncio
    async def test_scheduling_shows_form_when_no_input(self):
        flow = _make_options_flow()
        result = await flow.async_step_scheduling(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "scheduling"

    @pytest.mark.asyncio
    async def test_advanced_shows_form_when_no_input(self):
        flow = _make_options_flow()
        result = await flow.async_step_advanced(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "advanced"

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
    async def test_tariffs_menu_save_creates_entry(self):
        flow = _make_options_flow()
        flow._system_opts = {"grid_import_limit": 10.0}
        flow._tariffs = [{"name": "Peak", "import_price": 0.35}]
        result = await flow.async_step_tariffs_menu(user_input={"action": "save"})
        assert result["type"] == "create_entry"
        data = result["data"]
        assert data["grid_import_limit"] == 10.0
        assert len(data["tariff_periods"]) == 1

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


