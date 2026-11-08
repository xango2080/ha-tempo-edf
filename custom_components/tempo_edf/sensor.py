"""Capteurs : couleurs J/J+1, tarif courant, 6 tarifs fixes, compteurs de saison."""
from __future__ import annotations

from typing import Any

from homeassistant.components.sensor import SensorDeviceClass, SensorEntity, SensorStateClass
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from . import TempoConfigEntry
from .const import (
    COLOR_CODE,
    COLOR_EMOJI,
    COLOR_HEX,
    COLORS,
    PERIODS,
    PRICE_UNIT,
    SEASON_TOTALS,
    TARIFFS,
)
from .entity import TempoEntity
from .tempo import season_label, season_status, tempo_day


async def async_setup_entry(
    hass: HomeAssistant, entry: TempoConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c = entry.runtime_data
    entities: list[SensorEntity] = [
        TempoDaySensor(c, "today", "Couleur aujourd'hui", 0),
        TempoDaySensor(c, "tomorrow", "Couleur demain", 1),
        TempoCurrentSensor(c),
        TempoCurrentPriceSensor(c),
        TempoSeasonSensor(c),
    ]
    entities += [TempoRemainingSensor(c, color) for color in SEASON_TOTALS]
    if c.enedis_sync is not None:
        entities.append(TempoEnedisSensor(c))
    entities += [TempoFixedPriceSensor(c, color, period) for color, period in TARIFFS]
    async_add_entities(entities)


class TempoDaySensor(TempoEntity, SensorEntity):
    """Couleur du jour Tempo (J) ou du lendemain (J+1). 'unknown' tant que RTE ne l'a pas publiée."""

    _attr_icon = "mdi:flash"
    # ENUM : l'éditeur d'automatisations propose la liste des états au lieu d'une saisie libre.
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(COLORS.values())  # ["Bleu", "Blanc", "Rouge"]

    def __init__(self, coordinator, key: str, name: str, offset: int) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._offset = offset

    @property
    def native_value(self) -> str | None:
        _, color = self.color_on(self._offset)
        return COLORS[color] if color else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d, color = self.color_on(self._offset)
        attrs: dict[str, Any] = {"date": d.isoformat()}
        if color:
            attrs |= {
                "color": color.lower(),  # blue / white / red
                "color_code": COLOR_CODE[color],
                "emoji": COLOR_EMOJI[color],
                "color_hex": COLOR_HEX[color],
            }
        return attrs


class TempoCurrentSensor(TempoEntity, SensorEntity):
    """Couleur + période en cours, ex: 'Bleu HP'."""

    _attr_name = "Tarif actuel"
    _attr_icon = "mdi:clock-time-eight-outline"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = [f"{name} {period}" for name in COLORS.values() for period in PERIODS]

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "current")

    @property
    def native_value(self) -> str | None:
        _, color = self.color_on(0)
        return f"{COLORS[color]} {self.period_now()}" if color else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        _, color = self.color_on(0)
        period = self.period_now()
        return {
            "period": period,
            "is_hc": period == "HC",
            "is_hp": period == "HP",
            "color": color.lower() if color else None,
        }


class _PriceSensor(TempoEntity, SensorEntity):
    _attr_native_unit_of_measurement = PRICE_UNIT
    _attr_state_class = SensorStateClass.MEASUREMENT  # => statistiques long terme conservées
    _attr_suggested_display_precision = 4
    _attr_icon = "mdi:currency-eur"


class TempoCurrentPriceSensor(_PriceSensor):
    _attr_name = "Prix actuel"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "price_current")

    @property
    def native_value(self) -> float | None:
        _, color = self.color_on(0)
        if not color:
            return None
        return self.prices_today().get(f"{color}_{self.period_now()}")


class TempoFixedPriceSensor(_PriceSensor):
    """Un des 6 tarifs. Pratique pour le tableau de bord Énergie (un compteur par tarif)."""

    def __init__(self, coordinator, color: str, period: str) -> None:
        super().__init__(coordinator, f"price_{color.lower()}_{period.lower()}")
        self._opt = f"{color}_{period}"
        self._attr_name = f"Prix {COLORS[color]} {period}"

    @property
    def native_value(self) -> float | None:
        return self.prices_today().get(self._opt)


class TempoSeasonSensor(TempoEntity, SensorEntity):
    """Saison en cours + jours consommés / restants par couleur."""

    _attr_name = "Saison"
    _attr_icon = "mdi:calendar-range"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "season")

    @property
    def native_value(self) -> str:
        return season_label(tempo_day(dt_util.now()))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        today = tempo_day(dt_util.now())
        res = season_status(self.coordinator.days, today)
        attrs: dict[str, Any] = {
            "history_complete": res["known"] == res["elapsed"],
            "known_days": res["known"],
            "elapsed_days": res["elapsed"],
        }
        for color, n in res["counts"].items():
            name = color.lower()
            attrs[f"{name}_used"] = n
            attrs[f"{name}_remaining"] = self.coordinator.quota(color) - n
        return attrs


COLOR_PLURAL = {"BLUE": "bleus", "WHITE": "blancs", "RED": "rouges"}


class TempoRemainingSensor(TempoEntity, SensorEntity):
    """Jours restants d'une couleur sur la saison (demain déduit dès son annonce).

    'unknown' tant que l'historique de la saison est incomplet : mieux vaut pas de valeur qu'une fausse.
    """

    _attr_native_unit_of_measurement = "jours"
    _attr_state_class = SensorStateClass.MEASUREMENT  # statistiques long terme conservées
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator, color: str) -> None:
        super().__init__(coordinator, f"remaining_{color.lower()}")
        self._color = color
        self._attr_name = f"Jours {COLOR_PLURAL[color]} restants"

    def _status(self) -> dict[str, Any]:
        return season_status(self.coordinator.days, tempo_day(dt_util.now()))

    @property
    def native_value(self) -> int | None:
        res = self._status()
        if res["known"] != res["elapsed"]:
            return None
        return self.coordinator.quota(self._color) - res["counts"][self._color]

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        res = self._status()
        return {
            "quota": self.coordinator.quota(self._color),
            "used": res["counts"][self._color],
            "history_complete": res["known"] == res["elapsed"],
        }


class TempoEnedisSensor(TempoEntity, SensorEntity):
    """Suivi de l'import Enedis : dernier jour complet importé, avec le statut de la dernière synchro."""

    _attr_name = "Enedis dernière donnée"
    _attr_icon = "mdi:transmission-tower-import"
    _attr_device_class = SensorDeviceClass.DATE

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "enedis_last_day")

    @property
    def native_value(self):
        return self.coordinator.enedis_sync.last_day

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        sync = self.coordinator.enedis_sync
        return {
            "status": sync.status,
            "last_run": sync.last_run,
            "imported_days": sync.complete_days,
            "history_start": sync.start_day,
            "unassigned_hours": sync.unassigned_hours,
        }
