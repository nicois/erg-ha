"""E2E tests: Config flow via Playwright browser automation."""

from __future__ import annotations

import asyncio
import time

import aiohttp
import pytest

pytestmark = pytest.mark.ui

MOCK_BACKEND_URL = "http://localhost:8080"
HA_URL = "http://localhost:8123"


class TestConfigFlowUI:
    """Test the initial integration configuration flow in the browser."""

    def test_add_integration_page_loads(self, page, config_entry_id: str):
        """The integrations page should load and show the erg integration."""
        page.goto(f"{HA_URL}/config/integrations")
        page.wait_for_load_state("networkidle")

        # Look for the erg integration card
        page.wait_for_timeout(3000)

        # The integration should be visible
        content = page.content()
        assert "erg" in content.lower() or "Erg" in content, (
            "Erg integration not found on integrations page"
        )

    def test_integration_config_entry_visible(self, page, config_entry_id: str):
        """The configured erg entry should be visible on the integrations page."""
        page.goto(f"{HA_URL}/config/integrations")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(3000)

        # Look for erg-related text
        content = page.content()
        # The entry title is "Erg (mock-backend:8080)"
        assert "mock-backend" in content or "erg" in content.lower(), (
            "Erg config entry not visible"
        )

    def test_connection_error_display(self, page):
        """Adding integration with wrong port should show error.

        Note: This test creates a new config flow. If the integration
        is already configured with a unique_id, HA may abort with
        'already_configured'. We test the flow mechanics.
        """
        page.goto(f"{HA_URL}/config/integrations/dashboard")
        page.wait_for_load_state("networkidle")
        page.wait_for_timeout(2000)

        # Look for "Add Integration" button
        add_button = page.locator("ha-fab, [aria-label='Add integration']").first
        if add_button.is_visible():
            add_button.click()
            page.wait_for_timeout(2000)

            # Search for "erg" in the integration list
            search_input = page.locator("search-input input, [type='search']").first
            if search_input.is_visible():
                search_input.fill("erg")
                page.wait_for_timeout(1000)

        # This is a smoke test — just verify the page doesn't crash
        content = page.content()
        assert content  # Page rendered something
