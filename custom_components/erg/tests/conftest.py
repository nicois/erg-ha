"""Shared fixtures for Erg integration tests."""

from __future__ import annotations

import pytest


@pytest.fixture
def sample_jobs() -> list[dict]:
    """Return a set of sample recurring job definitions for testing."""
    return [
        {
            "entity_id": "switch.pool_pump",
            "ac_power": 1.5,
            "dc_power": 0,
            "force": False,
            "benefit": 0,
            "enabled": True,
            "recurrence": {
                "frequency": "daily",
                "time_window_start": "09:00",
                "time_window_end": "17:00",
                "maximum_duration": "3h",
                "minimum_duration": "1h",
                "minimum_burst": "30m",
            },
        },
        {
            "entity_id": "switch.ev_charger",
            "ac_power": 7.0,
            "dc_power": 0,
            "force": True,
            "benefit": 50,
            "enabled": True,
            "recurrence": {
                "frequency": "weekdays",
                "time_window_start": "22:00",
                "time_window_end": "06:00",
                "maximum_duration": "6h",
                "minimum_duration": "2h",
                "minimum_burst": "1h",
            },
        },
    ]


@pytest.fixture
def sample_tariff_defs() -> list[dict]:
    """Return a set of sample recurring tariff definitions for testing."""
    return [
        {
            "name": "Off-Peak",
            "import_price": 0.12,
            "feed_in_price": 0.05,
            "recurrence": {
                "frequency": "daily",
                "time_window_start": "22:00",
                "time_window_end": "07:00",
            },
        },
        {
            "name": "Peak",
            "import_price": 0.35,
            "feed_in_price": 0.03,
            "recurrence": {
                "frequency": "weekdays",
                "time_window_start": "14:00",
                "time_window_end": "20:00",
            },
        },
    ]


@pytest.fixture
def sample_schedule_data() -> dict:
    """Return sample coordinator data representing a schedule response."""
    return {
        "assignments": [
            {
                "entity": "switch.pool_pump",
                "slots": [
                    "2025-01-15T10:00:00+10:00",
                    "2025-01-15T10:05:00+10:00",
                    "2025-01-15T10:10:00+10:00",
                ],
                "run_time_seconds": 900,
                "energy_cost": 0.15,
                "energy_benefit": 1.5,
            },
            {
                "entity": "__solar__",
                "slots": [
                    "2025-01-15T09:00:00+10:00",
                    "2025-01-15T09:05:00+10:00",
                ],
                "run_time_seconds": 600,
                "energy_cost": 0.0,
                "energy_benefit": 0.0,
            },
        ],
        "total_benefit": 2.0,
        "total_cost": 0.45,
        "export_revenue": 0.30,
        "net_value": 1.85,
        "battery_profile": [
            {"time": "2025-01-15T09:00:00+10:00", "soc_kwh": 5.0},
            {"time": "2025-01-15T12:00:00+10:00", "soc_kwh": 7.5},
            {"time": "2025-01-15T18:00:00+10:00", "soc_kwh": 3.2},
        ],
        "feed_in_periods": [],
    }
