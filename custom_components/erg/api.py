"""HTTP client for the Erg energy scheduler server."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class ErgApiError(Exception):
    """Base exception for Erg API errors."""


class ErgAuthError(ErgApiError):
    """Authentication failed."""


class ErgConnectionError(ErgApiError):
    """Could not connect to the server."""


class ErgApiClient:
    """Async HTTP client for the Erg scheduler API."""

    def __init__(
        self,
        session: aiohttp.ClientSession,
        base_url: str,
        token: str | None = None,
    ) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")
        self._token = token

    def _headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    async def health(self) -> bool:
        """Check server health. Returns True if healthy."""
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/health",
                headers=self._headers(),
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                return resp.status == 200
        except aiohttp.ClientError as err:
            raise ErgConnectionError(f"Cannot connect to Erg server: {err}") from err

    async def schedule(self, request: dict[str, Any]) -> dict[str, Any]:
        """Submit a scheduling problem and return the result."""
        try:
            async with self._session.post(
                f"{self._base_url}/api/v1/schedule",
                headers=self._headers(),
                json=request,
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                if resp.status != 200:
                    body = await resp.text()
                    raise ErgApiError(
                        f"Schedule request failed (HTTP {resp.status}): {body}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err
