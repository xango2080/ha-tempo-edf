"""Coordinateur : récupère les couleurs Tempo et conserve l'historique sur disque.

Sources, dans l'ordre : API officielle RTE (si identifiants fournis), puis Jour Tempo (gratuit, sans clé).
"""
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
    SEASON_TOTALS,
    STORE_VERSION,
)
from .enedis_api import ConsoApiClient
from .jourtempo_api import JourTempoClient, JourTempoError
from .tempo import has_gaps, parse_calendar, past_season_bounds, season_start, tempo_day

_LOGGER = logging.getLogger(__name__)


class SourcesError(Exception):
    """Aucune source de couleurs n'a répondu."""


class TempoCoordinator(DataUpdateCoordinator[dict[str, str]]):
    """Données : {'YYYY-MM-DD': 'BLUE'|'WHITE'|'RED'}."""

    config_entry: ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: ConfigEntry,
        jourtempo: JourTempoClient,
        rte: RteClient | None = None,
    ) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(hours=POLL_INTERVAL_HOURS),
        )
        self._jourtempo = jourtempo
        self._rte = rte
        self.enedis: ConsoApiClient | None = None  # renseigné par __init__ si token + PRM
        self.enedis_sync = None  # EnedisSync, créé par __init__ si Enedis est configuré
        # Stocké dans .storage/ : survit aux purges du recorder et est inclus dans les sauvegardes.
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.{entry.entry_id}")
        self.days: dict[str, str] = {}
        self.quotas: dict[str, int] = {}  # lus dans tempo.json ; SEASON_TOTALS sert de valeur par défaut
        self._backfilled = 0  # nombre de saisons passées déjà rapatriées
        self._loaded = False
        self._last_full_fetch: datetime | None = None

    def quota(self, color: str) -> int:
        """Quota de jours de la saison pour une couleur (API Jour Tempo, sinon valeur par défaut)."""
        return self.quotas.get(color, SEASON_TOTALS[color])

    async def _async_save(self) -> None:
        await self._store.async_save(
            {"days": self.days, "quotas": self.quotas, "backfilled_seasons": self._backfilled}
        )

    async def _async_fetch_current(self, start_day, today) -> tuple[dict[str, str], dict[str, int]]:
        """RTE officiel d'abord s'il est configuré, sinon (ou en cas d'échec) Jour Tempo."""
        errors: list[str] = []
        if self._rte is not None:
            tz = dt_util.DEFAULT_TIME_ZONE
            start = datetime.combine(start_day, time.min, tzinfo=tz)
            end = datetime.combine(today + timedelta(days=2), time.min, tzinfo=tz)
            try:
                new = parse_calendar(await self._rte.async_get_calendars(start, end))
                if new:
                    return new, {}
                errors.append("RTE : réponse vide")
            except (RteAuthError, RteApiError) as err:
                errors.append(f"RTE : {err}")
        try:
            return await self._jourtempo.async_get_current()
        except JourTempoError as err:
            errors.append(f"Jour Tempo : {err}")
        raise SourcesError(" ; ".join(errors))

    async def _async_update_data(self) -> dict[str, str]:
        if not self._loaded:
            stored = await self._store.async_load()
            if stored:
                self.days = dict(stored.get("days", {}))
                self.quotas = {k: int(v) for k, v in stored.get("quotas", {}).items()}
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
            try:
                new, quotas = await self._async_fetch_current(start_day, today)
            except SourcesError as err:
                # Panne : si la couleur du jour est déjà stockée, les capteurs restent disponibles.
                if today.isoformat() in self.days:
                    _LOGGER.warning("Sources Tempo indisponibles, données locales utilisées : %s", err)
                    return self.days
                raise UpdateFailed(str(err)) from err

            if full_ok:
                self._last_full_fetch = now
            days_changed = any(self.days.get(k) != v for k, v in new.items())
            quotas_changed = any(self.quotas.get(k) != v for k, v in quotas.items())
            if days_changed or quotas_changed:
                self.days.update(new)
                self.quotas.update(quotas)
                await self._async_save()
        return self.days

    async def async_backfill(self) -> None:
        """Rapatrie les saisons passées en tâche de fond.

        Jour Tempo : une seule requête (CSV depuis 2014). Sinon, RTE officiel : une requête par saison.
        La progression est persistée.
        """
        wanted = int(self.config_entry.options.get(CONF_HISTORY_SEASONS, DEFAULT_HISTORY_SEASONS))
        if self._backfilled >= wanted:
            return
        today = tempo_day(dt_util.now())

        try:
            history = await self._jourtempo.async_get_history()
        except JourTempoError as err:
            _LOGGER.warning("Historique Jour Tempo indisponible : %s", err)
        else:
            oldest, _ = past_season_bounds(today, wanted)
            self.days.update({d: c for d, c in history.items() if d >= oldest.isoformat()})
            self._backfilled = wanted
            await self._async_save()
            self.async_update_listeners()
            _LOGGER.info("Historique importé depuis %s (%s jours en base)", oldest, len(self.days))
            return

        if self._rte is None:
            return  # réessai au prochain redémarrage / changement d'options
        tz = dt_util.DEFAULT_TIME_ZONE
        while self._backfilled < wanted:
            n = self._backfilled + 1
            first, last = past_season_bounds(today, n)
            start = datetime.combine(first, time.min, tzinfo=tz)
            end = datetime.combine(last, time.min, tzinfo=tz)
            try:
                payload = await self._rte.async_get_calendars(start, end)
            except (RteApiError, RteAuthError) as err:
                _LOGGER.warning("Historique saison %s-%s non récupéré (nouvel essai plus tard) : %s",
                                first.year, last.year, err)
                return
            new = parse_calendar(payload)
            self.days.update(new)
            self._backfilled = n
            await self._async_save()
            self.async_update_listeners()
            await asyncio.sleep(2)  # ménage le quota de l'API RTE
