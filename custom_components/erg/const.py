"""Constants for the Erg Energy Scheduler integration."""

from __future__ import annotations

import re

import voluptuous as vol

DOMAIN = "erg"
CONF_SESSION_TOKEN = "session_token"
PLATFORMS: list[str] = ["sensor", "binary_sensor", "calendar", "switch", "number", "select", "text"]

DEFAULT_PORT = 8080
DEFAULT_SLOT_DURATION = "15m"
DEFAULT_HORIZON_HOURS = 24
DEFAULT_UPDATE_INTERVAL_MINUTES = 15
DEFAULT_EXTEND_TO_END_OF_DAY = True

_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")
_TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")


def parse_slot_duration_seconds(slot_duration_str: str) -> int:
    """Parse a Go-style duration string like '5m', '1h30m' to seconds.

    Supports h, m, s components. Returns 300 (5 min) as default if parsing fails.
    """
    if not slot_duration_str:
        return 300

    m = _DURATION_RE.match(slot_duration_str.strip())
    if not m or not any(m.groups()):
        return 300

    hours = int(m.group(1)) if m.group(1) else 0
    minutes = int(m.group(2)) if m.group(2) else 0
    seconds = int(m.group(3)) if m.group(3) else 0

    total = hours * 3600 + minutes * 60 + seconds
    return total if total > 0 else 300


def format_duration_seconds(total_seconds: int) -> str:
    """Format seconds as a Go-style duration string like '1h30m'.

    Returns '0s' for zero or negative values.
    """
    if total_seconds <= 0:
        return "0s"
    hours = total_seconds // 3600
    remaining = total_seconds % 3600
    minutes = remaining // 60
    seconds = remaining % 60
    parts = []
    if hours:
        parts.append(f"{hours}h")
    if minutes:
        parts.append(f"{minutes}m")
    if seconds:
        parts.append(f"{seconds}s")
    return "".join(parts) or "0s"


def validate_duration(value: str) -> str:
    """Validate a Go-style duration string like '5m', '1h30m', '0s'.

    Raises vol.Invalid if the format is wrong. Returns the original string
    unchanged so it can be used as a voluptuous validator.
    """
    if not isinstance(value, str) or not value.strip():
        raise vol.Invalid("Duration must be a non-empty string")
    stripped = value.strip()
    m = _DURATION_RE.match(stripped)
    if not m or not any(m.groups()):
        raise vol.Invalid(
            f"Invalid duration '{value}'. Use h/m/s components, e.g. '1h', '30m', '1h30m', '90s'."
        )
    return stripped


def validate_time_str(value: str) -> str:
    """Validate an HH:MM time string.

    Raises vol.Invalid if the format is wrong. Returns the original string
    unchanged so it can be used as a voluptuous validator.
    """
    if not isinstance(value, str) or not value.strip():
        raise vol.Invalid("Time must be a non-empty string")
    stripped = value.strip()
    if not _TIME_RE.match(stripped):
        raise vol.Invalid(
            f"Invalid time '{value}'. Use HH:MM format, e.g. '09:00', '17:30'."
        )
    return stripped


def make_job_device_info(entity_id: str) -> dict:
    """Build a DeviceInfo-compatible dict for grouping per-job entities under one device."""
    if "." in entity_id:
        friendly = entity_id.split(".", 1)[1].replace("_", " ").title()
    else:
        friendly = entity_id.replace("_", " ").title()
    return {
        "identifiers": {(DOMAIN, entity_id)},
        "name": f"Erg Job: {friendly}",
        "manufacturer": "Erg Energy Scheduler",
        "model": "Scheduled Job",
        "entry_type": "service",
    }


FREQUENCY_CHOICES = {
    "daily": "Daily",
    "weekdays": "Weekdays (Mon-Fri)",
    "weekends": "Weekends (Sat-Sun)",
    "weekly": "Weekly (specific day)",
    "custom": "Custom (specific days)",
}

DAY_OF_WEEK_CHOICES = {
    0: "Monday",
    1: "Tuesday",
    2: "Wednesday",
    3: "Thursday",
    4: "Friday",
    5: "Saturday",
    6: "Sunday",
}
