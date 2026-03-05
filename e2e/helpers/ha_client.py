"""Async HTTP wrapper for the Home Assistant REST API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class HAClientError(Exception):
    """Error from HA REST API."""

    def __init__(self, status: int, body: str, url: str = "") -> None:
        self.status = status
        self.body = body
        self.url = url
        super().__init__(f"HTTP {status} from {url}: {body}")


class HAClient:
    """Async client for the Home Assistant REST API."""

    def __init__(self, base_url: str, token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self._session: aiohttp.ClientSession | None = None

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json",
        }

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def _request(
        self,
        method: str,
        path: str,
        json: Any = None,
        params: dict | None = None,
    ) -> Any:
        session = await self._ensure_session()
        url = f"{self.base_url}{path}"
        async with session.request(
            method,
            url,
            headers=self._headers(),
            json=json,
            params=params,
        ) as resp:
            body = await resp.text()
            if resp.status >= 400:
                raise HAClientError(resp.status, body, url)
            if not body:
                return None
            return await resp.json(content_type=None) if body else None

    async def get_states(self) -> list[dict]:
        """Get all entity states."""
        return await self._request("GET", "/api/states")

    async def get_state(self, entity_id: str) -> dict | None:
        """Get state of a specific entity. Returns None if not found."""
        try:
            return await self._request("GET", f"/api/states/{entity_id}")
        except HAClientError as err:
            if err.status == 404:
                return None
            raise

    async def call_service(
        self,
        domain: str,
        service: str,
        data: dict | None = None,
        target: dict | None = None,
    ) -> list[dict]:
        """Call a Home Assistant service."""
        payload = {}
        if data:
            payload.update(data)
        if target:
            payload["target"] = target
        return await self._request("POST", f"/api/services/{domain}/{service}", json=payload)

    async def get_config_entries(self) -> list[dict]:
        """Get all config entries."""
        return await self._request("GET", "/api/config/config_entries/entry")

    async def init_config_flow(self, handler: str) -> dict:
        """Initialize a config flow for a given handler."""
        return await self._request(
            "POST",
            "/api/config/config_entries/flow",
            json={"handler": handler},
        )

    async def configure_flow(self, flow_id: str, data: dict) -> dict:
        """Submit data to a config flow step."""
        return await self._request(
            "POST",
            f"/api/config/config_entries/flow/{flow_id}",
            json=data,
        )

    async def get_config_entry_options_flow(self, entry_id: str) -> dict:
        """Start an options flow for a config entry."""
        return await self._request(
            "POST",
            "/api/config/config_entries/options/flow",
            json={"handler": entry_id},
        )

    async def configure_options_flow(self, flow_id: str, data: dict) -> dict:
        """Submit data to an options flow step."""
        return await self._request(
            "POST",
            f"/api/config/config_entries/options/flow/{flow_id}",
            json=data,
        )

    async def get_calendar_events(
        self, entity_id: str, start: str, end: str
    ) -> list[dict]:
        """Get calendar events for an entity within a time range."""
        return await self._request(
            "GET",
            f"/api/calendars/{entity_id}",
            params={"start": start, "end": end},
        )

    async def fire_event(self, event_type: str, data: dict | None = None) -> None:
        """Fire an event."""
        await self._request("POST", f"/api/events/{event_type}", json=data or {})

    async def get_services(self) -> list[dict]:
        """Get all registered services."""
        return await self._request("GET", "/api/services")

    async def close(self) -> None:
        """Close the HTTP session."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None
