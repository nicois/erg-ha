"""Tests for api.py — ErgApiClient with mocked aiohttp."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.api import (
    ErgApiClient,
    ErgAuthError,
    ErgConnectionError,
)


def _make_response(status: int, json_data: dict | None = None, text: str = ""):
    """Create a mock aiohttp response."""
    resp = AsyncMock()
    resp.status = status
    resp.json = AsyncMock(return_value=json_data)
    resp.text = AsyncMock(return_value=text)
    return resp


def _make_session(method: str, response):
    """Create a mock aiohttp.ClientSession with a context-manager method."""
    session = MagicMock()
    ctx = AsyncMock()
    ctx.__aenter__ = AsyncMock(return_value=response)
    ctx.__aexit__ = AsyncMock(return_value=False)

    if method == "get":
        session.get = MagicMock(return_value=ctx)
    elif method == "post":
        session.post = MagicMock(return_value=ctx)
    return session


class TestHealthCheck:
    """Tests for ErgApiClient.health()."""

    @pytest.mark.asyncio
    async def test_health_returns_true_on_200(self):
        resp = _make_response(200)
        session = _make_session("get", resp)
        client = ErgApiClient(session, "http://localhost:8080")

        result = await client.health()
        assert result is True
        session.get.assert_called_once_with(
            "http://localhost:8080/api/v1/health",
            headers={"Content-Type": "application/json"},
        )

    @pytest.mark.asyncio
    async def test_health_returns_false_on_500(self):
        resp = _make_response(500)
        session = _make_session("get", resp)
        client = ErgApiClient(session, "http://localhost:8080")

        result = await client.health()
        assert result is False

    @pytest.mark.asyncio
    async def test_health_raises_auth_error_on_401(self):
        resp = _make_response(401)
        session = _make_session("get", resp)
        client = ErgApiClient(session, "http://localhost:8080")

        with pytest.raises(ErgAuthError):
            await client.health()

    @pytest.mark.asyncio
    async def test_health_raises_auth_error_on_403(self):
        resp = _make_response(403)
        session = _make_session("get", resp)
        client = ErgApiClient(session, "http://localhost:8080")

        with pytest.raises(ErgAuthError):
            await client.health()

    @pytest.mark.asyncio
    async def test_health_raises_connection_error(self):
        import aiohttp

        session = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("refused"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.get = MagicMock(return_value=ctx)

        client = ErgApiClient(session, "http://localhost:8080")
        with pytest.raises(ErgConnectionError):
            await client.health()


class TestSchedule:
    """Tests for ErgApiClient.schedule()."""

    @pytest.mark.asyncio
    async def test_schedule_returns_parsed_json(self):
        expected = {"assignments": [], "total_cost": 0}
        resp = _make_response(200, json_data=expected)
        session = _make_session("post", resp)
        client = ErgApiClient(session, "http://localhost:8080", token="secret")

        result = await client.schedule({"system": {}, "boxes": []})
        assert result == expected
        session.post.assert_called_once()
        # Verify auth header is included
        call_kwargs = session.post.call_args
        headers = call_kwargs[1]["headers"] if "headers" in call_kwargs[1] else call_kwargs[0][1]
        assert headers["Authorization"] == "Bearer secret"

    @pytest.mark.asyncio
    async def test_schedule_raises_auth_error_on_401(self):
        resp = _make_response(401)
        session = _make_session("post", resp)
        client = ErgApiClient(session, "http://localhost:8080")

        with pytest.raises(ErgAuthError):
            await client.schedule({})

    @pytest.mark.asyncio
    async def test_schedule_raises_api_error_on_bad_status(self):
        from custom_components.erg.api import ErgApiError

        resp = _make_response(500, text="internal error")
        session = _make_session("post", resp)
        client = ErgApiClient(session, "http://localhost:8080")

        with pytest.raises(ErgApiError, match="HTTP 500"):
            await client.schedule({})

    @pytest.mark.asyncio
    async def test_schedule_raises_connection_error(self):
        import aiohttp

        session = MagicMock()
        ctx = AsyncMock()
        ctx.__aenter__ = AsyncMock(side_effect=aiohttp.ClientError("timeout"))
        ctx.__aexit__ = AsyncMock(return_value=False)
        session.post = MagicMock(return_value=ctx)

        client = ErgApiClient(session, "http://localhost:8080")
        with pytest.raises(ErgConnectionError):
            await client.schedule({})

    @pytest.mark.asyncio
    async def test_base_url_trailing_slash_stripped(self):
        resp = _make_response(200, json_data={})
        session = _make_session("post", resp)
        client = ErgApiClient(session, "http://localhost:8080/", token=None)

        await client.schedule({})
        call_args = session.post.call_args
        url = call_args[0][0] if call_args[0] else call_args[1].get("url", "")
        assert "//" not in url.replace("http://", "")
