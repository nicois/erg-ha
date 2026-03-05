"""Failure artifact capture for E2E tests.

On test failure, captures screenshots, entity state dumps, HA logs,
and mock request logs into the artifacts/ directory.
"""

from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

import aiohttp
import pytest

_LOGGER = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).parent.parent / "artifacts"
MOCK_BACKEND_URL = "http://localhost:8080"
COMPOSE_FILE = Path(__file__).parent.parent / "docker-compose.yml"


def _safe_name(nodeid: str) -> str:
    """Convert a pytest nodeid into a filesystem-safe name."""
    return nodeid.replace("/", "_").replace("::", "__").replace(" ", "_")


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    """Capture artifacts on test failure."""
    outcome = yield
    report = outcome.get_result()

    if report.when != "call" or not report.failed:
        return

    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    test_name = _safe_name(item.nodeid)

    # Screenshot (if Playwright page fixture exists)
    page = item.funcargs.get("page")
    if page is not None:
        try:
            screenshot_path = ARTIFACTS_DIR / f"{test_name}.png"
            # page.screenshot is sync in the pytest context via sync wrapper
            import asyncio
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We're in an async context; schedule the screenshot
                import concurrent.futures
                with concurrent.futures.ThreadPoolExecutor() as pool:
                    pool.submit(_sync_screenshot, page, screenshot_path).result(timeout=10)
            else:
                loop.run_until_complete(page.screenshot(path=str(screenshot_path)))
            _LOGGER.info("Screenshot saved: %s", screenshot_path)
        except Exception as exc:
            _LOGGER.warning("Failed to capture screenshot: %s", exc)

    # Entity state dump
    ha_client = item.funcargs.get("ha_client")
    if ha_client is not None:
        try:
            import asyncio
            states = asyncio.get_event_loop().run_until_complete(ha_client.get_states())
            states_path = ARTIFACTS_DIR / f"{test_name}_states.json"
            states_path.write_text(json.dumps(states, indent=2, default=str))
            _LOGGER.info("States dump saved: %s", states_path)
        except Exception as exc:
            _LOGGER.warning("Failed to capture states: %s", exc)

    # HA container logs
    try:
        result = subprocess.run(
            ["podman", "compose", "-f", str(COMPOSE_FILE), "logs", "homeassistant", "--tail=500"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        log_path = ARTIFACTS_DIR / f"{test_name}_ha.log"
        log_path.write_text(result.stdout + result.stderr)
        _LOGGER.info("HA logs saved: %s", log_path)
    except Exception as exc:
        _LOGGER.warning("Failed to capture HA logs: %s", exc)

    # Mock request log
    try:
        import asyncio
        requests_data = asyncio.get_event_loop().run_until_complete(_fetch_mock_requests())
        requests_path = ARTIFACTS_DIR / f"{test_name}_requests.json"
        requests_path.write_text(json.dumps(requests_data, indent=2, default=str))
        _LOGGER.info("Mock requests saved: %s", requests_path)
    except Exception as exc:
        _LOGGER.warning("Failed to capture mock requests: %s", exc)


def _sync_screenshot(page, path):
    """Take a screenshot synchronously."""
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(page.screenshot(path=str(path)))
    finally:
        loop.close()


async def _fetch_mock_requests() -> list:
    """Fetch recorded requests from the mock backend."""
    async with aiohttp.ClientSession() as session:
        async with session.get(f"{MOCK_BACKEND_URL}/mock/requests") as resp:
            if resp.status == 200:
                return await resp.json()
            return []
