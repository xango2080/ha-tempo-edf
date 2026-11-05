"""Entité de base."""
from __future__ import annotations

from datetime import date, timedelta

from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .coordinator import TempoCoordinator
from .tempo import is_hc, tempo_day


class TempoEntity(CoordinatorEntity[TempoCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: TempoCoordinator, key: str) -> None:
        super().__init__(coordinator)
        entry_id = coordinator.config_entry.entry_id
        self._attr_unique_id = f"{entry_id}_{key}"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry_id)},
            name="EDF Tempo",
            manufacturer="RTE / EDF",
            entry_type=DeviceEntryType.SERVICE,
        )

    @property
    def entry_options(self) -> dict:
        return self.coordinator.config_entry.options

    def color_on(self, offset: int = 0) -> tuple[date, str | None]:
        """(jour Tempo, couleur) pour aujourd'hui (+offset jours)."""
        d = tempo_day(dt_util.now()) + timedelta(days=offset)
        return d, self.coordinator.days.get(d.isoformat())

    @staticmethod
    def period_now() -> str:
        return "HC" if is_hc(dt_util.now()) else "HP"
