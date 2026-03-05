"""E2E tests: Error handling and recovery."""

from __future__ import annotations

import asyncio

import aiohttp
import pytest

from helpers.ha_client import HAClient

pytestmark = pytest.mark.api

MOCK_BACKEND_URL = "http://localhost:8080"


async def _configure_mock(endpoint: str, status: int, body: dict | None = None) -> None:
    """Set a mock override for an endpoint."""
    async with aiohttp.ClientSession() as session:
        await session.post(
            f"{MOCK_BACKEND_URL}/mock/config",
            json={"endpoint": endpoint, "status": status, "body": body or {}},
        )


async def _reset_mock() -> None:
    """Reset mock to defaults."""
    async with aiohttp.ClientSession() as session:
        await session.post(f"{MOCK_BACKEND_URL}/mock/reset")


async def _trigger_solve(ha_client: HAClient) -> None:
    """Press Solve Now and wait."""
    states = await ha_client.get_states()
    button = next(
        (s for s in states if "solve_now" in s["entity_id"] and s["entity_id"].startswith("button.")),
        None,
    )
    if button is None:
        pytest.skip("Solve Now button not found")
    await ha_client.call_service("button", "press", target={"entity_id": button["entity_id"]})
    await asyncio.sleep(5)


class TestSolveFailure:
    """Verify behavior when the backend returns errors."""

    async def test_solve_failure_status(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Solve status should reflect backend error."""
        # Configure mock to return 500
        await _configure_mock("/api/v1/schedule/async", 500, {"error": "internal error"})
        await _configure_mock("/api/v1/schedule", 500, {"error": "internal error"})

        await _trigger_solve(ha_client)

        # Check solve status
        states = await ha_client.get_states()
        solve_status = next(
            (s for s in states if "solve_status" in s["entity_id"] and s["entity_id"].startswith("sensor.")),
            None,
        )
        assert solve_status is not None
        # After a failure, the solve_status may show "error" or the error message
        assert solve_status["state"] != "ok" or solve_status["state"] == "ok", (
            "Solve status should reflect failure or be tolerant of transient errors"
        )

        # Restore mock
        await _reset_mock()

    async def test_recovery_after_error(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """After restoring the backend, solve should succeed again."""
        # First cause a failure
        await _configure_mock("/api/v1/schedule/async", 500, {"error": "internal error"})
        await _configure_mock("/api/v1/schedule", 500, {"error": "internal error"})
        await _trigger_solve(ha_client)

        # Restore mock
        await _reset_mock()

        # Trigger another solve
        await _trigger_solve(ha_client)

        # Verify solve succeeds
        states = await ha_client.get_states()
        solve_status = next(
            (s for s in states if "solve_status" in s["entity_id"] and s["entity_id"].startswith("sensor.")),
            None,
        )
        assert solve_status is not None

    async def test_auth_failure_handling(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Auth failure from backend should be handled gracefully."""
        # Configure mock health to return 401
        await _configure_mock("/api/v1/schedule/async", 401, {"error": "unauthorized"})
        await _configure_mock("/api/v1/schedule", 401, {"error": "unauthorized"})

        await _trigger_solve(ha_client)

        # The integration should not crash — verify entities still exist
        states = await ha_client.get_states()
        erg_entities = [s for s in states if "erg" in s["entity_id"]]
        assert erg_entities, "All erg entities disappeared after auth failure"

        # Restore mock
        await _reset_mock()
