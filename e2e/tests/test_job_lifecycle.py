"""E2E tests: Job CRUD lifecycle (API + Playwright)."""

from __future__ import annotations

import asyncio

import pytest

from helpers.ha_client import HAClient, HAClientError

pytestmark = pytest.mark.api


class TestJobLifecycleAPI:
    """Verify job creation, update, and deletion via service calls."""

    async def test_create_recurring_job(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Creating a recurring job should produce all per-job entities."""
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
                "benefit": 0.5,
            })
            await asyncio.sleep(3)

            states = await ha_client.get_states()
            sanitized = entity_id.replace(".", "_")
            job_entities = [s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]]

            # Should have: job sensor, next_start, run_time, energy_cost,
            # binary_sensor (scheduled), switches (enabled, must_run),
            # numbers (ac_power, dc_power, benefit, etc.), selects (frequency),
            # texts (max_duration, etc.)
            assert len(job_entities) >= 3, (
                f"Expected at least 3 per-job entities, got {len(job_entities)}: "
                f"{[s['entity_id'] for s in job_entities]}"
            )

            # Check specific entity types exist
            entity_types = {s["entity_id"].split(".")[0] for s in job_entities}
            assert "sensor" in entity_types, "No sensor entities found for job"

        finally:
            try:
                await ha_client.call_service("erg", "delete_job", data={
                    "job_entity_id": entity_id,
                })
                await asyncio.sleep(2)
            except HAClientError:
                pass

    async def test_create_oneshot_job(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Creating a oneshot job should succeed."""
        entity_id = "input_boolean.water_heater"
        try:
            await ha_client.call_service("erg", "create_job", data={
                "entity_id": entity_id,
                "job_type": "oneshot",
                "ac_power": 2.0,
                "maximum_duration": "1h",
                "minimum_duration": "0s",
                "minimum_burst": "0s",
            })
            await asyncio.sleep(3)

            states = await ha_client.get_states()
            sanitized = entity_id.replace(".", "_")
            job_entities = [s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]]
            assert job_entities, f"No entities found for oneshot job {entity_id}"

        finally:
            try:
                await ha_client.call_service("erg", "delete_job", data={
                    "job_entity_id": entity_id,
                })
                await asyncio.sleep(2)
            except HAClientError:
                pass

    async def test_update_job(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Updating a job should modify entity attributes."""
        # Update ac_power
        await ha_client.call_service("erg", "update_job", data={
            "job_entity_id": created_recurring_job,
            "ac_power": 5.0,
            "benefit": 1.5,
        })
        await asyncio.sleep(2)

        # Check the number entity changed
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        ac_power = next(
            (s for s in states if "ac_power" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("number.")),
            None,
        )
        if ac_power is not None:
            assert float(ac_power["state"]) == pytest.approx(5.0, abs=0.1)

    async def test_delete_job(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Deleting a job should remove all its entities."""
        entity_id = "input_boolean.ev_charger"

        # Create
        await ha_client.call_service("erg", "create_job", data={
            "entity_id": entity_id,
            "job_type": "recurring",
            "ac_power": 7.0,
            "frequency": "daily",
            "time_window_start": "09:00",
            "time_window_end": "17:00",
            "maximum_duration": "2h",
            "minimum_duration": "0s",
            "minimum_burst": "0s",
        })
        await asyncio.sleep(3)

        sanitized = entity_id.replace(".", "_")
        states = await ha_client.get_states()
        before_count = len([s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]])
        assert before_count > 0, "Job was not created"

        # Delete
        await ha_client.call_service("erg", "delete_job", data={
            "job_entity_id": entity_id,
        })
        await asyncio.sleep(3)

        states = await ha_client.get_states()
        after_count = len([s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]])
        assert after_count < before_count, (
            f"Entities not removed after delete. Before: {before_count}, After: {after_count}"
        )

    async def test_duplicate_job_rejected(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Creating a job for an entity that already has one should not duplicate."""
        # Try to create a second job for the same entity
        await ha_client.call_service("erg", "create_job", data={
            "entity_id": created_recurring_job,
            "job_type": "recurring",
            "ac_power": 1.0,
            "frequency": "daily",
            "time_window_start": "09:00",
            "time_window_end": "17:00",
            "maximum_duration": "1h",
            "minimum_duration": "0s",
            "minimum_burst": "0s",
        })
        await asyncio.sleep(2)

        # Count entities — should not have duplicated
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        job_sensors = [
            s for s in states
            if sanitized in s["entity_id"]
            and "erg" in s["entity_id"]
            and s["entity_id"].startswith("sensor.")
            and "job" in s["entity_id"]
            and "next_start" not in s["entity_id"]
            and "run_time" not in s["entity_id"]
            and "energy_cost" not in s["entity_id"]
        ]
        # There should be at most 1 main job entity
        assert len(job_sensors) <= 1, (
            f"Duplicate job entities found: {[s['entity_id'] for s in job_sensors]}"
        )

    async def test_create_multiple_jobs(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Multiple jobs for different entities should coexist."""
        entities = ["input_boolean.pool_pump", "input_boolean.ev_charger"]
        try:
            for entity_id in entities:
                await ha_client.call_service("erg", "create_job", data={
                    "entity_id": entity_id,
                    "job_type": "recurring",
                    "ac_power": 1.0,
                    "frequency": "daily",
                    "time_window_start": "09:00",
                    "time_window_end": "17:00",
                    "maximum_duration": "1h",
                    "minimum_duration": "0s",
                    "minimum_burst": "0s",
                })
                await asyncio.sleep(2)

            states = await ha_client.get_states()
            for entity_id in entities:
                sanitized = entity_id.replace(".", "_")
                matches = [s for s in states if sanitized in s["entity_id"] and "erg" in s["entity_id"]]
                assert matches, f"No entities for {entity_id}"

        finally:
            for entity_id in entities:
                try:
                    await ha_client.call_service("erg", "delete_job", data={
                        "job_entity_id": entity_id,
                    })
                    await asyncio.sleep(1)
                except HAClientError:
                    pass
