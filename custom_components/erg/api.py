"""HTTP client for the Erg energy scheduler server."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)


class ErgApiError(Exception):
    """Base exception for Erg API errors."""

    def __init__(
        self,
        message: str,
        code: str = "UNKNOWN",
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.details = details or {}


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

    async def create_api_key(
        self, name: str, scope: str = "schedule"
    ) -> dict[str, Any] | None:
        """Create an API key. Returns the key data dict, or None if the server doesn't support keys (404)."""
        try:
            async with self._session.post(
                f"{self._base_url}/api/v1/keys",
                headers=self._headers(),
                json={"name": name, "scope": scope},
            ) as resp:
                if resp.status == 404:
                    return None
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                if resp.status != 200:
                    body = await resp.text()
                    raise ErgApiError(
                        f"Failed to create API key (HTTP {resp.status}): {body}"
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

    async def delete_api_key(self, key_id: int) -> bool:
        """Delete (revoke) an API key. Returns True on success."""
        try:
            async with self._session.delete(
                f"{self._base_url}/api/v1/keys/{key_id}",
                headers=self._headers(),
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                return resp.status == 200
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

    async def get_aemo_tariff(self, region: str) -> list[dict] | None:
        """Fetch AEMO PREDISPATCH tariff periods for a NEM region.

        Returns the periods list on success, None on 404/503 (server
        doesn't support AEMO or data unavailable). Raises ErgAuthError
        on 401/403.
        """
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/tariff/aemo",
                params={"region": region},
                headers=self._headers(),
            ) as resp:
                if resp.status in (404, 503):
                    return None
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                if resp.status != 200:
                    body = await resp.text()
                    raise ErgApiError(
                        f"Failed to get AEMO tariff (HTTP {resp.status}): {body}"
                    )
                data = await resp.json()
                return data.get("periods", [])
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

    async def submit_schedule_async(
        self, request: dict[str, Any]
    ) -> dict[str, Any] | None:
        """Submit async schedule request.

        Returns {"job_id": ..., "status": "pending"} or None if the
        server doesn't support async scheduling (404).
        """
        try:
            async with self._session.post(
                f"{self._base_url}/api/v1/schedule/async",
                headers=self._headers(),
                json=request,
            ) as resp:
                if resp.status == 404:
                    return None
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                if resp.status not in (200, 202):
                    body = await resp.text()
                    code = "UNKNOWN"
                    msg = body
                    details: dict[str, Any] = {}
                    try:
                        err_data = await resp.json()
                        if isinstance(err_data, dict) and "error" in err_data:
                            err_obj = err_data["error"]
                            if isinstance(err_obj, dict):
                                code = err_obj.get("code", "UNKNOWN")
                                msg = err_obj.get("message", body)
                                details = err_obj.get("details", {})
                            else:
                                msg = str(err_obj)
                    except Exception:  # noqa: BLE001
                        pass
                    raise ErgApiError(
                        f"Async schedule request failed (HTTP {resp.status}): {msg}",
                        code=code,
                        details=details,
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err

    async def get_schedule_job(self, job_id: str) -> dict[str, Any]:
        """Poll async job status.

        Returns {"job_id": ..., "status": ..., "result"?: ..., "error"?: ...}.
        Raises ErgApiError on 404 (job expired/not found) or other errors.
        """
        try:
            async with self._session.get(
                f"{self._base_url}/api/v1/schedule/jobs/{job_id}",
                headers=self._headers(),
            ) as resp:
                if resp.status == 401 or resp.status == 403:
                    raise ErgAuthError("Authentication failed")
                if resp.status == 404:
                    raise ErgApiError(
                        "Job not found", code="JOB_NOT_FOUND"
                    )
                if resp.status != 200:
                    body = await resp.text()
                    raise ErgApiError(
                        f"Job status request failed (HTTP {resp.status}): {body}"
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
                    code = "UNKNOWN"
                    msg = body
                    details: dict[str, Any] = {}
                    try:
                        err_data = await resp.json()
                        if isinstance(err_data, dict) and "error" in err_data:
                            err_obj = err_data["error"]
                            if isinstance(err_obj, dict):
                                code = err_obj.get("code", "UNKNOWN")
                                msg = err_obj.get("message", body)
                                details = err_obj.get("details", {})
                            else:
                                msg = str(err_obj)
                    except Exception:  # noqa: BLE001
                        pass
                    raise ErgApiError(
                        f"Schedule request failed (HTTP {resp.status}): {msg}",
                        code=code,
                        details=details,
                    )
                return await resp.json()
        except aiohttp.ClientError as err:
            raise ErgConnectionError(
                f"Cannot connect to Erg server: {err}"
            ) from err
