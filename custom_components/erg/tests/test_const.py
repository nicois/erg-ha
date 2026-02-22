"""Tests for const.py — duration parser and constants."""

from __future__ import annotations

import pytest

from custom_components.erg.const import PLATFORMS, parse_slot_duration_seconds


class TestPlatforms:
    """Tests for PLATFORMS constant."""

    def test_platforms_contains_sensor(self):
        assert "sensor" in PLATFORMS

    def test_platforms_contains_binary_sensor(self):
        assert "binary_sensor" in PLATFORMS

    def test_platforms_contains_calendar(self):
        assert "calendar" in PLATFORMS


class TestParseSlotDurationSeconds:
    """Tests for parse_slot_duration_seconds."""

    def test_five_minutes(self):
        assert parse_slot_duration_seconds("5m") == 300

    def test_one_hour(self):
        assert parse_slot_duration_seconds("1h") == 3600

    def test_one_hour_thirty_minutes(self):
        assert parse_slot_duration_seconds("1h30m") == 5400

    def test_seconds_only(self):
        assert parse_slot_duration_seconds("90s") == 90

    def test_full_hms(self):
        assert parse_slot_duration_seconds("1h2m3s") == 3723

    def test_empty_string_returns_default(self):
        assert parse_slot_duration_seconds("") == 300

    def test_invalid_string_returns_default(self):
        assert parse_slot_duration_seconds("garbage") == 300

    def test_zero_returns_default(self):
        assert parse_slot_duration_seconds("0s") == 300
