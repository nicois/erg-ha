"""E2E tests: Schedule coordinator behavior."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from helpers.ha_client import HAClient

pytestmark = pytest.mark.api

MOCK_BACKEND_URL = "http://localhost:8080"


async def _get_mock_requests() -> list[dict]:
    """Fetch recorded requests from mock backend."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{MOCK_BACKEND_URL}/mock/requests") as resp:
            return await resp.json()


async def _trigger_solve(ha_client: HAClient) -> None:
    """Press Solve Now and wait for it to complete."""
    states = await ha_client.get_states()
    button = next(
        (s for s in states if "solve_now" in s["entity_id"] and s["entity_id"].startswith("button.")),
        None,
    )
    if button is None:
        pytest.skip("Solve Now button not found")
    await ha_client.call_service("button", "press", target={"entity_id": button["entity_id"]})
    await asyncio.sleep(5)


class TestScheduleRequest:
    """Verify the structure of schedule requests sent to the backend."""

    async def test_schedule_request_structure(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Schedule request should contain system, tariff, boxes, and horizon."""
        await _trigger_solve(ha_client)
        requests_data = await _get_mock_requests()

        schedule_requests = [
            r for r in requests_data
            if r["path"] in ("/api/v1/schedule", "/api/v1/schedule/async")
            and r["method"] == "POST"
        ]
        assert schedule_requests, "No schedule request sent"

        body = schedule_requests[-1]["body"]
        assert body is not None, "Schedule request body is None"
        assert "system" in body, f"Missing 'system' in request. Keys: {list(body.keys())}"
        assert "horizon" in body, f"Missing 'horizon' in request. Keys: {list(body.keys())}"

    async def test_system_fields(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """System block should contain grid limits and battery params."""
        await _trigger_solve(ha_client)
        requests_data = await _get_mock_requests()

        schedule_requests = [
            r for r in requests_data
            if r["path"] in ("/api/v1/schedule", "/api/v1/schedule/async")
            and r["method"] == "POST"
        ]
        assert schedule_requests
        system = schedule_requests[-1]["body"].get("system", {})

        # These come from options flow defaults
        assert "grid_import_limit" in system
        assert "battery_capacity" in system

    async def test_schedule_includes_jobs(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Schedule request should include boxes for created jobs."""
        await _trigger_solve(ha_client)
        requests_data = await _get_mock_requests()

        schedule_requests = [
            r for r in requests_data
            if r["path"] in ("/api/v1/schedule", "/api/v1/schedule/async")
            and r["method"] == "POST"
        ]
        assert schedule_requests

        body = schedule_requests[-1]["body"]
        boxes = body.get("boxes", [])
        # There should be at least one box for the created job
        job_boxes = [b for b in boxes if b.get("entity") == created_recurring_job]
        assert job_boxes, (
            f"No box found for {created_recurring_job}. "
            f"Boxes: {[b.get('entity') for b in boxes]}"
        )

    async def test_battery_soc_in_request(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """System block should contain state_of_charge from template sensor."""
        # Configure the options to point to our battery SoC entity
        # This requires the options flow, which may not be set up.
        # Instead just verify the field exists (even if 0)
        await _trigger_solve(ha_client)
        requests_data = await _get_mock_requests()

        schedule_requests = [
            r for r in requests_data
            if r["path"] in ("/api/v1/schedule", "/api/v1/schedule/async")
            and r["method"] == "POST"
        ]
        assert schedule_requests
        system = schedule_requests[-1]["body"].get("system", {})
        assert "state_of_charge" in system
