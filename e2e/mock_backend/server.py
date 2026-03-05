"""Mock Erg Go backend server for E2E testing.

Implements all API endpoints the erg-ha integration calls, with canned
responses and request recording for test assertions.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from aiohttp import web

logging.basicConfig(level=logging.INFO)
_LOGGER = logging.getLogger("mock_backend")

RESPONSES_DIR = Path(__file__).parent / "responses"


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _replace_timestamps(obj: Any) -> Any:
    """Replace __NOW__, __NOW+Xm__, and __NOW-Xm__ placeholders with real timestamps."""
    if isinstance(obj, str):
        now = _now()
        # __NOW+15m__, __NOW+30m__, etc.
        match = re.match(r"__NOW\+(\d+)m__", obj)
        if match:
            minutes = int(match.group(1))
            return (now + timedelta(minutes=minutes)).isoformat()
        # __NOW-15m__, __NOW-30m__, etc.
        match = re.match(r"__NOW-(\d+)m__", obj)
        if match:
            minutes = int(match.group(1))
            return (now - timedelta(minutes=minutes)).isoformat()
        if obj == "__NOW__":
            return now.isoformat()
        return obj
    if isinstance(obj, list):
        return [_replace_timestamps(item) for item in obj]
    if isinstance(obj, dict):
        return {k: _replace_timestamps(v) for k, v in obj.items()}
    return obj


def _load_response(name: str) -> dict:
    """Load a JSON response template and replace timestamp placeholders."""
    path = RESPONSES_DIR / name
    with open(path) as f:
        data = json.load(f)
    return _replace_timestamps(data)


class MockBackend:
    """In-memory state for the mock backend."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.overrides: dict[str, dict[str, Any]] = {}
        self.async_job_poll_counts: dict[str, int] = {}

    def record(self, method: str, path: str, headers: dict, body: Any = None) -> None:
        self.requests.append({
            "method": method,
            "path": path,
            "headers": {k: v for k, v in headers.items()},
            "body": body,
            "timestamp": _now().isoformat(),
        })

    def get_override(self, endpoint: str) -> dict[str, Any] | None:
        return self.overrides.get(endpoint)

    def reset(self) -> None:
        self.requests.clear()
        self.overrides.clear()
        self.async_job_poll_counts.clear()


state = MockBackend()


def _check_override(endpoint: str) -> web.Response | None:
    """Check if there's an override for this endpoint and return it."""
    override = state.get_override(endpoint)
    if override is None:
        return None
    status = override.get("status", 200)
    body = override.get("body", {})
    delay = override.get("delay", 0)
    # delay is handled at route level if needed; for now just return
    return web.json_response(body, status=status)


# --- API Routes ---


async def health(request: web.Request) -> web.Response:
    state.record("GET", "/api/v1/health", dict(request.headers))
    override = _check_override("/api/v1/health")
    if override:
        return override
    return web.json_response({"status": "ok"})


async def auth_providers(request: web.Request) -> web.Response:
    state.record("GET", "/api/v1/auth/providers", dict(request.headers))
    override = _check_override("/api/v1/auth/providers")
    if override:
        return override
    return web.json_response({"providers": []})


async def auth_login(request: web.Request) -> web.Response:
    state.record("GET", "/api/v1/auth/login", dict(request.headers))
    override = _check_override("/api/v1/auth/login")
    if override:
        return override
    return web.json_response({
        "login_url": "http://mock-backend:8080/mock/fake-oidc",
        "state": "mock-state-123",
        "expires_in": 300,
    })


async def auth_status(request: web.Request) -> web.Response:
    state.record("GET", "/api/v1/auth/status", dict(request.headers))
    override = _check_override("/api/v1/auth/status")
    if override:
        return override
    return web.json_response({
        "status": "complete",
        "session_token": "mock-session-token",
        "user": {"id": 1, "email": "test@example.com"},
    })


async def auth_me(request: web.Request) -> web.Response:
    state.record("GET", "/api/v1/auth/me", dict(request.headers))
    override = _check_override("/api/v1/auth/me")
    if override:
        return override
    return web.json_response({
        "id": 1,
        "email": "test@example.com",
        "quota": {"solves_remaining": 100, "solves_limit": 1000},
    })


async def keys_create(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else None
    state.record("POST", "/api/v1/keys", dict(request.headers), body)
    override = _check_override("/api/v1/keys")
    if override:
        return override
    return web.json_response({
        "id": 1,
        "token": "mock-api-key-from-server",
        "name": body.get("name", "test") if body else "test",
        "scope": body.get("scope", "schedule") if body else "schedule",
    })


async def keys_delete(request: web.Request) -> web.Response:
    key_id = request.match_info["id"]
    state.record("DELETE", f"/api/v1/keys/{key_id}", dict(request.headers))
    override = _check_override(f"/api/v1/keys/{key_id}")
    if override:
        return override
    return web.json_response({"deleted": True})


async def schedule_sync(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else None
    state.record("POST", "/api/v1/schedule", dict(request.headers), body)
    override = _check_override("/api/v1/schedule")
    if override:
        return override
    data = _load_response("schedule.json")
    return web.json_response(data)


async def schedule_async_submit(request: web.Request) -> web.Response:
    body = await request.json() if request.can_read_body else None
    state.record("POST", "/api/v1/schedule/async", dict(request.headers), body)
    override = _check_override("/api/v1/schedule/async")
    if override:
        return override
    data = _load_response("schedule_async_submit.json")
    return web.json_response(data, status=202)


async def schedule_job_status(request: web.Request) -> web.Response:
    job_id = request.match_info["id"]
    state.record("GET", f"/api/v1/schedule/jobs/{job_id}", dict(request.headers))
    override = _check_override(f"/api/v1/schedule/jobs/{job_id}")
    if override:
        return override

    # First call returns pending, subsequent calls return complete
    count = state.async_job_poll_counts.get(job_id, 0)
    state.async_job_poll_counts[job_id] = count + 1

    if count == 0:
        return web.json_response({
            "job_id": job_id,
            "status": "pending",
        })

    schedule_data = _load_response("schedule.json")
    return web.json_response({
        "job_id": job_id,
        "status": "complete",
        "result": schedule_data,
    })


async def aemo_tariff(request: web.Request) -> web.Response:
    region = request.query.get("region", "NSW1")
    state.record("GET", f"/api/v1/tariff/aemo?region={region}", dict(request.headers))
    override = _check_override("/api/v1/tariff/aemo")
    if override:
        return override
    data = _load_response("aemo_tariff.json")
    return web.json_response(data)


async def schedule_view(request: web.Request) -> web.Response:
    state.record("GET", "/api/v1/schedule/view", dict(request.headers))
    return web.Response(text="<html><body>Mock Schedule View</body></html>", content_type="text/html")


# --- Test Control Routes ---


async def mock_requests(request: web.Request) -> web.Response:
    return web.json_response(state.requests)


async def mock_config(request: web.Request) -> web.Response:
    body = await request.json()
    endpoint = body.get("endpoint")
    if not endpoint:
        return web.json_response({"error": "endpoint required"}, status=400)
    state.overrides[endpoint] = {
        "status": body.get("status", 200),
        "body": body.get("body", {}),
        "delay": body.get("delay", 0),
    }
    _LOGGER.info("Override set for %s: status=%s", endpoint, body.get("status", 200))
    return web.json_response({"ok": True})


async def mock_reset(request: web.Request) -> web.Response:
    state.reset()
    _LOGGER.info("Mock state reset")
    return web.json_response({"ok": True})


def create_app() -> web.Application:
    app = web.Application()

    # Erg API endpoints
    app.router.add_get("/api/v1/health", health)
    app.router.add_get("/api/v1/auth/providers", auth_providers)
    app.router.add_get("/api/v1/auth/login", auth_login)
    app.router.add_get("/api/v1/auth/status", auth_status)
    app.router.add_get("/api/v1/auth/me", auth_me)
    app.router.add_post("/api/v1/keys", keys_create)
    app.router.add_delete("/api/v1/keys/{id}", keys_delete)
    app.router.add_post("/api/v1/schedule", schedule_sync)
    app.router.add_post("/api/v1/schedule/async", schedule_async_submit)
    app.router.add_get("/api/v1/schedule/jobs/{id}", schedule_job_status)
    app.router.add_get("/api/v1/tariff/aemo", aemo_tariff)
    app.router.add_get("/api/v1/schedule/view", schedule_view)

    # Test control endpoints
    app.router.add_get("/mock/requests", mock_requests)
    app.router.add_post("/mock/config", mock_config)
    app.router.add_post("/mock/reset", mock_reset)

    return app


if __name__ == "__main__":
    port = int(os.environ.get("PORT", "8080"))
    app = create_app()
    _LOGGER.info("Starting mock backend on port %d", port)
    web.run_app(app, host="0.0.0.0", port=port)
