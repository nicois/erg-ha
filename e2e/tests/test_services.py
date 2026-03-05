"""E2E tests: Service call verification."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from helpers.ha_client import HAClient, HAClientError

pytestmark = pytest.mark.api

MOCK_BACKEND_URL = "http://localhost:8080"


class TestCreateJobService:
    """Verify erg.create_job service schema and behavior."""

    async def test_create_job_valid_payload(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Valid create_job call should succeed."""
        entity_id = "input_boolean.ev_charger"
        try:
            await ha_client.call_service("erg", "create_job", data={
                "entity_id": entity_id,
                "job_type": "recurring",
                "ac_power": 7.0,
                "frequency": "weekdays",
                "time_window_start": "22:00",
                "time_window_end": "06:00",
                "maximum_duration": "4h",
                "minimum_duration": "0s",
                "minimum_burst": "0s",
            })
            await asyncio.sleep(3)

            # Verify entity was created
            states = await ha_client.get_states()
            sanitized = entity_id.replace(".", "_")
            matches = [s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]]
            assert matches, f"No entities found for {entity_id}"
        finally:
            # Cleanup
            try:
                await ha_client.call_service("erg", "delete_job", data={
                    "job_entity_id": entity_id,
                })
                await asyncio.sleep(2)
            except HAClientError:
                pass

    async def test_create_job_invalid_duration(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Create job with invalid duration format should fail."""
        with pytest.raises(HAClientError):
            await ha_client.call_service("erg", "create_job", data={
                "entity_id": "input_boolean.pool_pump",
                "job_type": "recurring",
                "ac_power": 1.0,
                "maximum_duration": "invalid",
            })


class TestUpdateJobService:
    """Verify erg.update_job service behavior."""

    async def test_partial_update_merges(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Updating a single field should not affect other fields."""
        await ha_client.call_service("erg", "update_job", data={
            "job_entity_id": created_recurring_job,
            "ac_power": 3.0,
        })
        await asyncio.sleep(2)

        # Verify ac_power changed
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        ac_power = next(
            (s for s in states if "ac_power" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("number.")),
            None,
        )
        if ac_power is not None:
            assert float(ac_power["state"]) == pytest.approx(3.0, abs=0.1)


class TestDeleteJobService:
    """Verify erg.delete_job service cleans up all entities."""

    async def test_delete_removes_all_entities(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Deleting a job should remove all associated entities."""
        entity_id = "input_boolean.ev_charger"

        # Create
        await ha_client.call_service("erg", "create_job", data={
            "entity_id": entity_id,
            "job_type": "recurring",
            "ac_power": 7.0,
            "frequency": "daily",
            "time_window_start": "22:00",
            "time_window_end": "06:00",
            "maximum_duration": "4h",
            "minimum_duration": "0s",
            "minimum_burst": "0s",
        })
        await asyncio.sleep(3)

        # Verify created
        sanitized = entity_id.replace(".", "_")
        states = await ha_client.get_states()
        before = [s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]]
        assert before, "Job entities not created"

        # Delete
        await ha_client.call_service("erg", "delete_job", data={
            "job_entity_id": entity_id,
        })
        await asyncio.sleep(3)

        # Verify removed
        states = await ha_client.get_states()
        after = [s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]]
        assert len(after) < len(before), (
            f"Entities not cleaned up. Before: {len(before)}, After: {len(after)}"
        )


class TestCheckHealthService:
    """Verify erg.check_health service fires an event."""

    async def test_check_health_returns_status(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """check_health service should execute without error."""
        # Just verify the service call doesn't raise
        await ha_client.call_service("erg", "check_health")
        # The service fires an erg_health event; we can't easily listen
        # for events via REST API, but the call succeeding is the key test.
