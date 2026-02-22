"""Job entity definitions for the Erg Energy Scheduler integration.

Each job is represented as an ErgJobEntity (SensorEntity + RestoreEntity) so
that automations can dynamically create, modify, and delete jobs at runtime.
Job configuration is stored as flat entity attributes.
"""

from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorEntity
from homeassistant.helpers.restore_state import RestoreEntity

from .const import make_job_device_info


class ErgJobEntity(RestoreEntity, SensorEntity):
    """Sensor entity representing a single Erg job definition."""

    _attr_icon = "mdi:briefcase-clock"

    def __init__(self, entry_id: str, attrs: dict[str, Any]) -> None:
        sanitized = attrs["entity_id"].replace(".", "_")
        self._attr_unique_id = f"{entry_id}_job_{sanitized}"
        self._attr_name = f"Erg Job {attrs['entity_id']}"
        self._job_attrs = dict(attrs)
        self._entry_id = entry_id

    @property
    def device_info(self):
        return make_job_device_info(self._job_attrs["entity_id"])

    @property
    def native_value(self) -> str:
        return "enabled" if self._job_attrs.get("enabled", True) else "disabled"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return dict(self._job_attrs)

    def update_attributes(self, new_attrs: dict[str, Any]) -> None:
        """Merge new attributes and write state."""
        self._job_attrs.update(new_attrs)
        self.async_write_ha_state()

    async def async_added_to_hass(self) -> None:
        """Restore state on startup."""
        last_state = await self.async_get_last_state()
        if last_state and last_state.attributes:
            self._job_attrs = dict(last_state.attributes)

    @classmethod
    def from_job_dict(cls, entry_id: str, job: dict[str, Any]) -> ErgJobEntity:
        """Create from the nested job dict format (for migration).

        Flattens the recurrence sub-dict into top-level attributes and adds
        a ``job_type`` field.
        """
        attrs: dict[str, Any] = {
            "entity_id": job["entity_id"],
            "ac_power": job.get("ac_power", 0.0),
            "dc_power": job.get("dc_power", 0.0),
            "force": job.get("force", False),
            "benefit": job.get("benefit", 0.0),
            "enabled": job.get("enabled", True),
        }

        recurrence = job.get("recurrence")
        if recurrence is not None:
            attrs["job_type"] = "recurring"
            attrs["frequency"] = recurrence.get("frequency", "daily")
            attrs["time_window_start"] = recurrence.get("time_window_start", "09:00")
            attrs["time_window_end"] = recurrence.get("time_window_end", "17:00")
            attrs["maximum_duration"] = recurrence.get("maximum_duration", "1h")
            attrs["minimum_duration"] = recurrence.get("minimum_duration", "0s")
            attrs["minimum_burst"] = recurrence.get("minimum_burst", "0s")
            if recurrence.get("frequency") == "weekly":
                attrs["day_of_week"] = recurrence.get("day_of_week", 0)
            elif recurrence.get("frequency") == "custom":
                attrs["days_of_week"] = recurrence.get("days_of_week", [])
        else:
            attrs["job_type"] = "oneshot"
            attrs["start"] = job.get("start", "")
            attrs["finish"] = job.get("finish", "")
            attrs["maximum_duration"] = job.get("maximum_duration", "1h")
            attrs["minimum_duration"] = job.get("minimum_duration", "0s")
            attrs["minimum_burst"] = job.get("minimum_burst", "0s")

        return cls(entry_id, attrs)


def job_entity_to_dict(entity: ErgJobEntity) -> dict[str, Any]:
    """Reconstruct the nested job dict that expand_recurring_jobs() expects.

    Reads flat attributes from the entity and rebuilds the nested recurrence
    dict (or sets it to None for one-shot jobs).
    """
    attrs = entity.extra_state_attributes
    base: dict[str, Any] = {
        "entity_id": attrs["entity_id"],
        "ac_power": attrs.get("ac_power", 0.0),
        "dc_power": attrs.get("dc_power", 0.0),
        "force": attrs.get("force", False),
        "benefit": attrs.get("benefit", 0.0),
        "enabled": attrs.get("enabled", True),
    }

    if attrs.get("job_type") == "recurring":
        base["recurrence"] = {
            "frequency": attrs.get("frequency", "daily"),
            "time_window_start": attrs.get("time_window_start", "09:00"),
            "time_window_end": attrs.get("time_window_end", "17:00"),
            "maximum_duration": attrs.get("maximum_duration", "1h"),
            "minimum_duration": attrs.get("minimum_duration", "0s"),
            "minimum_burst": attrs.get("minimum_burst", "0s"),
        }
        if attrs.get("frequency") == "weekly":
            base["recurrence"]["day_of_week"] = attrs.get("day_of_week", 0)
        elif attrs.get("frequency") == "custom":
            base["recurrence"]["days_of_week"] = attrs.get("days_of_week", [])
    else:
        base["recurrence"] = None
        base["start"] = attrs.get("start", "")
        base["finish"] = attrs.get("finish", "")
        base["maximum_duration"] = attrs.get("maximum_duration", "1h")
        base["minimum_duration"] = attrs.get("minimum_duration", "0s")
        base["minimum_burst"] = attrs.get("minimum_burst", "0s")

    return base
