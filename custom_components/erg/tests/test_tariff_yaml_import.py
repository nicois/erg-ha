"""Tests for YAML tariff import in config_flow.py."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.erg.config_flow import (
    ErgOptionsFlow,
    _parse_tariff_yaml,
)


# ── _parse_tariff_yaml ─────────────────────────────────────────────────


class TestParseTariffYaml:
    def test_valid_periods_key(self):
        yaml_text = """
periods:
  - start: "00:00"
    end: "07:00"
    import_price: 0.12
    feed_in_price: 0.05
  - start: "07:00"
    end: "22:00"
    import_price: 0.36
    feed_in_price: 0.03
  - start: "22:00"
    end: "00:00"
    import_price: 0.12
    feed_in_price: 0.05
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert error is None
        assert len(tariffs) == 3
        assert tariffs[0]["import_price"] == 0.12
        assert tariffs[0]["recurrence"]["time_window_start"] == "00:00"
        assert tariffs[0]["recurrence"]["time_window_end"] == "07:00"
        assert tariffs[0]["recurrence"]["frequency"] == "daily"

    def test_valid_bare_list(self):
        yaml_text = """
- start: "00:00"
  end: "12:00"
  import_price: 0.20
  feed_in_price: 0.05
- start: "12:00"
  end: "00:00"
  import_price: 0.30
  feed_in_price: 0.03
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert error is None
        assert len(tariffs) == 2

    def test_auto_generated_names(self):
        yaml_text = """
periods:
  - start: "00:00"
    end: "12:00"
    import_price: 0.20
    feed_in_price: 0.05
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert error is None
        assert tariffs[0]["name"] == "Tariff 1 (00:00-12:00)"

    def test_explicit_name_preserved(self):
        yaml_text = """
periods:
  - name: "Off-Peak"
    start: "00:00"
    end: "07:00"
    import_price: 0.12
    feed_in_price: 0.05
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert error is None
        assert tariffs[0]["name"] == "Off-Peak"

    def test_empty_string(self):
        tariffs, error = _parse_tariff_yaml("")
        assert tariffs == []
        assert error == "invalid_yaml"

    def test_whitespace_only(self):
        tariffs, error = _parse_tariff_yaml("   \n  ")
        assert tariffs == []
        assert error == "invalid_yaml"

    def test_invalid_yaml_syntax(self):
        tariffs, error = _parse_tariff_yaml("{{not yaml")
        assert tariffs == []
        assert error == "invalid_yaml"

    def test_missing_periods_key(self):
        tariffs, error = _parse_tariff_yaml("other_key: 123")
        assert tariffs == []
        assert error == "invalid_yaml"

    def test_empty_periods_list(self):
        tariffs, error = _parse_tariff_yaml("periods: []")
        assert tariffs == []
        assert error == "invalid_yaml"

    def test_invalid_time_format(self):
        yaml_text = """
periods:
  - start: "25:00"
    end: "07:00"
    import_price: 0.12
    feed_in_price: 0.05
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert tariffs == []
        assert error == "invalid_yaml_time"

    def test_negative_price(self):
        yaml_text = """
periods:
  - start: "00:00"
    end: "12:00"
    import_price: -0.10
    feed_in_price: 0.05
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert tariffs == []
        assert error == "invalid_yaml_price"

    def test_non_numeric_price(self):
        yaml_text = """
periods:
  - start: "00:00"
    end: "12:00"
    import_price: "abc"
    feed_in_price: 0.05
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert tariffs == []
        assert error == "invalid_yaml_price"

    def test_period_not_a_dict(self):
        yaml_text = """
periods:
  - "not a dict"
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert tariffs == []
        assert error == "invalid_yaml"

    def test_missing_prices_default_to_zero(self):
        yaml_text = """
periods:
  - start: "00:00"
    end: "12:00"
"""
        tariffs, error = _parse_tariff_yaml(yaml_text)
        assert error is None
        assert tariffs[0]["import_price"] == 0.0
        assert tariffs[0]["feed_in_price"] == 0.0


# ── Flow step helpers ──────────────────────────────────────────────────


ENTRY_ID = "test_entry_123"


def _make_options_flow(
    options: dict | None = None,
) -> ErgOptionsFlow:
    """Create an ErgOptionsFlow with a mocked config_entry."""
    entry = MagicMock()
    entry.options = options or {}
    entry.entry_id = ENTRY_ID

    flow = ErgOptionsFlow(entry)
    flow.hass = MagicMock()
    flow.hass.data = {"erg": {ENTRY_ID: {}}}

    return flow


# ── YAML import flow step tests ────────────────────────────────────────


class TestImportTariffsYamlFlow:
    @pytest.mark.asyncio
    async def test_shows_form_when_no_input(self):
        flow = _make_options_flow()
        result = await flow.async_step_import_tariffs_yaml(user_input=None)
        assert result["type"] == "form"
        assert result["step_id"] == "import_tariffs_yaml"

    @pytest.mark.asyncio
    async def test_valid_yaml_replaces_tariffs(self):
        flow = _make_options_flow()
        flow._tariffs = [{"name": "Old tariff"}]
        yaml_text = """
periods:
  - start: "00:00"
    end: "12:00"
    import_price: 0.20
    feed_in_price: 0.05
  - start: "12:00"
    end: "00:00"
    import_price: 0.30
    feed_in_price: 0.03
"""
        result = await flow.async_step_import_tariffs_yaml(
            user_input={"tariffs_yaml": yaml_text}
        )
        assert result["step_id"] == "tariffs_menu"
        assert len(flow._tariffs) == 2
        assert flow._tariffs[0]["import_price"] == 0.20

    @pytest.mark.asyncio
    async def test_invalid_yaml_shows_error(self):
        flow = _make_options_flow()
        flow._tariffs = [{"name": "Existing"}]
        result = await flow.async_step_import_tariffs_yaml(
            user_input={"tariffs_yaml": "{{bad yaml"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "import_tariffs_yaml"
        assert "tariffs_yaml" in result["errors"]
        # Original tariffs should be unchanged
        assert len(flow._tariffs) == 1

    @pytest.mark.asyncio
    async def test_tariffs_menu_import_yaml_action(self):
        flow = _make_options_flow()
        flow._tariffs = []
        result = await flow.async_step_tariffs_menu(
            user_input={"action": "import_yaml"}
        )
        assert result["type"] == "form"
        assert result["step_id"] == "import_tariffs_yaml"
