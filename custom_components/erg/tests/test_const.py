"""Tests for const.py — duration parser and constants."""

from __future__ import annotations

import pytest

import voluptuous as vol

from custom_components.erg.const import (
    PLATFORMS,
    parse_slot_duration_seconds,
    validate_duration,
    validate_time_str,
)


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


class TestValidateDuration:
    """Tests for validate_duration."""

    def test_accepts_minutes(self):
        assert validate_duration("30m") == "30m"

    def test_accepts_hours(self):
        assert validate_duration("2h") == "2h"

    def test_accepts_seconds(self):
        assert validate_duration("90s") == "90s"

    def test_accepts_combined(self):
        assert validate_duration("1h30m") == "1h30m"

    def test_accepts_full_hms(self):
        assert validate_duration("1h2m3s") == "1h2m3s"

    def test_accepts_zero_seconds(self):
        assert validate_duration("0s") == "0s"

    def test_strips_whitespace(self):
        assert validate_duration("  5m  ") == "5m"

    def test_rejects_garbage(self):
        with pytest.raises(vol.Invalid):
            validate_duration("garbage")

    def test_rejects_typo_180os(self):
        with pytest.raises(vol.Invalid):
            validate_duration("180os")

    def test_rejects_empty(self):
        with pytest.raises(vol.Invalid):
            validate_duration("")

    def test_rejects_bare_number(self):
        with pytest.raises(vol.Invalid):
            validate_duration("180")

    def test_rejects_wrong_unit(self):
        with pytest.raises(vol.Invalid):
            validate_duration("5d")

    def test_rejects_non_string(self):
        with pytest.raises(vol.Invalid):
            validate_duration(123)


class TestValidateTimeStr:
    """Tests for validate_time_str."""

    def test_accepts_midnight(self):
        assert validate_time_str("00:00") == "00:00"

    def test_accepts_noon(self):
        assert validate_time_str("12:00") == "12:00"

    def test_accepts_end_of_day(self):
        assert validate_time_str("23:59") == "23:59"

    def test_accepts_morning(self):
        assert validate_time_str("09:30") == "09:30"

    def test_strips_whitespace(self):
        assert validate_time_str("  17:00  ") == "17:00"

    def test_rejects_hour_25(self):
        with pytest.raises(vol.Invalid):
            validate_time_str("25:00")

    def test_rejects_minute_60(self):
        with pytest.raises(vol.Invalid):
            validate_time_str("12:60")

    def test_rejects_no_colon(self):
        with pytest.raises(vol.Invalid):
            validate_time_str("1200")

    def test_rejects_single_digit_hour(self):
        with pytest.raises(vol.Invalid):
            validate_time_str("9:00")

    def test_rejects_garbage(self):
        with pytest.raises(vol.Invalid):
            validate_time_str("morning")

    def test_rejects_empty(self):
        with pytest.raises(vol.Invalid):
            validate_time_str("")

    def test_rejects_non_string(self):
        with pytest.raises(vol.Invalid):
            validate_time_str(900)
