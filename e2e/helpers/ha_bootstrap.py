"""Automate Home Assistant first-time onboarding for E2E tests."""

from __future__ import annotations

import asyncio
import logging

import aiohttp

_LOGGER = logging.getLogger(__name__)

HA_BASE = "http://localhost:8123"
OWNER_NAME = "test"
OWNER_USERNAME = "test"
OWNER_PASSWORD = "test"


async def wait_for_ha(timeout: float = 120, interval: float = 1.0) -> None:
    """Poll HA until it responds, up to timeout seconds."""
    _LOGGER.info("Waiting for Home Assistant to be ready...")
    deadline = asyncio.get_event_loop().time() + timeout
    last_error = None
    async with aiohttp.ClientSession() as session:
        while asyncio.get_event_loop().time() < deadline:
            try:
                async with session.get(f"{HA_BASE}/api/", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                    if resp.status in (200, 401):
                        _LOGGER.info("Home Assistant is ready (status=%d)", resp.status)
                        return
            except (aiohttp.ClientError, asyncio.TimeoutError) as err:
                last_error = err
            await asyncio.sleep(interval)
    raise TimeoutError(f"HA did not become ready within {timeout}s. Last error: {last_error}")


async def onboard_and_get_token(timeout: float = 120) -> str:
    """Run HA onboarding and return a long-lived access token.

    Steps:
    1. Wait for HA to be ready
    2. Create owner user
    3. Accept core config
    4. Skip analytics
    5. Skip integration discovery
    6. Get an auth token via password grant
    7. Create a long-lived access token
    """
    await wait_for_ha(timeout=timeout)

    async with aiohttp.ClientSession() as session:
        # Step 1: Create owner user
        _LOGGER.info("Creating owner user...")
        async with session.post(
            f"{HA_BASE}/api/onboarding/users",
            json={
                "name": OWNER_NAME,
                "username": OWNER_USERNAME,
                "password": OWNER_PASSWORD,
                "language": "en",
            },
        ) as resp:
            if resp.status == 200:
                result = await resp.json()
                auth_code = result.get("auth_code")
                _LOGGER.info("Owner created, auth_code obtained")
            elif resp.status == 403:
                _LOGGER.info("Onboarding already done, proceeding to auth")
                auth_code = None
            else:
                text = await resp.text()
                raise RuntimeError(f"Failed to create owner (HTTP {resp.status}): {text}")

        # If we have an auth_code from onboarding, exchange it for tokens
        if auth_code:
            async with session.post(
                f"{HA_BASE}/auth/token",
                data={
                    "grant_type": "authorization_code",
                    "code": auth_code,
                    "client_id": "http://localhost:8123/",
                },
            ) as resp:
                if resp.status != 200:
                    text = await resp.text()
                    raise RuntimeError(f"Auth code exchange failed (HTTP {resp.status}): {text}")
                token_data = await resp.json()
                access_token = token_data["access_token"]
                refresh_token = token_data.get("refresh_token")
        else:
            # Onboarding already done; get token via password grant
            access_token, refresh_token = await _password_login(session)

        headers = {"Authorization": f"Bearer {access_token}"}

        # Step 2: Accept core config (may fail if already done, that's fine)
        try:
            async with session.post(
                f"{HA_BASE}/api/onboarding/core_config",
                headers=headers,
            ) as resp:
                _LOGGER.info("Core config step: status=%d", resp.status)
        except Exception:
            pass

        # Step 3: Skip analytics
        try:
            async with session.post(
                f"{HA_BASE}/api/onboarding/analytics",
                headers=headers,
            ) as resp:
                _LOGGER.info("Analytics step: status=%d", resp.status)
        except Exception:
            pass

        # Step 4: Skip integration discovery
        try:
            async with session.post(
                f"{HA_BASE}/api/onboarding/integration",
                headers=headers,
                json={"client_id": "http://localhost:8123/"},
            ) as resp:
                _LOGGER.info("Integration step: status=%d", resp.status)
        except Exception:
            pass

        # Step 5: Create a long-lived access token
        _LOGGER.info("Creating long-lived access token...")
        async with session.post(
            f"{HA_BASE}/auth/long_lived_access_token",
            headers=headers,
            json={
                "client_name": "e2e-test",
                "lifespan": 365,
            },
        ) as resp:
            if resp.status == 200:
                ll_token = await resp.text()
                # HA returns the token as a JSON string
                ll_token = ll_token.strip().strip('"')
                _LOGGER.info("Long-lived token created")
                return ll_token
            else:
                # Fall back to using the regular access token
                _LOGGER.warning(
                    "Could not create long-lived token (HTTP %d), using session token",
                    resp.status,
                )
                return access_token


async def _password_login(session: aiohttp.ClientSession) -> tuple[str, str | None]:
    """Get access token via password grant (for already-onboarded instances)."""
    # HA uses the auth/login_flow endpoint for password auth
    # Step 1: Initialize flow
    async with session.post(
        f"{HA_BASE}/auth/login_flow",
        json={
            "client_id": "http://localhost:8123/",
            "handler": ["homeassistant", None],
            "redirect_uri": "http://localhost:8123/",
        },
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Login flow init failed (HTTP {resp.status}): {text}")
        flow = await resp.json()
        flow_id = flow["flow_id"]

    # Step 2: Submit credentials
    async with session.post(
        f"{HA_BASE}/auth/login_flow/{flow_id}",
        json={
            "client_id": "http://localhost:8123/",
            "username": OWNER_USERNAME,
            "password": OWNER_PASSWORD,
        },
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Login flow submit failed (HTTP {resp.status}): {text}")
        result = await resp.json()
        auth_code = result.get("result")

    # Step 3: Exchange code for token
    async with session.post(
        f"{HA_BASE}/auth/token",
        data={
            "grant_type": "authorization_code",
            "code": auth_code,
            "client_id": "http://localhost:8123/",
        },
    ) as resp:
        if resp.status != 200:
            text = await resp.text()
            raise RuntimeError(f"Token exchange failed (HTTP {resp.status}): {text}")
        token_data = await resp.json()
        return token_data["access_token"], token_data.get("refresh_token")
