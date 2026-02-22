"""Calendar platform for the Erg Energy Scheduler integration."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DEFAULT_SLOT_DURATION, DOMAIN, parse_slot_duration_seconds


def _friendly_name(entity_id: str) -> str:
    """Convert entity_id like 'switch.pool_pump' to 'Pool Pump'."""
    if "." in entity_id:
        entity_id = entity_id.split(".", 1)[1]
    return entity_id.replace("_", " ").title()


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities,
) -> None:
    """Set up Erg calendar from a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]["coordinator"]
    async_add_entities([ErgScheduleCalendar(coordinator, entry)])


class ErgScheduleCalendar(CoordinatorEntity, CalendarEntity):
    """Calendar entity showing the Erg schedule timeline."""

    def __init__(self, coordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._entry = entry
        self._attr_unique_id = f"{entry.entry_id}_erg_schedule_calendar"
        self._attr_name = "Erg Schedule"

    @property
    def name(self) -> str:
        return "Erg Schedule"

    @property
    def event(self) -> CalendarEvent | None:
        """Return the next upcoming event."""
        events = self._build_events()
        if not events:
            return None
        now = datetime.now().astimezone()
        for ev in events:
            if ev.end > now:
                return ev
        return None

    async def async_get_events(
        self,
        hass: HomeAssistant,
        start_date: datetime,
        end_date: datetime,
    ) -> list[CalendarEvent]:
        """Return events within a date range."""
        events = self._build_events()
        return [
            ev
            for ev in events
            if ev.end > start_date and ev.start < end_date
        ]

    def _build_events(self) -> list[CalendarEvent]:
        """Convert schedule assignments into calendar events.

        Groups contiguous slots into single events. A new group starts
        when the gap between consecutive slots exceeds the slot duration.
        """
        data = self.coordinator.data
        if data is None:
            return []

        slot_duration_str = self._entry.options.get(
            "slot_duration", DEFAULT_SLOT_DURATION
        )
        slot_seconds = parse_slot_duration_seconds(slot_duration_str)
        slot_duration = timedelta(seconds=slot_seconds)

        events: list[CalendarEvent] = []

        for assignment in data.get("assignments", []):
            entity_id = assignment.get("entity", "")
            if entity_id.startswith("__"):
                continue

            slots = sorted(
                datetime.fromisoformat(s) for s in assignment.get("slots", [])
            )
            if not slots:
                continue

            friendly = _friendly_name(entity_id)
            run_time = assignment.get("run_time_seconds", 0)
            cost = assignment.get("energy_cost", 0)
            benefit = assignment.get("energy_benefit", 0)
            description = (
                f"Run time: {run_time / 3600:.2f}h, "
                f"Cost: ${cost:.2f}, "
                f"Benefit: ${benefit:.2f}"
            )

            # Group contiguous slots
            group_start = slots[0]
            group_end = slots[0] + slot_duration

            for i in range(1, len(slots)):
                expected_next = group_end
                if slots[i] <= expected_next:
                    # Contiguous — extend the group
                    group_end = slots[i] + slot_duration
                else:
                    # Gap — emit current group, start new one
                    events.append(
                        CalendarEvent(
                            start=group_start,
                            end=group_end,
                            summary=friendly,
                            description=description,
                        )
                    )
                    group_start = slots[i]
                    group_end = slots[i] + slot_duration

            # Emit final group
            events.append(
                CalendarEvent(
                    start=group_start,
                    end=group_end,
                    summary=friendly,
                    description=description,
                )
            )

        events.sort(key=lambda e: e.start)
        return events
