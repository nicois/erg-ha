"""Constants for the Erg Energy Scheduler integration."""

from __future__ import annotations

import re

DOMAIN = "erg"
PLATFORMS: list[str] = ["sensor", "binary_sensor", "calendar"]

DEFAULT_PORT = 8080
DEFAULT_SLOT_DURATION = "5m"
DEFAULT_HORIZON_HOURS = 24
DEFAULT_UPDATE_INTERVAL_MINUTES = 15

_DURATION_RE = re.compile(r"(?:(\d+)h)?(?:(\d+)m)?(?:(\d+)s)?$")


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
