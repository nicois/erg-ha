"""Tests for coordinator.py — resolve_soc_kwh helper."""

from __future__ import annotations

import pytest

from custom_components.erg.coordinator import resolve_soc_kwh


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
