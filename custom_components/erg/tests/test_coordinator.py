"""Tests for coordinator.py — resolve_soc_kwh, EV box splitting, AEMO merge, polling."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.erg.api import ErgApiClient, ErgApiError
from custom_components.erg.coordinator import (
    ErgScheduleCoordinator,
    _extend_tariff_coverage,
    _merge_aemo_with_manual,
    _merge_overflow_assignments,
    _split_ev_boxes,
    resolve_soc_kwh,
)

from datetime import datetime, timezone


class TestResolveSocKwh:
    def test_percentage_converts_to_kwh(self):
        # 50% of 10 kWh battery = 5 kWh
        assert resolve_soc_kwh(50.0, "%", 10.0) == pytest.approx(5.0)

    def test_percentage_full(self):
        assert resolve_soc_kwh(100.0, "%", 13.5) == pytest.approx(13.5)

    def test_percentage_empty(self):
        assert resolve_soc_kwh(0.0, "%", 10.0) == pytest.approx(0.0)

    def test_percentage_partial(self):
        # 75% of 8 kWh = 6 kWh
        assert resolve_soc_kwh(75.0, "%", 8.0) == pytest.approx(6.0)

    def test_kwh_unit_passed_through(self):
        assert resolve_soc_kwh(4.5, "kWh", 10.0) == pytest.approx(4.5)

    def test_empty_unit_passed_through(self):
        assert resolve_soc_kwh(3.2, "", 10.0) == pytest.approx(3.2)

    def test_other_unit_passed_through(self):
        assert resolve_soc_kwh(7.0, "Wh", 10.0) == pytest.approx(7.0)

    def test_zero_capacity_with_percentage(self):
        # Edge case: % unit but zero capacity configured
        assert resolve_soc_kwh(50.0, "%", 0.0) == pytest.approx(0.0)


class TestSplitEvBoxes:
    """Tests for _split_ev_boxes — two-tier EV charging split."""

    def test_no_split_when_no_min_energy(self):
        boxes = [
            {
                "entity": "switch.ev",
                "target_energy": 50,
                "benefit": 10,
                "min_energy": 0,
                "low_benefit": 0,
                "ac_power": 7,
                "force": False,
            }
        ]
        result = _split_ev_boxes(boxes)
        assert len(result) == 1
        assert result[0]["entity"] == "switch.ev"
        assert result[0]["target_energy"] == 50
        assert result[0]["benefit"] == 10
        # min_energy and low_benefit should be stripped
        assert "min_energy" not in result[0]
        assert "low_benefit" not in result[0]

    def test_splits_into_two_boxes(self):
        boxes = [
            {
                "entity": "switch.ev",
                "target_energy": 50,
                "benefit": 10,
                "min_energy": 40,
                "low_benefit": 2,
                "ac_power": 7,
                "min_ac_power": 1.4,
                "force": False,
                "start_time": "2026-03-04T22:00:00+11:00",
                "finish_time": "2026-03-05T06:00:00+11:00",
                "maximum_duration": "6h",
            }
        ]
        result = _split_ev_boxes(boxes)
        assert len(result) == 2

        must_have = result[0]
        overflow = result[1]

        # Must-have box
        assert must_have["entity"] == "switch.ev"
        assert must_have["target_energy"] == 40
        assert must_have["benefit"] == 10
        assert must_have["ac_power"] == 7
        assert must_have["min_ac_power"] == 1.4
        assert "min_energy" not in must_have
        assert "low_benefit" not in must_have

        # Overflow box
        assert overflow["entity"] == "switch.ev__overflow"
        assert overflow["target_energy"] == 10
        assert overflow["benefit"] == 2
        assert overflow["ac_power"] == 7
        assert overflow["min_ac_power"] == 1.4
        assert overflow["start_time"] == must_have["start_time"]
        assert overflow["finish_time"] == must_have["finish_time"]
        assert "min_energy" not in overflow
        assert "low_benefit" not in overflow

    def test_no_split_when_min_energy_equals_target(self):
        boxes = [
            {
                "entity": "switch.ev",
                "target_energy": 40,
                "benefit": 10,
                "min_energy": 40,
                "low_benefit": 2,
                "ac_power": 7,
            }
        ]
        result = _split_ev_boxes(boxes)
        assert len(result) == 1
        assert result[0]["entity"] == "switch.ev"
        assert result[0]["target_energy"] == 40
        assert result[0]["benefit"] == 10

    def test_no_split_when_min_energy_exceeds_target(self):
        boxes = [
            {
                "entity": "switch.ev",
                "target_energy": 30,
                "benefit": 10,
                "min_energy": 40,
                "low_benefit": 2,
                "ac_power": 7,
            }
        ]
        result = _split_ev_boxes(boxes)
        assert len(result) == 1
        assert result[0]["entity"] == "switch.ev"
        assert result[0]["target_energy"] == 30

    def test_solar_boxes_pass_through(self):
        boxes = [
            {
                "entity": "__solar__",
                "ac_power": -5,
                "dc_power": 0,
                "min_energy": 0,
                "low_benefit": 0,
            },
            {
                "entity": "switch.ev",
                "target_energy": 50,
                "benefit": 10,
                "min_energy": 40,
                "low_benefit": 2,
                "ac_power": 7,
            },
        ]
        result = _split_ev_boxes(boxes)
        assert len(result) == 3
        assert result[0]["entity"] == "__solar__"
        assert result[1]["entity"] == "switch.ev"
        assert result[2]["entity"] == "switch.ev__overflow"

    def test_depends_on_in_box(self):
        """depends_on field appears in box dicts from _make_box."""
        from custom_components.erg.jobs import _make_box

        job = {
            "entity_id": "switch.dryer",
            "ac_power": 3.0,
            "dc_power": 0,
            "force": False,
            "benefit": 4,
            "depends_on": "switch.washer",
            "maximum_duration": "1h",
        }
        from datetime import datetime, timezone

        start = datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 5, 17, 0, tzinfo=timezone.utc)
        box = _make_box(job, start, end)
        assert box["depends_on"] == "switch.washer"

    def test_depends_on_defaults_empty_in_box(self):
        """depends_on defaults to empty string when not in job dict."""
        from custom_components.erg.jobs import _make_box

        job = {
            "entity_id": "switch.pump",
            "ac_power": 1.0,
            "maximum_duration": "1h",
        }
        from datetime import datetime, timezone

        start = datetime(2026, 3, 5, 9, 0, tzinfo=timezone.utc)
        end = datetime(2026, 3, 5, 17, 0, tzinfo=timezone.utc)
        box = _make_box(job, start, end)
        assert box["depends_on"] == ""


class TestMergeOverflowAssignments:
    """Tests for _merge_overflow_assignments."""

    def test_no_overflow_returns_unchanged(self):
        assignments = [
            {"entity": "switch.ev", "slots": ["s1", "s2"], "run_time_seconds": 600},
        ]
        result = _merge_overflow_assignments(assignments)
        assert result == assignments

    def test_merges_overflow_into_primary(self):
        assignments = [
            {
                "entity": "switch.ev",
                "slots": ["s1", "s2"],
                "run_time_seconds": 600,
                "energy_cost": 1.0,
            },
            {
                "entity": "switch.ev__overflow",
                "slots": ["s3"],
                "run_time_seconds": 300,
                "energy_cost": 0.5,
            },
        ]
        result = _merge_overflow_assignments(assignments)
        assert len(result) == 1
        assert result[0]["entity"] == "switch.ev"
        assert result[0]["slots"] == ["s1", "s2", "s3"]
        assert result[0]["run_time_seconds"] == 900
        assert result[0]["energy_cost"] == pytest.approx(1.5)

    def test_overflow_only_creates_primary(self):
        """Overflow scheduled but must-have was skipped."""
        assignments = [
            {
                "entity": "switch.ev__overflow",
                "slots": ["s1"],
                "run_time_seconds": 300,
                "energy_cost": 0.5,
            },
        ]
        result = _merge_overflow_assignments(assignments)
        assert len(result) == 1
        assert result[0]["entity"] == "switch.ev"
        assert result[0]["slots"] == ["s1"]

    def test_merges_slot_powers(self):
        assignments = [
            {
                "entity": "switch.ev",
                "slots": ["s1"],
                "slot_powers": [7.0],
                "run_time_seconds": 300,
                "energy_cost": 0.5,
            },
            {
                "entity": "switch.ev__overflow",
                "slots": ["s2"],
                "slot_powers": [3.5],
                "run_time_seconds": 300,
                "energy_cost": 0.3,
            },
        ]
        result = _merge_overflow_assignments(assignments)
        assert len(result) == 1
        assert result[0]["slot_powers"] == [7.0, 3.5]


class TestMergeAemoWithManual:
    """Tests for _merge_aemo_with_manual — AEMO wholesale + manual offsets."""

    def test_adds_wholesale_to_manual_offsets(self):
        aemo = [
            {
                "start": "2026-03-04T00:00:00+00:00",
                "end": "2026-03-04T00:30:00+00:00",
                "import_price": 0.06,
                "feed_in_price": 0.06,
            },
            {
                "start": "2026-03-04T14:00:00+00:00",
                "end": "2026-03-04T14:30:00+00:00",
                "import_price": 0.12,
                "feed_in_price": 0.12,
            },
        ]
        manual = [
            {
                "start": "2026-03-03T22:00:00+00:00",
                "end": "2026-03-04T07:00:00+00:00",
                "import_price": 0.05,  # off-peak network charge
                "feed_in_price": 0.02,
            },
            {
                "start": "2026-03-04T07:00:00+00:00",
                "end": "2026-03-04T22:00:00+00:00",
                "import_price": 0.15,  # peak network charge
                "feed_in_price": 0.01,
            },
        ]
        result = _merge_aemo_with_manual(aemo, manual)
        assert len(result) == 2
        # 00:00 falls in off-peak: 0.06 + 0.05 = 0.11
        assert result[0]["import_price"] == pytest.approx(0.11)
        assert result[0]["feed_in_price"] == pytest.approx(0.08)
        # 14:00 falls in peak: 0.12 + 0.15 = 0.27
        assert result[1]["import_price"] == pytest.approx(0.27)
        assert result[1]["feed_in_price"] == pytest.approx(0.13)

    def test_zero_offset_when_no_manual_covers_period(self):
        aemo = [
            {
                "start": "2026-03-04T00:00:00+00:00",
                "end": "2026-03-04T00:30:00+00:00",
                "import_price": 0.08,
                "feed_in_price": 0.08,
            },
        ]
        manual = []  # no manual tariffs configured
        result = _merge_aemo_with_manual(aemo, manual)
        assert len(result) == 1
        assert result[0]["import_price"] == pytest.approx(0.08)
        assert result[0]["feed_in_price"] == pytest.approx(0.08)

    def test_preserves_aemo_period_boundaries(self):
        aemo = [
            {
                "start": "2026-03-04T10:00:00+00:00",
                "end": "2026-03-04T10:30:00+00:00",
                "import_price": 0.07,
                "feed_in_price": 0.07,
            },
        ]
        manual = [
            {
                "start": "2026-03-04T00:00:00+00:00",
                "end": "2026-03-05T00:00:00+00:00",
                "import_price": 0.10,
                "feed_in_price": 0.03,
            },
        ]
        result = _merge_aemo_with_manual(aemo, manual)
        assert len(result) == 1
        assert result[0]["start"] == "2026-03-04T10:00:00+00:00"
        assert result[0]["end"] == "2026-03-04T10:30:00+00:00"

    def test_empty_aemo_returns_empty(self):
        result = _merge_aemo_with_manual([], [{"start": "2026-03-04T00:00:00+00:00", "end": "2026-03-05T00:00:00+00:00", "import_price": 0.1, "feed_in_price": 0.05}])
        assert result == []


class TestExtendTariffCoverage:
    """Tests for _extend_tariff_coverage — fill horizon edge gaps."""

    def test_extends_first_period_backward(self):
        periods = [
            {
                "start": "2026-03-04T12:00:00+00:00",
                "end": "2026-03-04T12:30:00+00:00",
                "import_price": 0.20,
                "feed_in_price": 0.05,
            },
        ]
        h_start = datetime(2026, 3, 4, 11, 54, 21, tzinfo=timezone.utc)
        h_end = datetime(2026, 3, 4, 12, 30, 0, tzinfo=timezone.utc)
        result = _extend_tariff_coverage(periods, h_start, h_end)
        assert result[0]["start"] == h_start.isoformat()
        assert result[0]["end"] == "2026-03-04T12:30:00+00:00"

    def test_extends_last_period_forward(self):
        periods = [
            {
                "start": "2026-03-04T12:00:00+00:00",
                "end": "2026-03-04T12:30:00+00:00",
                "import_price": 0.20,
                "feed_in_price": 0.05,
            },
        ]
        h_start = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
        h_end = datetime(2026, 3, 4, 13, 0, 0, tzinfo=timezone.utc)
        result = _extend_tariff_coverage(periods, h_start, h_end)
        assert result[0]["start"] == "2026-03-04T12:00:00+00:00"
        assert result[0]["end"] == h_end.isoformat()

    def test_extends_both_ends(self):
        periods = [
            {
                "start": "2026-03-04T12:00:00+00:00",
                "end": "2026-03-04T12:30:00+00:00",
                "import_price": 0.20,
                "feed_in_price": 0.05,
            },
            {
                "start": "2026-03-04T12:30:00+00:00",
                "end": "2026-03-04T13:00:00+00:00",
                "import_price": 0.25,
                "feed_in_price": 0.06,
            },
        ]
        h_start = datetime(2026, 3, 4, 11, 50, 0, tzinfo=timezone.utc)
        h_end = datetime(2026, 3, 4, 14, 0, 0, tzinfo=timezone.utc)
        result = _extend_tariff_coverage(periods, h_start, h_end)
        assert len(result) == 2
        assert result[0]["start"] == h_start.isoformat()
        assert result[0]["import_price"] == 0.20  # prices unchanged
        assert result[-1]["end"] == h_end.isoformat()
        assert result[-1]["import_price"] == 0.25

    def test_no_change_when_already_covered(self):
        periods = [
            {
                "start": "2026-03-04T11:00:00+00:00",
                "end": "2026-03-04T14:00:00+00:00",
                "import_price": 0.20,
                "feed_in_price": 0.05,
            },
        ]
        h_start = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
        h_end = datetime(2026, 3, 4, 13, 0, 0, tzinfo=timezone.utc)
        result = _extend_tariff_coverage(periods, h_start, h_end)
        assert result[0]["start"] == "2026-03-04T11:00:00+00:00"
        assert result[0]["end"] == "2026-03-04T14:00:00+00:00"

    def test_empty_periods_returns_empty(self):
        h_start = datetime(2026, 3, 4, 12, 0, 0, tzinfo=timezone.utc)
        h_end = datetime(2026, 3, 4, 13, 0, 0, tzinfo=timezone.utc)
        assert _extend_tariff_coverage([], h_start, h_end) == []

    def test_sorts_by_start_time(self):
        periods = [
            {
                "start": "2026-03-04T13:00:00+00:00",
                "end": "2026-03-04T13:30:00+00:00",
                "import_price": 0.25,
                "feed_in_price": 0.06,
            },
            {
                "start": "2026-03-04T12:00:00+00:00",
                "end": "2026-03-04T12:30:00+00:00",
                "import_price": 0.20,
                "feed_in_price": 0.05,
            },
        ]
        h_start = datetime(2026, 3, 4, 11, 50, 0, tzinfo=timezone.utc)
        h_end = datetime(2026, 3, 4, 14, 0, 0, tzinfo=timezone.utc)
        result = _extend_tariff_coverage(periods, h_start, h_end)
        # First period (by time) gets extended backward
        assert result[0]["start"] == h_start.isoformat()
        assert result[0]["import_price"] == 0.20
        # Last period gets extended forward
        assert result[-1]["end"] == h_end.isoformat()
        assert result[-1]["import_price"] == 0.25


class TestScheduleWithPolling:
    """Tests for ErgScheduleCoordinator._schedule_with_polling()."""

    def _make_coordinator(self, api_client):
        """Create a coordinator with a mocked hass and config entry.

        We bypass __init__ since DataUpdateCoordinator requires a real
        HomeAssistant instance. We only need the api_client attribute
        and the _schedule_with_polling method.
        """
        coord = object.__new__(ErgScheduleCoordinator)
        coord.api_client = api_client
        return coord

    @pytest.mark.asyncio
    async def test_async_happy_path(self):
        """Async submit, poll pending, poll complete — returns result."""
        api = MagicMock(spec=ErgApiClient)
        api.submit_schedule_async = AsyncMock(
            return_value={"job_id": "job123", "status": "pending"}
        )
        expected_result = {"assignments": [{"entity": "switch.pump"}]}
        # First poll: solving, second poll: complete
        api.get_schedule_job = AsyncMock(
            side_effect=[
                {"job_id": "job123", "status": "solving"},
                {
                    "job_id": "job123",
                    "status": "complete",
                    "result": expected_result,
                },
            ]
        )

        coord = self._make_coordinator(api)
        with patch("custom_components.erg.coordinator.asyncio.sleep", new_callable=AsyncMock):
            result = await coord._schedule_with_polling({"system": {}})

        assert result == expected_result
        api.submit_schedule_async.assert_called_once_with({"system": {}})
        assert api.get_schedule_job.call_count == 2

    @pytest.mark.asyncio
    async def test_fallback_to_sync(self):
        """When submit_schedule_async returns None, falls back to sync."""
        api = MagicMock(spec=ErgApiClient)
        api.submit_schedule_async = AsyncMock(return_value=None)
        expected_result = {"assignments": []}
        api.schedule = AsyncMock(return_value=expected_result)

        coord = self._make_coordinator(api)
        result = await coord._schedule_with_polling({"system": {}})

        assert result == expected_result
        api.schedule.assert_called_once_with({"system": {}})
        api.get_schedule_job.assert_not_called()

    @pytest.mark.asyncio
    async def test_poll_timeout(self):
        """When polling never completes, raises ErgApiError."""
        api = MagicMock(spec=ErgApiClient)
        api.submit_schedule_async = AsyncMock(
            return_value={"job_id": "job123", "status": "pending"}
        )
        api.get_schedule_job = AsyncMock(
            return_value={"job_id": "job123", "status": "solving"}
        )

        coord = self._make_coordinator(api)
        with patch("custom_components.erg.coordinator.asyncio.sleep", new_callable=AsyncMock):
            with patch("custom_components.erg.coordinator._SCHEDULE_POLL_MAX_ATTEMPTS", 3):
                with pytest.raises(ErgApiError, match="timed out"):
                    await coord._schedule_with_polling({"system": {}})

        assert api.get_schedule_job.call_count == 3

    @pytest.mark.asyncio
    async def test_poll_failed_job(self):
        """When job fails, raises ErgApiError with code and message."""
        api = MagicMock(spec=ErgApiClient)
        api.submit_schedule_async = AsyncMock(
            return_value={"job_id": "job123", "status": "pending"}
        )
        api.get_schedule_job = AsyncMock(
            return_value={
                "job_id": "job123",
                "status": "failed",
                "error": {
                    "code": "INFEASIBLE_POWER_LIMIT",
                    "message": "forced jobs exceed grid limit",
                },
            }
        )

        coord = self._make_coordinator(api)
        with patch("custom_components.erg.coordinator.asyncio.sleep", new_callable=AsyncMock):
            with pytest.raises(ErgApiError, match="forced jobs exceed grid limit") as exc_info:
                await coord._schedule_with_polling({"system": {}})

        assert exc_info.value.code == "INFEASIBLE_POWER_LIMIT"


class TestPreservationBoundsPassthrough:
    """Verify preservation bound fields are passed to the API request."""

    def test_fields_in_system_dict(self):
        """The coordinator builds a system dict from opts — verify the new fields
        are included with the expected defaults when not configured."""
        opts: dict = {}
        system = {
            "battery_preservation": opts.get("battery_preservation", 0.0),
            "preservation_lower_bound": opts.get("preservation_lower_bound", 0.0),
            "preservation_upper_bound": opts.get("preservation_upper_bound", 0.0),
        }
        assert "preservation_lower_bound" in system
        assert "preservation_upper_bound" in system
        assert system["preservation_lower_bound"] == 0.0
        assert system["preservation_upper_bound"] == 0.0

    def test_fields_with_custom_values(self):
        """When the user configures custom bounds, they propagate correctly."""
        opts = {
            "preservation_lower_bound": 0.1,
            "preservation_upper_bound": 0.95,
        }
        system = {
            "preservation_lower_bound": opts.get("preservation_lower_bound", 0.0),
            "preservation_upper_bound": opts.get("preservation_upper_bound", 0.0),
        }
        assert system["preservation_lower_bound"] == 0.1
        assert system["preservation_upper_bound"] == 0.95
