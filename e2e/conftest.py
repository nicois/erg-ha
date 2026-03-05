"""E2E test fixtures for the erg-ha integration.

Session-scoped: Podman services, HA onboarding, client, config entry, browser.
Function-scoped: page, mock reset, job creation/cleanup.
"""

from __future__ import annotations

import asyncio
import logging
import subprocess
import time
from pathlib import Path
from typing import AsyncGenerator, Generator

import aiohttp
import pytest
import pytest_asyncio

from helpers.ha_bootstrap import onboard_and_get_token
from helpers.ha_client import HAClient, HAClientError
from helpers.wait import wait_for_entity_exists, wait_for_entities

_LOGGER = logging.getLogger(__name__)

E2E_DIR = Path(__file__).parent
COMPOSE_FILE = E2E_DIR / "docker-compose.yml"
MOCK_BACKEND_URL = "http://localhost:8080"
HA_URL = "http://localhost:8123"


# -- Debug artifact hooks (from helpers/debug.py) --

from helpers.debug import pytest_runtest_makereport  # noqa: F401, E402


# =============================================================================
# Session-scoped fixtures
# =============================================================================


@pytest.fixture(scope="session")
def podman_services():
    """Start Podman Compose services and tear down after all tests."""
    _LOGGER.info("Starting Podman Compose services...")
    subprocess.run(
        ["podman", "compose", "-f", str(COMPOSE_FILE), "up", "-d", "--build"],
        check=True,
        capture_output=True,
        text=True,
    )

    # Wait for mock-backend health
    _wait_for_url(f"{MOCK_BACKEND_URL}/api/v1/health", timeout=30)

    yield

    _LOGGER.info("Tearing down Podman Compose services...")
    subprocess.run(
        ["podman", "compose", "-f", str(COMPOSE_FILE), "down", "-v"],
        check=True,
        capture_output=True,
        text=True,
    )


@pytest.fixture(scope="session")
def ha_token(podman_services) -> str:
    """Bootstrap HA onboarding and return a long-lived access token."""
    loop = asyncio.new_event_loop()
    try:
        token = loop.run_until_complete(onboard_and_get_token(timeout=120))
        return token
    finally:
        loop.close()


@pytest_asyncio.fixture(scope="session")
async def ha_client(ha_token: str) -> AsyncGenerator[HAClient, None]:
    """Session-scoped HA REST API client."""
    client = HAClient(HA_URL, ha_token)
    yield client
    await client.close()


@pytest_asyncio.fixture(scope="session")
async def config_entry_id(ha_client: HAClient) -> str:
    """Create the erg config entry via the config flow API.

    Uses mock-backend as the host (Docker network name visible to HA).
    Waits for global entities to appear before returning.
    """
    # Start config flow
    flow = await ha_client.init_config_flow("erg")
    flow_id = flow["flow_id"]

    # Submit connection details — HA container uses "mock-backend" hostname
    result = await ha_client.configure_flow(flow_id, {
        "host": "mock-backend",
        "port": 8080,
        "use_ssl": False,
        "api_token": "test-token",
    })

    # The flow should complete and create an entry
    entry_id = result.get("result", {}).get("entry_id")
    if not entry_id:
        # Maybe result is the entry directly
        entry_id = result.get("entry_id")

    if not entry_id:
        # Try to find it from config entries
        entries = await ha_client.get_config_entries()
        for entry in entries:
            if entry.get("domain") == "erg":
                entry_id = entry["entry_id"]
                break

    assert entry_id, f"Failed to create erg config entry. Flow result: {result}"

    # Wait for global entities to appear (solve_status is a good indicator)
    await _wait_for_global_entities(ha_client)

    return entry_id


@pytest.fixture(scope="session")
def browser():
    """Launch a Playwright browser (headless Chromium)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed")
        return

    pw = sync_playwright().start()
    browser = pw.chromium.launch(headless=True)
    yield browser
    browser.close()
    pw.stop()


# =============================================================================
# Function-scoped fixtures
# =============================================================================


@pytest.fixture(autouse=True)
def mock_reset():
    """Reset mock backend state before each test."""
    import requests
    try:
        requests.post(f"{MOCK_BACKEND_URL}/mock/reset", timeout=5)
    except Exception:
        # If mock backend isn't up, skip silently — podman_services fixture
        # will handle the actual failure
        pass


@pytest.fixture
def page(browser, ha_token: str):
    """Create a new browser page with HA auth for each test."""
    context = browser.new_context(
        viewport={"width": 1280, "height": 720},
        ignore_https_errors=True,
    )
    page = context.new_page()

    # Navigate to HA and inject auth
    page.goto(f"{HA_URL}/")
    page.wait_for_load_state("networkidle")

    # Set auth token in localStorage (HA stores auth this way)
    page.evaluate(f"""() => {{
        window.localStorage.setItem('hassTokens', JSON.stringify({{
            hassUrl: '{HA_URL}',
            access_token: '{ha_token}',
            token_type: 'Bearer',
            expires_in: 86400,
            expires: Date.now() + 86400000,
        }}));
    }}""")

    # Reload to apply auth
    page.goto(f"{HA_URL}/")
    page.wait_for_load_state("networkidle")

    yield page

    context.close()


@pytest_asyncio.fixture
async def created_recurring_job(
    ha_client: HAClient, config_entry_id: str
) -> AsyncGenerator[str, None]:
    """Create a pool_pump recurring job, yield the entity_id, then delete."""
    entity_id = "input_boolean.pool_pump"

    await ha_client.call_service("erg", "create_job", data={
        "entity_id": entity_id,
        "job_type": "recurring",
        "ac_power": 1.5,
        "frequency": "daily",
        "time_window_start": "09:00",
        "time_window_end": "17:00",
        "maximum_duration": "2h",
        "minimum_duration": "0s",
        "minimum_burst": "0s",
    })

    # Wait for the job entity to appear
    await _wait_for_job_entities(ha_client, entity_id, timeout=30)

    yield entity_id

    # Cleanup: delete the job
    try:
        await ha_client.call_service("erg", "delete_job", data={
            "job_entity_id": entity_id,
        })
        await asyncio.sleep(2)
    except HAClientError:
        pass


@pytest_asyncio.fixture
async def created_oneshot_job(
    ha_client: HAClient, config_entry_id: str
) -> AsyncGenerator[str, None]:
    """Create a water_heater oneshot job, yield the entity_id, then delete."""
    entity_id = "input_boolean.water_heater"

    await ha_client.call_service("erg", "create_job", data={
        "entity_id": entity_id,
        "job_type": "oneshot",
        "ac_power": 2.0,
        "maximum_duration": "1h",
        "minimum_duration": "0s",
        "minimum_burst": "0s",
    })

    await _wait_for_job_entities(ha_client, entity_id, timeout=30)

    yield entity_id

    try:
        await ha_client.call_service("erg", "delete_job", data={
            "job_entity_id": entity_id,
        })
        await asyncio.sleep(2)
    except HAClientError:
        pass


# =============================================================================
# Helpers
# =============================================================================


def _wait_for_url(url: str, timeout: float = 30) -> None:
    """Synchronously poll a URL until it responds 200."""
    import requests
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                return
        except Exception:
            pass
        time.sleep(1)
    raise TimeoutError(f"URL {url} did not become available within {timeout}s")


async def _wait_for_global_entities(client: HAClient, timeout: float = 60) -> None:
    """Wait for key global erg entities to appear in HA."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        states = await client.get_states()
        entity_ids = {s["entity_id"] for s in states}
        # Check for solve_status sensor as indicator
        erg_entities = [eid for eid in entity_ids if "erg" in eid]
        if any("solve_status" in eid for eid in erg_entities):
            _LOGGER.info("Global erg entities found: %s", erg_entities)
            return
        await asyncio.sleep(2)
    raise TimeoutError(f"Global erg entities did not appear within {timeout}s")


async def _wait_for_job_entities(
    client: HAClient, entity_id: str, timeout: float = 30
) -> None:
    """Wait for per-job entities to appear after job creation."""
    sanitized = entity_id.replace(".", "_")
    # The main job sensor has entity_id pattern sensor.erg_job_{sanitized}
    # but HA entity registry may use different patterns. Just look for the entity
    # in the states that contains the sanitized name.
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        states = await client.get_states()
        entity_ids = {s["entity_id"] for s in states}
        # Look for the main job entity or any per-job sensor
        matches = [eid for eid in entity_ids if sanitized in eid and "erg" in eid]
        if matches:
            _LOGGER.info("Job entities found for %s: %s", entity_id, matches)
            return
        await asyncio.sleep(1)
    raise TimeoutError(f"Job entities for {entity_id} did not appear within {timeout}s")
