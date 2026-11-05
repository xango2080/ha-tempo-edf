"""Coordinateur : récupère le calendrier RTE et conserve l'historique sur disque."""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .api import RteApiError, RteAuthError, RteClient
from .const import (
    CONF_HISTORY_SEASONS,
    DEFAULT_HISTORY_SEASONS,
    DOMAIN,
    POLL_INTERVAL_HOURS,
    STORE_VERSION,
)
from .tempo import has_gaps, parse_calendar, past_season_bounds, season_start, tempo_day

_LOGGER = logging.getLogger(__name__)


class TempoCoordinator(DataUpdateCoordinator[dict[str, str]]):
    """Données : {'YYYY-MM-DD': 'BLUE'|'WHITE'|'RED'} (saison en cours + saisons rapatriées)."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: RteClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=POLL_INTERVAL_HOURS),
        )
        self._client = client
        # Stocké dans .storage/ : survit aux purges du recorder et est inclus dans les sauvegardes.
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.days: dict[str, str] = {}
        self._backfilled = 0  # nombre de saisons passées déjà rapatriées
        self._loaded = False
        self._last_full_fetch: datetime | None = None

    async def _async_save(self) -> None:
        await self._store.async_save({"days": self.days, "backfilled_seasons": self._backfilled})

    async def _async_update_data(self) -> dict[str, str]:
        if not self._loaded:
            stored = await self._store.async_load()
            if stored:
                self.days = dict(stored.get("days", {}))
                self._backfilled = int(stored.get("backfilled_seasons", 0))
            self._loaded = True

        now = dt_util.now()
        today = tempo_day(now)
        tomorrow = today + timedelta(days=1)

        missing_recent = today.isoformat() not in self.days or tomorrow.isoformat() not in self.days
        gaps = has_gaps(self.days, today)
        # Rattrapage complet de la saison au plus 1 fois / 24 h
        full_ok = gaps and (
            self._last_full_fetch is None or now - self._last_full_fetch > timedelta(hours=24)
        )

        if missing_recent or full_ok:
            start_day = season_start(today) if full_ok else today
            tz = dt_util.DEFAULT_TIME_ZONE
            start = datetime.combine(start_day, time.min, tzinfo=tz)
            end = datetime.combine(today + timedelta(days=2), time.min, tzinfo=tz)
            try:
                payload = await self._client.async_get_calendars(start, end)
            except RteAuthError as err:
                raise UpdateFailed(f"Identifiants RTE refusés : {err}") from err
            except RteApiError as err:
                if today.isoformat() in self.days:
                    _LOGGER.warning("RTE injoignable, données locales utilisées : %s", err)
                    return self.days
                raise UpdateFailed(str(err)) from err

            if full_ok:
                self._last_full_fetch = now
            new = parse_calendar(payload)
            if new and any(self.days.get(k) != v for k, v in new.items()):
                self.days.update(new)
                await self._async_save()
        return self.days

    async def async_backfill(self) -> None:
        """Rapatrie les saisons passées, une requête par saison, en tâche de fond.

        Progression persistée : après un redémarrage ou une erreur, on reprend où on s'est arrêté.
        """
        wanted = int(self.config_entry.options.get(CONF_HISTORY_SEASONS, DEFAULT_HISTORY_SEASONS))
        today = tempo_day(dt_util.now())
        tz = dt_util.DEFAULT_TIME_ZONE
        while self._backfilled < wanted:
            n = self._backfilled + 1
            first, last = past_season_bounds(today, n)
            start = datetime.combine(first, time.min, tzinfo=tz)
            end = datetime.combine(last, time.min, tzinfo=tz)
            try:
                payload = await self._client.async_get_calendars(start, end)
            except (RteApiError, RteAuthError) as err:
                _LOGGER.warning("Historique saison %s-%s non récupéré (nouvel essai plus tard) : %s",
                                first.year, last.year, err)
                return
            new = parse_calendar(payload)
            if not new:
                _LOGGER.info("RTE ne renvoie aucune donnée pour la saison %s-%s", first.year, last.year)
            self.days.update(new)
            self._backfilled = n
            await self._async_save()
            self.async_update_listeners()
            _LOGGER.info("Saison %s-%s rapatriée : %s jours", first.year, last.year, len(new))
            await asyncio.sleep(2)  # ménage le quota de l'API RTE
