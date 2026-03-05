"""Polling utilities for waiting on HA entity state changes."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from .ha_client import HAClient

_LOGGER = logging.getLogger(__name__)


async def wait_for_state(
    client: HAClient,
    entity_id: str,
    expected_state: str,
    timeout: float = 30,
    interval: float = 0.5,
) -> dict:
    """Wait until entity reaches expected state. Returns the state dict."""
    deadline = asyncio.get_event_loop().time() + timeout
    last_state = None
    while asyncio.get_event_loop().time() < deadline:
        state = await client.get_state(entity_id)
        if state is not None:
            last_state = state.get("state")
            if last_state == expected_state:
                return state
        await asyncio.sleep(interval)
    raise TimeoutError(
        f"Entity {entity_id} did not reach state '{expected_state}' within {timeout}s. "
        f"Last state: {last_state}"
    )


async def wait_for_entity_exists(
    client: HAClient,
    entity_id: str,
    timeout: float = 30,
    interval: float = 0.5,
) -> dict:
    """Wait until entity exists in HA. Returns the state dict."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        state = await client.get_state(entity_id)
        if state is not None:
            return state
        await asyncio.sleep(interval)
    raise TimeoutError(f"Entity {entity_id} did not appear within {timeout}s")


async def wait_for_entities(
    client: HAClient,
    entity_ids: list[str],
    timeout: float = 30,
    interval: float = 0.5,
) -> list[dict]:
    """Wait until all entities exist. Returns list of state dicts."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        states = await client.get_states()
        found_ids = {s["entity_id"] for s in states}
        if all(eid in found_ids for eid in entity_ids):
            return [s for s in states if s["entity_id"] in entity_ids]
        await asyncio.sleep(interval)
    missing = [eid for eid in entity_ids if eid not in found_ids]
    raise TimeoutError(
        f"Entities did not appear within {timeout}s. Missing: {missing}"
    )


async def wait_for_attribute(
    client: HAClient,
    entity_id: str,
    attribute: str,
    expected_value: Any,
    timeout: float = 30,
    interval: float = 0.5,
) -> dict:
    """Wait until entity attribute matches expected value. Returns the state dict."""
    deadline = asyncio.get_event_loop().time() + timeout
    last_value = None
    while asyncio.get_event_loop().time() < deadline:
        state = await client.get_state(entity_id)
        if state is not None:
            attrs = state.get("attributes", {})
            last_value = attrs.get(attribute)
            if last_value == expected_value:
                return state
        await asyncio.sleep(interval)
    raise TimeoutError(
        f"Entity {entity_id} attribute '{attribute}' did not reach '{expected_value}' "
        f"within {timeout}s. Last value: {last_value}"
    )


async def trigger_refresh_and_wait(
    client: HAClient,
    timeout: float = 30,
    interval: float = 0.5,
) -> None:
    """Press button.erg_solve_now and wait for solve_status to be 'ok'."""
    # Find the solve_now button entity
    states = await client.get_states()
    solve_now = None
    for s in states:
        if s["entity_id"].startswith("button.") and "solve_now" in s["entity_id"]:
            solve_now = s["entity_id"]
            break

    if solve_now is None:
        raise RuntimeError("Could not find button.erg_solve_now entity")

    await client.call_service("button", "press", target={"entity_id": solve_now})

    # Wait for solve status to update
    solve_status = None
    for s in states:
        if s["entity_id"].startswith("sensor.") and "solve_status" in s["entity_id"]:
            solve_status = s["entity_id"]
            break

    if solve_status is None:
        raise RuntimeError("Could not find solve_status sensor entity")

    await wait_for_state(client, solve_status, "ok", timeout=timeout, interval=interval)
