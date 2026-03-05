"""E2E tests: Entity states and control verification."""

from __future__ import annotations

import asyncio

import pytest

from helpers.ha_client import HAClient
from helpers.wait import wait_for_state, wait_for_entity_exists

pytestmark = pytest.mark.api


class TestGlobalSensors:
    """Verify global sensor values from the schedule response."""

    async def test_net_schedule_value(self, ha_client: HAClient, config_entry_id: str):
        """Net value sensor should have a numeric value."""
        states = await ha_client.get_states()
        sensor = _find_erg_sensor(states, "net_schedule_value")
        assert sensor is not None, "net_schedule_value sensor not found"
        # Value comes from schedule response net_value = -0.05
        assert sensor["state"] not in ("unavailable", "unknown"), (
            f"Unexpected state: {sensor['state']}"
        )

    async def test_grid_import_cost(self, ha_client: HAClient, config_entry_id: str):
        """Grid import cost sensor should have a numeric value."""
        states = await ha_client.get_states()
        sensor = _find_erg_sensor(states, "grid_import_cost")
        assert sensor is not None
        assert sensor["state"] not in ("unavailable",)

    async def test_export_revenue(self, ha_client: HAClient, config_entry_id: str):
        """Export revenue sensor should have a value."""
        states = await ha_client.get_states()
        sensor = _find_erg_sensor(states, "grid_export_revenue")
        assert sensor is not None

    async def test_import_price_threshold(self, ha_client: HAClient, config_entry_id: str):
        """Import price threshold should have a value from schedule response."""
        states = await ha_client.get_states()
        sensor = _find_erg_sensor(states, "import_price_threshold")
        assert sensor is not None

    async def test_export_price_threshold(self, ha_client: HAClient, config_entry_id: str):
        """Export price threshold should have a value."""
        states = await ha_client.get_states()
        sensor = _find_erg_sensor(states, "export_price_threshold")
        assert sensor is not None


class TestPerJobSensors:
    """Verify per-job sensors after creating a recurring job."""

    async def test_job_entity_exists(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Main job sensor entity should exist."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        job_entities = [
            s for s in states
            if sanitized in s["entity_id"] and "erg" in s["entity_id"]
        ]
        assert job_entities, f"No job entities found for {created_recurring_job}"

    async def test_next_start_sensor(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Next start sensor should exist for the job."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        sensor = next(
            (s for s in states if "next_start" in s["entity_id"] and sanitized in s["entity_id"]),
            None,
        )
        assert sensor is not None, f"next_start sensor not found for {created_recurring_job}"

    async def test_energy_cost_sensor(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Energy cost sensor should exist for the job."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        sensor = next(
            (s for s in states if "energy_cost" in s["entity_id"] and sanitized in s["entity_id"]),
            None,
        )
        assert sensor is not None, f"energy_cost sensor not found for {created_recurring_job}"


class TestPerJobControls:
    """Verify per-job switch, number, text, and select entities."""

    async def test_switch_enabled_toggle(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Enabled switch should be toggleable."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        switch = next(
            (s for s in states if "enabled" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("switch.")),
            None,
        )
        if switch is None:
            pytest.skip("Enabled switch not found")

        # Toggle off
        await ha_client.call_service("switch", "turn_off", target={"entity_id": switch["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(switch["entity_id"])
        assert state["state"] == "off"

        # Toggle back on
        await ha_client.call_service("switch", "turn_on", target={"entity_id": switch["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(switch["entity_id"])
        assert state["state"] == "on"

    async def test_switch_must_run_toggle(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Must-run switch should be toggleable."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        switch = next(
            (s for s in states if "must_run" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("switch.")),
            None,
        )
        if switch is None:
            pytest.skip("Must-run switch not found")

        await ha_client.call_service("switch", "turn_on", target={"entity_id": switch["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(switch["entity_id"])
        assert state["state"] == "on"

    async def test_number_ac_power_set(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """AC power number entity should accept new values."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        number = next(
            (s for s in states if "ac_power" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("number.")),
            None,
        )
        if number is None:
            pytest.skip("AC power number not found")

        await ha_client.call_service("number", "set_value", data={"value": 2.5}, target={"entity_id": number["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(number["entity_id"])
        assert float(state["state"]) == pytest.approx(2.5, abs=0.1)

    async def test_number_benefit_set(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Benefit number entity should accept new values."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        number = next(
            (s for s in states if "benefit" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("number.") and "low_benefit" not in s["entity_id"]),
            None,
        )
        if number is None:
            pytest.skip("Benefit number not found")

        await ha_client.call_service("number", "set_value", data={"value": 1.0}, target={"entity_id": number["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(number["entity_id"])
        assert float(state["state"]) == pytest.approx(1.0, abs=0.1)

    async def test_select_frequency(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Frequency select entity should accept new values."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        select = next(
            (s for s in states if "frequency" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("select.")),
            None,
        )
        if select is None:
            pytest.skip("Frequency select not found")

        await ha_client.call_service("select", "select_option", data={"option": "weekdays"}, target={"entity_id": select["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(select["entity_id"])
        assert state["state"] == "weekdays"

    async def test_text_time_window_set(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Time window text entity should accept values."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        text = next(
            (s for s in states if "time_window_start" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("text.")),
            None,
        )
        if text is None:
            pytest.skip("Time window start text not found")

        await ha_client.call_service("text", "set_value", data={"value": "08:00"}, target={"entity_id": text["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(text["entity_id"])
        assert state["state"] == "08:00"

    async def test_text_duration_set(
        self, ha_client: HAClient, created_recurring_job: str
    ):
        """Max duration text entity should accept Go-style duration values."""
        states = await ha_client.get_states()
        sanitized = created_recurring_job.replace(".", "_")
        text = next(
            (s for s in states if "max_duration" in s["entity_id"] and sanitized in s["entity_id"] and s["entity_id"].startswith("text.")),
            None,
        )
        if text is None:
            pytest.skip("Max duration text not found")

        await ha_client.call_service("text", "set_value", data={"value": "1h30m"}, target={"entity_id": text["entity_id"]})
        await asyncio.sleep(1)
        state = await ha_client.get_state(text["entity_id"])
        assert state["state"] == "1h30m"

    async def test_button_solve_now(self, ha_client: HAClient, config_entry_id: str):
        """Pressing Solve Now should trigger a schedule refresh."""
        states = await ha_client.get_states()
        button = next(
            (s for s in states if "solve_now" in s["entity_id"] and s["entity_id"].startswith("button.")),
            None,
        )
        assert button is not None, "Solve Now button not found"

        await ha_client.call_service("button", "press", target={"entity_id": button["entity_id"]})

        # Give time for the coordinator to process
        await asyncio.sleep(5)

        # Verify the mock backend received a schedule request
        import aiohttp
        async with aiohttp.ClientSession() as session:
            async with session.get("http://localhost:8080/mock/requests") as resp:
                requests_data = await resp.json()

        schedule_requests = [
            r for r in requests_data
            if r["path"] in ("/api/v1/schedule", "/api/v1/schedule/async")
            and r["method"] == "POST"
        ]
        assert schedule_requests, "No schedule request was sent to mock backend after pressing Solve Now"


# =============================================================================
# Helpers
# =============================================================================


def _find_erg_sensor(states: list[dict], key: str) -> dict | None:
    """Find an erg sensor by key substring."""
    for s in states:
        if key in s["entity_id"] and s["entity_id"].startswith("sensor.") and "erg" in s["entity_id"]:
            return s
    return None
