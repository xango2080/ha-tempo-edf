"""Calendrier : un évènement « journée entière » par jour Tempo (historique consultable)."""
from __future__ import annotations

from datetime import date, datetime, timedelta

from homeassistant.components.calendar import CalendarEntity, CalendarEvent
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TempoConfigEntry
from .const import COLOR_EMOJI, COLORS
from .entity import TempoEntity
from .tempo import tempo_day


async def async_setup_entry(
    hass: HomeAssistant, entry: TempoConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    async_add_entities([TempoCalendar(entry.runtime_data)])


def _event(day: date, color: str) -> CalendarEvent:
    return CalendarEvent(
        start=day,
        end=day + timedelta(days=1),
        summary=f"{COLOR_EMOJI[color]} {COLORS[color]}",
    )


class TempoCalendar(TempoEntity, CalendarEntity):
    _attr_name = "Calendrier"
    _attr_icon = "mdi:calendar-star"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "calendar")

    @property
    def event(self) -> CalendarEvent | None:
        d, color = self.color_on(0)
        return _event(d, color) if color else None

    async def async_get_events(
        self, hass: HomeAssistant, start_date: datetime, end_date: datetime
    ) -> list[CalendarEvent]:
        start, end = dt_util.as_local(start_date).date(), dt_util.as_local(end_date).date()
        events = []
        for iso, color in sorted(self.coordinator.days.items()):
            d = date.fromisoformat(iso)
            if start <= d <= end:
                events.append(_event(d, color))
        return events
