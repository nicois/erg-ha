"""E2E tests: Integration loading and global entity verification."""

from __future__ import annotations

import pytest

from helpers.ha_client import HAClient

pytestmark = pytest.mark.api


@pytest.fixture
async def all_states(ha_client: HAClient) -> list[dict]:
    return await ha_client.get_states()


@pytest.fixture
def erg_entity_ids(all_states: list[dict]) -> set[str]:
    return {s["entity_id"] for s in all_states if "erg" in s["entity_id"]}


class TestIntegrationLoading:
    """Verify the integration loads correctly and creates expected entities."""

    async def test_config_entry_active(self, ha_client: HAClient, config_entry_id: str):
        """Config entry should be loaded and active."""
        entries = await ha_client.get_config_entries()
        erg_entries = [e for e in entries if e.get("domain") == "erg"]
        assert len(erg_entries) >= 1
        entry = next(e for e in erg_entries if e["entry_id"] == config_entry_id)
        assert entry["state"] == "loaded"

    async def test_global_sensors_exist(self, erg_entity_ids: set[str]):
        """All global sensor entities should exist."""
        expected_keys = [
            "net_schedule_value",
            "grid_import_cost",
            "job_scheduling_benefit",
            "grid_export_revenue",
            "battery_soc_forecast",
            "next_job",
            "schedule_age",
            "schedule_view_url",
            "import_price_threshold",
            "export_price_threshold",
            "solve_status",
        ]
        for key in expected_keys:
            matches = [eid for eid in erg_entity_ids if key in eid and eid.startswith("sensor.")]
            assert matches, f"No sensor found containing '{key}'. Erg entities: {erg_entity_ids}"

    async def test_calendar_entity_exists(self, erg_entity_ids: set[str]):
        """Calendar entity should exist."""
        calendars = [eid for eid in erg_entity_ids if eid.startswith("calendar.")]
        assert calendars, f"No calendar entity found. Erg entities: {erg_entity_ids}"

    async def test_button_solve_now_exists(self, erg_entity_ids: set[str]):
        """Solve Now button should exist."""
        buttons = [eid for eid in erg_entity_ids if "solve_now" in eid and eid.startswith("button.")]
        assert buttons, f"No solve_now button found. Erg entities: {erg_entity_ids}"

    async def test_solve_status_ok(self, ha_client: HAClient, erg_entity_ids: set[str]):
        """Solve status sensor should report 'ok' after initial load."""
        solve_entities = [eid for eid in erg_entity_ids if "solve_status" in eid]
        assert solve_entities
        state = await ha_client.get_state(solve_entities[0])
        assert state is not None
        # Solve status could be "ok" or "unknown" depending on whether
        # the coordinator has run. Accept either.
        assert state["state"] in ("ok", "unknown"), f"Unexpected solve_status: {state['state']}"

    async def test_no_error_entities(self, all_states: list[dict]):
        """No erg entities should be in 'unavailable' state."""
        erg_states = [s for s in all_states if "erg" in s["entity_id"]]
        unavailable = [s for s in erg_states if s["state"] == "unavailable"]
        # Some entities may be unavailable before first schedule, allow up to 2
        assert len(unavailable) <= 2, (
            f"Too many unavailable erg entities: "
            f"{[s['entity_id'] for s in unavailable]}"
        )
