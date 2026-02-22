"""Tests for device_action.py — Erg device actions for automations."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.device_action import (
    ACTION_TYPES,
    _get_job_entity_id_from_device,
    async_call_action_from_config,
    async_get_action_capabilities,
    async_get_actions,
)
from custom_components.erg.job_entities import ErgJobEntity


ENTRY_ID = "test_entry_123"
DEVICE_ID = "device_abc"
ENTITY_ID = "switch.pool_pump"


def _make_device(identifiers=None):
    """Create a mock device registry entry."""
    device = MagicMock()
    device.identifiers = identifiers or set()
    return device


def _make_registry(devices=None):
    """Create a mock device registry with async_get lookup."""
    registry = MagicMock()
    devices = devices or {}

    def _get(device_id):
        return devices.get(device_id)

    registry.async_get = MagicMock(side_effect=_get)
    return registry


def _patch_dr(registry):
    """Patch the dr module reference inside device_action to use our registry."""
    mock_dr = MagicMock()
    mock_dr.async_get = MagicMock(return_value=registry)
    return patch("custom_components.erg.device_action.dr", mock_dr)


def _make_hass(entry_data=None):
    """Create a mock hass with erg domain data."""
    hass = MagicMock()
    hass.data = {"erg": {ENTRY_ID: entry_data or {}}}
    return hass


def _make_entry_data(**overrides):
    """Create a standard entry_data dict."""
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    data = {
        "coordinator": coordinator,
        "job_entities": {},
    }
    data.update(overrides)
    return data


# ---------------------------------------------------------------------------
# _get_job_entity_id_from_device
# ---------------------------------------------------------------------------

class TestGetJobEntityIdFromDevice:
    def test_resolves_entity_id(self):
        device = _make_device(identifiers={("erg", "switch.pool_pump")})
        registry = _make_registry(devices={DEVICE_ID: device})
        hass = _make_hass()

        with _patch_dr(registry):
            result = _get_job_entity_id_from_device(hass, DEVICE_ID)
        assert result == "switch.pool_pump"

    def test_returns_none_for_unknown_device(self):
        registry = _make_registry(devices={})
        hass = _make_hass()

        with _patch_dr(registry):
            result = _get_job_entity_id_from_device(hass, "unknown_device")
        assert result is None

    def test_returns_none_for_wrong_domain(self):
        device = _make_device(identifiers={("other_domain", "switch.pool_pump")})
        registry = _make_registry(devices={DEVICE_ID: device})
        hass = _make_hass()

        with _patch_dr(registry):
            result = _get_job_entity_id_from_device(hass, DEVICE_ID)
        assert result is None


# ---------------------------------------------------------------------------
# async_get_actions
# ---------------------------------------------------------------------------

class TestAsyncGetActions:
    @pytest.mark.asyncio
    async def test_returns_nine_actions(self):
        device = _make_device(identifiers={("erg", ENTITY_ID)})
        registry = _make_registry(devices={DEVICE_ID: device})
        hass = _make_hass()

        with _patch_dr(registry):
            actions = await async_get_actions(hass, DEVICE_ID)
        assert len(actions) == 9
        types = {a["type"] for a in actions}
        assert types == set(ACTION_TYPES)

    @pytest.mark.asyncio
    async def test_all_actions_have_correct_keys(self):
        device = _make_device(identifiers={("erg", ENTITY_ID)})
        registry = _make_registry(devices={DEVICE_ID: device})
        hass = _make_hass()

        with _patch_dr(registry):
            actions = await async_get_actions(hass, DEVICE_ID)
        for action in actions:
            assert action["domain"] == "erg"
            assert action["device_id"] == DEVICE_ID
            assert "entity_id" not in action
            assert "type" in action

    @pytest.mark.asyncio
    async def test_returns_empty_for_unknown_device(self):
        registry = _make_registry(devices={})
        hass = _make_hass()

        with _patch_dr(registry):
            actions = await async_get_actions(hass, "unknown_device")
        assert actions == []


# ---------------------------------------------------------------------------
# async_get_action_capabilities
# ---------------------------------------------------------------------------

class TestAsyncGetActionCapabilities:
    @pytest.mark.asyncio
    async def test_bool_schema_for_force(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_force"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_bool_schema_for_enabled(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_enabled"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_float_schema_for_benefit(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_benefit"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_float_schema_for_ac_power(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_ac_power"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_float_schema_for_dc_power(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_dc_power"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_string_schema_for_maximum_duration(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_maximum_duration"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_string_schema_for_minimum_duration(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_minimum_duration"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_string_schema_for_minimum_burst(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_minimum_burst"})
        schema = caps["extra_fields"]
        assert "value" in schema.schema

    @pytest.mark.asyncio
    async def test_two_field_schema_for_time_window(self):
        hass = MagicMock()
        caps = await async_get_action_capabilities(hass, {"type": "set_time_window"})
        schema = caps["extra_fields"]
        assert "time_window_start" in schema.schema
        assert "time_window_end" in schema.schema


# ---------------------------------------------------------------------------
# async_call_action_from_config
# ---------------------------------------------------------------------------

class TestAsyncCallActionFromConfig:
    @pytest.mark.asyncio
    async def test_updates_force_attribute(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": ENTITY_ID,
            "force": False,
        })
        entity.async_write_ha_state = MagicMock()

        device = _make_device(identifiers={("erg", ENTITY_ID)})
        registry = _make_registry(devices={DEVICE_ID: device})
        entry_data = _make_entry_data(job_entities={ENTITY_ID: entity})
        hass = _make_hass(entry_data)

        config = {
            "device_id": DEVICE_ID,
            "type": "set_force",
            "value": True,
        }
        with _patch_dr(registry):
            await async_call_action_from_config(hass, config, {}, None)

        assert entity.extra_state_attributes["force"] is True
        entry_data["coordinator"].async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_updates_benefit_attribute(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": ENTITY_ID,
            "benefit": 0.0,
        })
        entity.async_write_ha_state = MagicMock()

        device = _make_device(identifiers={("erg", ENTITY_ID)})
        registry = _make_registry(devices={DEVICE_ID: device})
        entry_data = _make_entry_data(job_entities={ENTITY_ID: entity})
        hass = _make_hass(entry_data)

        config = {
            "device_id": DEVICE_ID,
            "type": "set_benefit",
            "value": 42.5,
        }
        with _patch_dr(registry):
            await async_call_action_from_config(hass, config, {}, None)

        assert entity.extra_state_attributes["benefit"] == 42.5

    @pytest.mark.asyncio
    async def test_updates_time_window_attributes(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": ENTITY_ID,
            "time_window_start": "09:00",
            "time_window_end": "17:00",
        })
        entity.async_write_ha_state = MagicMock()

        device = _make_device(identifiers={("erg", ENTITY_ID)})
        registry = _make_registry(devices={DEVICE_ID: device})
        entry_data = _make_entry_data(job_entities={ENTITY_ID: entity})
        hass = _make_hass(entry_data)

        config = {
            "device_id": DEVICE_ID,
            "type": "set_time_window",
            "time_window_start": "22:00",
            "time_window_end": "06:00",
        }
        with _patch_dr(registry):
            await async_call_action_from_config(hass, config, {}, None)

        assert entity.extra_state_attributes["time_window_start"] == "22:00"
        assert entity.extra_state_attributes["time_window_end"] == "06:00"

    @pytest.mark.asyncio
    async def test_noop_for_missing_device(self):
        registry = _make_registry(devices={})
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)

        config = {
            "device_id": "nonexistent",
            "type": "set_force",
            "value": True,
        }
        with _patch_dr(registry):
            await async_call_action_from_config(hass, config, {}, None)

        entry_data["coordinator"].async_request_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_noop_for_missing_entity(self):
        device = _make_device(identifiers={("erg", "switch.missing")})
        registry = _make_registry(devices={DEVICE_ID: device})
        entry_data = _make_entry_data(job_entities={})
        hass = _make_hass(entry_data)

        config = {
            "device_id": DEVICE_ID,
            "type": "set_force",
            "value": True,
        }
        with _patch_dr(registry):
            await async_call_action_from_config(hass, config, {}, None)

        entry_data["coordinator"].async_request_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_refreshes_coordinator(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": ENTITY_ID,
            "enabled": True,
        })
        entity.async_write_ha_state = MagicMock()

        device = _make_device(identifiers={("erg", ENTITY_ID)})
        registry = _make_registry(devices={DEVICE_ID: device})
        entry_data = _make_entry_data(job_entities={ENTITY_ID: entity})
        hass = _make_hass(entry_data)

        config = {
            "device_id": DEVICE_ID,
            "type": "set_enabled",
            "value": False,
        }
        with _patch_dr(registry):
            await async_call_action_from_config(hass, config, {}, None)

        entry_data["coordinator"].async_request_refresh.assert_awaited_once()
