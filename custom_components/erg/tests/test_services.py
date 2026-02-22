"""Tests for services.py — Erg job service handlers."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.services import (
    async_handle_create_job,
    async_handle_update_job,
    async_handle_delete_job,
    create_job_entity,
    delete_job_entity,
    _find_entry_data,
    async_register_services,
    async_unregister_services,
)
from custom_components.erg.job_entities import ErgJobEntity


ENTRY_ID = "test_entry_123"


def _make_mock_entry(subentries=None):
    """Create a mock config entry with a real subentries dict."""
    entry = MagicMock()
    entry.entry_id = ENTRY_ID
    entry.subentries = subentries if subentries is not None else {}
    return entry


def _make_hass(entry_data=None, mock_entry=None):
    """Create a mock hass object with erg domain data."""
    hass = MagicMock()
    hass.data = {"erg": {ENTRY_ID: entry_data or {}}}
    if mock_entry is None:
        mock_entry = _make_mock_entry()
    hass.config_entries.async_get_entry = MagicMock(return_value=mock_entry)
    hass.config_entries.async_add_subentry = MagicMock(return_value=True)
    hass.config_entries.async_remove_subentry = MagicMock(return_value=True)
    return hass


def _make_entry_data(**overrides):
    """Create a standard entry_data dict."""
    coordinator = MagicMock()
    coordinator.async_request_refresh = AsyncMock()
    data = {
        "coordinator": coordinator,
        "job_entities": {},
        "add_job_sensors": MagicMock(),
        "add_per_job_sensors": MagicMock(),
        "add_job_binary_sensors": MagicMock(),
        "per_job_sensors": {},
        "per_job_binary_sensors": {},
        "entry_options": {},
    }
    data.update(overrides)
    return data


def _make_call(data):
    """Create a mock service call."""
    call = MagicMock()
    call.data = data
    return call


class TestFindEntryData:
    def test_finds_entry_with_coordinator(self):
        entry_data = {"coordinator": MagicMock()}
        hass = _make_hass(entry_data)
        eid, data = _find_entry_data(hass)
        assert eid == ENTRY_ID
        assert data is entry_data

    def test_raises_when_no_entry(self):
        hass = MagicMock()
        hass.data = {"erg": {}}
        with pytest.raises(ValueError, match="No Erg config entry found"):
            _find_entry_data(hass)

    def test_raises_when_no_domain(self):
        hass = MagicMock()
        hass.data = {}
        with pytest.raises(ValueError, match="No Erg config entry found"):
            _find_entry_data(hass)


class TestCreateJob:
    @pytest.mark.asyncio
    async def test_creates_job_entity(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.5,
        })

        await async_handle_create_job(hass, call)

        assert "switch.pool_pump" in entry_data["job_entities"]
        entity = entry_data["job_entities"]["switch.pool_pump"]
        assert isinstance(entity, ErgJobEntity)
        assert entity.extra_state_attributes["ac_power"] == 1.5
        entry_data["add_job_sensors"].assert_called_once()
        entry_data["coordinator"].async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_skips_duplicate_entity(self):
        existing_entity = MagicMock()
        entry_data = _make_entry_data(job_entities={"switch.pool_pump": existing_entity})
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        await async_handle_create_job(hass, call)

        # Should not have replaced or added
        assert entry_data["job_entities"]["switch.pool_pump"] is existing_entity
        entry_data["coordinator"].async_request_refresh.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_creates_per_job_sensors(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        await async_handle_create_job(hass, call)

        entry_data["add_per_job_sensors"].assert_called_once()
        sensors = entry_data["add_per_job_sensors"].call_args[0][0]
        assert len(sensors) == 3  # next_start, run_time, energy_cost

    @pytest.mark.asyncio
    async def test_creates_binary_sensor(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        await async_handle_create_job(hass, call)

        entry_data["add_job_binary_sensors"].assert_called_once()
        sensors = entry_data["add_job_binary_sensors"].call_args[0][0]
        assert len(sensors) == 1


class TestUpdateJob:
    @pytest.mark.asyncio
    async def test_updates_existing_entity(self):
        entity = ErgJobEntity(ENTRY_ID, {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.0,
        })
        # Stub async_write_ha_state since entity isn't added to HA
        entity.async_write_ha_state = MagicMock()

        entry_data = _make_entry_data(job_entities={"switch.pool_pump": entity})
        hass = _make_hass(entry_data)
        call = _make_call({
            "job_entity_id": "switch.pool_pump",
            "ac_power": 2.5,
            "force": True,
        })

        await async_handle_update_job(hass, call)

        assert entity.extra_state_attributes["ac_power"] == 2.5
        assert entity.extra_state_attributes["force"] is True
        # Original attributes preserved
        assert entity.extra_state_attributes["entity_id"] == "switch.pool_pump"
        entry_data["coordinator"].async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_update_nonexistent_entity_warns(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({
            "job_entity_id": "switch.missing",
            "ac_power": 2.5,
        })

        await async_handle_update_job(hass, call)

        entry_data["coordinator"].async_request_refresh.assert_not_awaited()


class TestDeleteJob:
    @pytest.mark.asyncio
    async def test_deletes_job_and_sensors(self):
        entity = MagicMock()
        entity.async_remove = AsyncMock()
        sensor1 = MagicMock()
        sensor1.async_remove = AsyncMock()
        sensor2 = MagicMock()
        sensor2.async_remove = AsyncMock()
        binary_sensor = MagicMock()
        binary_sensor.async_remove = AsyncMock()

        entry_data = _make_entry_data(
            job_entities={"switch.pool_pump": entity},
            per_job_sensors={"switch.pool_pump": [sensor1, sensor2]},
            per_job_binary_sensors={"switch.pool_pump": [binary_sensor]},
        )
        hass = _make_hass(entry_data)
        call = _make_call({"job_entity_id": "switch.pool_pump"})

        await async_handle_delete_job(hass, call)

        entity.async_remove.assert_awaited_once()
        sensor1.async_remove.assert_awaited_once()
        sensor2.async_remove.assert_awaited_once()
        binary_sensor.async_remove.assert_awaited_once()
        assert "switch.pool_pump" not in entry_data["job_entities"]
        assert "switch.pool_pump" not in entry_data["per_job_sensors"]
        assert "switch.pool_pump" not in entry_data["per_job_binary_sensors"]
        entry_data["coordinator"].async_request_refresh.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_delete_nonexistent_entity_warns(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({"job_entity_id": "switch.missing"})

        await async_handle_delete_job(hass, call)

        entry_data["coordinator"].async_request_refresh.assert_not_awaited()


class TestCreateJobEntity:
    def test_creates_and_registers(self):
        entry_data = _make_entry_data()
        attrs = {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.5,
        }
        result = create_job_entity(ENTRY_ID, entry_data, attrs)
        assert result is not None
        assert isinstance(result, ErgJobEntity)
        assert "switch.pool_pump" in entry_data["job_entities"]
        assert result.extra_state_attributes["ac_power"] == 1.5
        entry_data["add_job_sensors"].assert_called_once()
        entry_data["add_per_job_sensors"].assert_called_once()

    def test_returns_none_for_duplicate(self):
        existing = MagicMock()
        entry_data = _make_entry_data(job_entities={"switch.pool_pump": existing})
        attrs = {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        }
        result = create_job_entity(ENTRY_ID, entry_data, attrs)
        assert result is None
        # Original entity should be untouched
        assert entry_data["job_entities"]["switch.pool_pump"] is existing

    def test_passes_subentry_id_to_add_job_sensors(self):
        entry_data = _make_entry_data()
        attrs = {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        }
        result = create_job_entity(ENTRY_ID, entry_data, attrs, subentry_id="sub_abc")
        assert result is not None
        # Verify config_subentry_id kwarg passed to add_job_sensors callback
        entry_data["add_job_sensors"].assert_called_once()
        _, kwargs = entry_data["add_job_sensors"].call_args
        assert kwargs.get("config_subentry_id") == "sub_abc"

    def test_passes_subentry_id_to_per_job_sensor_callbacks(self):
        entry_data = _make_entry_data()
        attrs = {
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        }
        create_job_entity(ENTRY_ID, entry_data, attrs, subentry_id="sub_abc")
        # Verify config_subentry_id kwarg passed to add_per_job_sensors callback
        entry_data["add_per_job_sensors"].assert_called_once()
        _, kwargs = entry_data["add_per_job_sensors"].call_args
        assert kwargs.get("config_subentry_id") == "sub_abc"
        # Verify config_subentry_id kwarg passed to add_job_binary_sensors callback
        entry_data["add_job_binary_sensors"].assert_called_once()
        _, kwargs = entry_data["add_job_binary_sensors"].call_args
        assert kwargs.get("config_subentry_id") == "sub_abc"


class TestDeleteJobEntity:
    @pytest.mark.asyncio
    async def test_removes_everything(self):
        entity = MagicMock()
        entity.async_remove = AsyncMock()
        sensor1 = MagicMock()
        sensor1.async_remove = AsyncMock()
        binary_sensor = MagicMock()
        binary_sensor.async_remove = AsyncMock()

        entry_data = _make_entry_data(
            job_entities={"switch.pool_pump": entity},
            per_job_sensors={"switch.pool_pump": [sensor1]},
            per_job_binary_sensors={"switch.pool_pump": [binary_sensor]},
        )

        result = await delete_job_entity(entry_data, "switch.pool_pump")
        assert result is True
        entity.async_remove.assert_awaited_once()
        sensor1.async_remove.assert_awaited_once()
        binary_sensor.async_remove.assert_awaited_once()
        assert "switch.pool_pump" not in entry_data["job_entities"]

    @pytest.mark.asyncio
    async def test_returns_false_for_missing(self):
        entry_data = _make_entry_data()
        result = await delete_job_entity(entry_data, "switch.missing")
        assert result is False


class TestCreateJobSubentry:
    @pytest.mark.asyncio
    async def test_create_job_adds_subentry(self):
        mock_entry = _make_mock_entry()
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data, mock_entry=mock_entry)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
            "ac_power": 1.5,
        })

        await async_handle_create_job(hass, call)

        hass.config_entries.async_get_entry.assert_called_once_with(ENTRY_ID)
        hass.config_entries.async_add_subentry.assert_called_once()
        _, args, _ = hass.config_entries.async_add_subentry.mock_calls[0]
        added_entry, subentry = args
        assert added_entry is mock_entry
        assert subentry.subentry_type == "job"
        assert subentry.title == "switch.pool_pump"
        assert subentry.unique_id == "switch.pool_pump"
        assert subentry.data["entity_id"] == "switch.pool_pump"
        assert subentry.data["ac_power"] == 1.5

    @pytest.mark.asyncio
    async def test_create_job_tracks_subentry_jobs(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        await async_handle_create_job(hass, call)

        assert "switch.pool_pump" in entry_data["_subentry_jobs"]

    @pytest.mark.asyncio
    async def test_create_job_passes_subentry_id_to_callbacks(self):
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        await async_handle_create_job(hass, call)

        # Get the subentry_id that was created
        _, args, _ = hass.config_entries.async_add_subentry.mock_calls[0]
        subentry = args[1]
        sid = subentry.subentry_id

        # Verify config_subentry_id kwarg passed to add_job_sensors
        _, kwargs = entry_data["add_job_sensors"].call_args
        assert kwargs.get("config_subentry_id") == sid

        # Verify config_subentry_id kwarg passed to add_per_job_sensors
        _, kwargs = entry_data["add_per_job_sensors"].call_args
        assert kwargs.get("config_subentry_id") == sid

    @pytest.mark.asyncio
    async def test_duplicate_does_not_add_subentry(self):
        existing_entity = MagicMock()
        entry_data = _make_entry_data(job_entities={"switch.pool_pump": existing_entity})
        hass = _make_hass(entry_data)
        call = _make_call({
            "entity_id": "switch.pool_pump",
            "job_type": "recurring",
        })

        await async_handle_create_job(hass, call)

        hass.config_entries.async_add_subentry.assert_not_called()


class TestDeleteJobSubentry:
    @pytest.mark.asyncio
    async def test_delete_job_removes_subentry(self):
        sub = MagicMock()
        sub.subentry_id = "sub_123"
        sub.data = {"entity_id": "switch.pool_pump"}
        mock_entry = _make_mock_entry(subentries={"sub_123": sub})

        entity = MagicMock()
        entity.async_remove = AsyncMock()
        entry_data = _make_entry_data(
            job_entities={"switch.pool_pump": entity},
            _subentry_jobs={"switch.pool_pump"},
        )
        hass = _make_hass(entry_data, mock_entry=mock_entry)
        call = _make_call({"job_entity_id": "switch.pool_pump"})

        await async_handle_delete_job(hass, call)

        hass.config_entries.async_remove_subentry.assert_called_once_with(
            mock_entry, "sub_123"
        )
        assert "switch.pool_pump" not in entry_data["_subentry_jobs"]

    @pytest.mark.asyncio
    async def test_delete_nonexistent_does_not_touch_subentries(self):
        mock_entry = _make_mock_entry()
        entry_data = _make_entry_data()
        hass = _make_hass(entry_data, mock_entry=mock_entry)
        call = _make_call({"job_entity_id": "switch.missing"})

        await async_handle_delete_job(hass, call)

        hass.config_entries.async_remove_subentry.assert_not_called()

    @pytest.mark.asyncio
    async def test_delete_job_with_no_matching_subentry(self):
        """Delete succeeds even if no sub-entry matches (legacy job)."""
        mock_entry = _make_mock_entry(subentries={})

        entity = MagicMock()
        entity.async_remove = AsyncMock()
        entry_data = _make_entry_data(job_entities={"switch.pool_pump": entity})
        hass = _make_hass(entry_data, mock_entry=mock_entry)
        call = _make_call({"job_entity_id": "switch.pool_pump"})

        await async_handle_delete_job(hass, call)

        hass.config_entries.async_remove_subentry.assert_not_called()
        entry_data["coordinator"].async_request_refresh.assert_awaited_once()


class TestServiceRegistration:
    def test_register_services(self):
        hass = MagicMock()
        async_register_services(hass)
        assert hass.services.async_register.call_count == 3

    def test_unregister_services(self):
        hass = MagicMock()
        async_unregister_services(hass)
        assert hass.services.async_remove.call_count == 3
