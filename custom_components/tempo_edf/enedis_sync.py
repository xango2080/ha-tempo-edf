"""Synchronisation Enedis : courbe de charge -> statistiques horaires par tarif pour la section Énergie.

Budget d'appels volontairement minimal (Conso API : 1 requête/jour conseillée, 6 h-10 h, heure non ronde) :
  - régime normal : 1 requête par jour (la veille), à un créneau stable dérivé du PRM entre 08:15 et 09:59 ;
  - 1 seul réessai l'après-midi si la veille manque encore ;
  - rattrapage : tranches de 6 jours, au plus 6 requêtes par synchronisation, le reste les jours suivants ;
  - arrêt immédiat sur toute erreur, sans boucle de nouvelles tentatives.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from datetime import date, datetime, timedelta
from typing import Any

from homeassistant.components.recorder.models import StatisticMetaData
from homeassistant.components.recorder.statistics import async_add_external_statistics
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .const import (
    COLORS,
    CONF_ENEDIS_HISTORY_DAYS,
    CONF_ENEDIS_PRM,
    CONF_TARIFFS,
    DEFAULT_ENEDIS_HISTORY_DAYS,
    DOMAIN,
    LOAD_CURVE_TYPE,
    MAX_REQUESTS_PER_HOUR,
    MAX_REQUESTS_PER_RUN,
    SYNC_CHUNK_DAYS,
    SYNC_PAUSE_SECONDS,
)
from .enedis_api import ConsoApiClient, EnedisApiError, EnedisAuthError
from .enedis_parse import load_curve_to_intervals
from .enedis_stats import (
    build_series,
    day_of_hour,
    group_runs,
    hourly_from_intervals,
    hours_per_day,
    last_complete_day,
    missing_days,
    parse_hour_key,
    schedule_slots,
)
from .tariffs import DEFAULT_TARIFFS

_LOGGER = logging.getLogger(__name__)
STORE_VERSION = 1
PUBLISH_TAIL = timedelta(hours=72)  # publication quotidienne : seulement les dernières heures


def _metadata(stat_id: str, name: str, unit: str, unit_class: str | None) -> StatisticMetaData:
    """Métadonnées compatibles avec plusieurs versions de Home Assistant (champs détectés)."""
    fields = getattr(StatisticMetaData, "__annotations__", {})
    meta: dict[str, Any] = {
        "has_sum": True,
        "name": name,
        "source": DOMAIN,
        "statistic_id": stat_id,
        "unit_of_measurement": unit,
    }
    if "mean_type" in fields:
        from homeassistant.components.recorder.models import StatisticMeanType

        meta["mean_type"] = StatisticMeanType.NONE
    if "has_mean" in fields:
        meta["has_mean"] = False
    if "unit_class" in fields:
        meta["unit_class"] = unit_class
    return meta  # type: ignore[return-value]


class EnedisSync:
    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, coordinator, client: ConsoApiClient) -> None:
        self.hass = hass
        self.entry = entry
        self.coordinator = coordinator
        self._client = client
        self._store: Store[dict[str, Any]] = Store(hass, STORE_VERSION, f"{DOMAIN}.enedis_{entry.entry_id}")
        self.hourly: dict[str, float] = {}      # {'2026-11-05T23' (heure UTC): kWh}
        self.unavailable: set[str] = set()       # jours anciens sans aucune donnée chez Enedis
        self.start_day: str | None = None
        self.last_run: str | None = None
        self.status = "Jamais synchronisé"
        self.unassigned_hours = 0
        self.last_manual: datetime | None = None
        self._lock = asyncio.Lock()
        self._requests: deque[float] = deque()
        self._auth_failed = False
        self._full_pending = True  # 1re publication complète ; ensuite seulement la queue, sauf données plus anciennes

    # ---------- cycle de vie ----------
    async def async_setup(self) -> None:
        stored = await self._store.async_load() or {}
        self.hourly = {k: float(v) for k, v in (stored.get("hourly") or {}).items()}
        self.unavailable = set(stored.get("unavailable") or [])
        self.start_day = stored.get("start_day")
        self.last_run = stored.get("last_run")
        self.status = stored.get("status") or self.status

        morning, afternoon = schedule_slots(self.entry.options[CONF_ENEDIS_PRM])
        for slot, mode in ((morning, "daily"), (afternoon, "retry")):
            self.entry.async_on_unload(
                async_track_time_change(
                    self.hass, self._make_callback(mode), hour=slot[0], minute=slot[1], second=slot[2]
                )
            )
        _LOGGER.info("Synchro Enedis planifiée : %02d:%02d:%02d puis réessai %02d:%02d:%02d", *morning, *afternoon)
        self.entry.async_create_background_task(self.hass, self._startup(), f"{DOMAIN}_enedis_startup")

    def _make_callback(self, mode: str):
        @callback
        def _cb(_now) -> None:
            self.entry.async_create_background_task(
                self.hass, self.async_sync(mode), f"{DOMAIN}_enedis_{mode}"
            )

        return _cb

    async def _startup(self) -> None:
        if self.last_run is None:
            await self.async_sync("initial")  # une seule fois : premier rattrapage borné
        else:
            await self.async_publish(full=True)
            self.coordinator.async_update_listeners()

    # ---------- budget d'appels ----------
    def _budget_ok(self) -> bool:
        now = time.monotonic()
        while self._requests and now - self._requests[0] > 3600:
            self._requests.popleft()
        return len(self._requests) < MAX_REQUESTS_PER_HOUR

    # ---------- synchronisation ----------
    async def async_sync(self, mode: str = "daily") -> dict[str, Any]:
        async with self._lock:
            summary = await self._sync_locked(mode)
        self.coordinator.async_update_listeners()
        return summary

    async def _sync_locked(self, mode: str) -> dict[str, Any]:
        if self._auth_failed and mode != "manual":
            return {"status": self.status, "requests": 0}
        if mode == "manual":
            self._auth_failed = False
            self.last_manual = dt_util.now()

        today = dt_util.now().date()
        yesterday = today - timedelta(days=1)
        wanted = today - timedelta(days=int(self.entry.options.get(CONF_ENEDIS_HISTORY_DAYS, DEFAULT_ENEDIS_HISTORY_DAYS)))
        start = min(date.fromisoformat(self.start_day), wanted) if self.start_day else wanted
        self.start_day = start.isoformat()

        missing = missing_days(self.hourly, start, yesterday, self.unavailable)
        if mode == "retry":
            missing = [d for d in missing if d == yesterday]
        runs = sorted(group_runs(missing, SYNC_CHUNK_DAYS), reverse=True)  # les plus récents d'abord
        limit = 1 if mode == "retry" else MAX_REQUESTS_PER_RUN

        requests = 0
        error: str | None = None
        prev_last = parse_hour_key(max(self.hourly)) if self.hourly else None
        for first, last in runs[:limit]:
            if not self._budget_ok():
                error = "plafond horaire interne atteint"
                break
            if requests:
                await asyncio.sleep(SYNC_PAUSE_SECONDS)
            self._requests.append(time.monotonic())
            requests += 1
            try:
                payload = await self._client.async_get(LOAD_CURVE_TYPE, first, last + timedelta(days=1))
            except EnedisAuthError as err:
                self._auth_failed = True
                error = f"token refusé ({err}) : refaire le consentement sur conso.boris.sh"
                break
            except EnedisApiError as err:
                error = str(err)
                break
            new = hourly_from_intervals(load_curve_to_intervals(payload))
            self.hourly.update(new)
            # Des heures plus anciennes que la queue décalent tous les cumuls suivants : tout republier.
            if new and (prev_last is None or min(new) < (prev_last - PUBLISH_TAIL).strftime("%Y-%m-%dT%H")):
                self._full_pending = True
            got = {day_of_hour(k) for k in new}
            d = first
            while d <= last:
                if d not in got and d < today - timedelta(days=3):
                    self.unavailable.add(d.isoformat())  # ancien et vide : on ne redemande plus
                d += timedelta(days=1)

        after = missing_days(self.hourly, start, yesterday, self.unavailable)
        self.last_run = dt_util.now().isoformat(timespec="seconds")
        if error:
            self.status = f"Erreur : {error}"
        elif after:
            self.status = f"{len(after)} jour(s) restant à importer"
        else:
            self.status = "À jour"
        await self._async_save()
        if requests:
            await self.async_publish(full=False)
        _LOGGER.info("Synchro Enedis (%s) : %s requête(s), %s", mode, requests, self.status)
        return {"mode": mode, "requests": requests, "days_remaining": len(after), "status": self.status}

    async def _async_save(self) -> None:
        await self._store.async_save(
            {
                "hourly": self.hourly,
                "unavailable": sorted(self.unavailable),
                "start_day": self.start_day,
                "last_run": self.last_run,
                "status": self.status,
            }
        )

    # ---------- publication vers la section Énergie ----------
    async def async_publish(self, full: bool) -> None:
        """(Re)publie les statistiques externes : une série kWh et une série € par tarif."""
        if not self.hourly:
            return
        tariffs = self.entry.options.get(CONF_TARIFFS) or DEFAULT_TARIFFS
        full = full or self._full_pending
        series, self.unassigned_hours = build_series(self.hourly, self.coordinator.days, tariffs)
        last = parse_hour_key(max(self.hourly))
        cutoff = None if full else last - PUBLISH_TAIL
        for (color, period), kinds in series.items():
            slug = f"{color.lower()}_{period.lower()}"
            for kind, prefix, unit, unit_class, label in (
                ("kwh", "conso", "kWh", "energy", "consommation"),
                ("eur", "cout", "EUR", None, "coût"),
            ):
                rows = [
                    {"start": h, "sum": s, "state": s}
                    for h, s in kinds[kind]
                    if cutoff is None or h >= cutoff
                ]
                if rows:
                    meta = _metadata(
                        f"{DOMAIN}:{prefix}_{slug}", f"Tempo {COLORS[color]} {period} ({label})", unit, unit_class
                    )
                    async_add_external_statistics(self.hass, meta, rows)
        self._full_pending = False

    # ---------- état pour le capteur de suivi ----------
    @property
    def last_day(self) -> date | None:
        return last_complete_day(self.hourly)

    @property
    def complete_days(self) -> int:
        return sum(1 for n in hours_per_day(self.hourly).values() if n >= 23)
