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

    async def get_auth_providers(self) -> list[dict[str, str]]:
        """Fetch available OIDC auth providers. Returns empty list if not supported."""
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/auth/providers",
                headers=self._headers(),
            ) as resp:
                if resp.status == 404:
                    return []
                if resp.status != 200:
                    return []
                data = await resp.json()
                return data.get("providers", [])
        except aiohttp.ClientError:
            return []

    async def start_auth_flow(self, provider: str) -> dict[str, Any]:
        """Start an OIDC auth flow. Returns {login_url, state, expires_in}."""
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/auth/login",
                params={"provider": provider},
                headers=self._headers(),
            ) as resp:
                if resp.status != 200:
                    body = await resp.text()
                    raise ErgApiError(
                        f"Failed to start auth flow (HTTP {resp.status}): {body}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

    async def poll_auth_status(self, state: str) -> dict[str, Any]:
        """Poll the auth flow status. Returns {status, session_token?, user?}."""
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/auth/status",
                params={"state": state},
                headers=self._headers(),
            ) as resp:
                if resp.status != 200:
                    return {"status": "expired"}
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

    async def get_me(self) -> dict[str, Any]:
        """Get current user info and quota usage."""
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/auth/me",
                headers=self._headers(),
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                if resp.status != 200:
                    body = await resp.text()
                    raise ErgApiError(
                        f"Failed to get user info (HTTP {resp.status}): {body}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

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
                    msg = body
                    try:
                        err_data = await resp.json()
                        if isinstance(err_data, dict) and "error" in err_data:
                            msg = err_data["error"]
                    except Exception:  # noqa: BLE001
                        pass
                    raise ErgApiError(
                        f"Schedule request failed (HTTP {resp.status}): {msg}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err
