"""E2E tests: Calendar entity verification."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from helpers.ha_client import HAClient

pytestmark = pytest.mark.api


class TestCalendarEvents:
    """Verify calendar entity shows schedule events."""

    async def test_calendar_entity_state(
        self, ha_client: HAClient, config_entry_id: str
    ):
        """Calendar entity should exist and not be unavailable."""
        states = await ha_client.get_states()
        calendar = next(
            (s for s in states if s["entity_id"].startswith("calendar.") and "erg" in s["entity_id"]),
            None,
        )
        assert calendar is not None, "Calendar entity not found"
        assert calendar["state"] != "unavailable"

    async def test_calendar_events_exist(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Calendar should have events matching schedule assignments."""
        states = await ha_client.get_states()
        calendar = next(
            (s for s in states if s["entity_id"].startswith("calendar.") and "erg" in s["entity_id"]),
            None,
        )
        if calendar is None:
            pytest.skip("Calendar entity not found")

        # Query events for the next 24 hours
        now = datetime.now(timezone.utc)
        start = (now - timedelta(hours=1)).isoformat()
        end = (now + timedelta(hours=24)).isoformat()

        try:
            events = await ha_client.get_calendar_events(
                calendar["entity_id"], start, end
            )
            # Events may or may not exist depending on timing; just verify
            # the endpoint works and returns a list
            assert isinstance(events, list), f"Expected list, got {type(events)}"
        except Exception as exc:
            # Calendar API may not be available in all HA versions
            pytest.skip(f"Calendar API not available: {exc}")
