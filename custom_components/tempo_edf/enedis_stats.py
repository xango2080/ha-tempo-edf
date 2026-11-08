"""Logique pure de l'import Enedis : heures, jours manquants, séries cumulées par tarif, créneaux d'appel."""
from __future__ import annotations

import hashlib
from collections import Counter
from datetime import UTC, date, datetime, timedelta
from typing import Any

from .const import TARIFFS
from .enedis_parse import PARIS
from .tariffs import tariff_at
from .tempo import is_hc, tempo_day

HOURS_COMPLETE = 23  # un jour est « complet » s'il a au moins 23 heures (jour de changement d'heure)


def hour_key(dt: datetime) -> str:
    """Début d'heure UTC -> '2026-11-05T23'."""
    return dt.astimezone(UTC).strftime("%Y-%m-%dT%H")


def parse_hour_key(key: str) -> datetime:
    return datetime.strptime(key, "%Y-%m-%dT%H").replace(tzinfo=UTC)


def hourly_from_intervals(intervals: list[tuple[datetime, datetime, float]]) -> dict[str, float]:
    """Regroupe les demi-heures en heures : {'2026-11-05T23': kWh}."""
    out: dict[str, float] = {}
    for start, _end, kwh in intervals:
        key = hour_key(start.astimezone(UTC).replace(minute=0, second=0, microsecond=0))
        out[key] = round(out.get(key, 0.0) + kwh, 6)
    return out


def hours_per_day(hourly: dict[str, float]) -> Counter:
    counts: Counter = Counter()
    for key in hourly:
        counts[parse_hour_key(key).astimezone(PARIS).date()] += 1
    return counts


def day_of_hour(key: str) -> date:
    return parse_hour_key(key).astimezone(PARIS).date()


def missing_days(hourly: dict[str, float], start: date, end: date, unavailable: set[str]) -> list[date]:
    """Jours de [start, end] sans données complètes et pas déclarés indisponibles."""
    counts = hours_per_day(hourly)
    out, d = [], start
    while d <= end:
        if counts.get(d, 0) < HOURS_COMPLETE and d.isoformat() not in unavailable:
            out.append(d)
        d += timedelta(days=1)
    return out


def group_runs(days: list[date], max_len: int) -> list[tuple[date, date]]:
    """Regroupe les jours consécutifs en tranches d'au plus max_len jours (une requête par tranche)."""
    runs: list[tuple[date, date]] = []
    for d in sorted(days):
        if runs and d == runs[-1][1] + timedelta(days=1) and (d - runs[-1][0]).days < max_len:
            runs[-1] = (runs[-1][0], d)
        else:
            runs.append((d, d))
    return runs


def last_complete_day(hourly: dict[str, float]) -> date | None:
    days = [d for d, n in hours_per_day(hourly).items() if n >= HOURS_COMPLETE]
    return max(days) if days else None


def build_series(
    hourly: dict[str, float], colors: dict[str, str], tariffs: list[dict[str, Any]]
) -> tuple[dict[tuple[str, str], dict[str, list[tuple[datetime, float]]]], int]:
    """Séries cumulées par tarif : {(couleur, période): {'kwh': [(heure_utc, somme)], 'eur': [...]}}.

    Une ligne par heure et par série (variation nulle hors du tarif concerné). Retourne aussi le nombre
    d'heures consommées dont la couleur du jour est inconnue (non attribuées).
    """
    series = {t: {"kwh": [], "eur": []} for t in TARIFFS}
    if not hourly:
        return series, 0
    keys = sorted(hourly)
    hour, last = parse_hour_key(keys[0]), parse_hour_key(keys[-1])
    sum_kwh = {t: 0.0 for t in TARIFFS}
    sum_eur = {t: 0.0 for t in TARIFFS}
    unassigned = 0
    while hour <= last:
        local = hour.astimezone(PARIS)
        kwh = hourly.get(hour_key(hour), 0.0)
        if kwh:
            color = colors.get(tempo_day(local).isoformat())
            if color:
                tariff = (color, "HC" if is_hc(local) else "HP")
                prices = tariff_at(tariffs, local.date()) or {}
                sum_kwh[tariff] += kwh
                sum_eur[tariff] += kwh * prices.get(f"{tariff[0]}_{tariff[1]}", 0.0)
            else:
                unassigned += 1
        for t in TARIFFS:
            series[t]["kwh"].append((hour, round(sum_kwh[t], 5)))
            series[t]["eur"].append((hour, round(sum_eur[t], 5)))
        hour += timedelta(hours=1)
    return series, unassigned


def schedule_slots(prm: str) -> tuple[tuple[int, int, int], tuple[int, int, int]]:
    """Créneaux d'appel stables mais non ronds, dérivés du PRM : matin 08:15-09:59, réessai 14:00-14:59."""
    d = hashlib.sha256(prm.encode()).digest()
    morning = 8 * 60 + 15 + int.from_bytes(d[0:2], "big") % 105
    afternoon = 14 * 60 + int.from_bytes(d[2:4], "big") % 60
    return (
        (morning // 60, morning % 60, d[4] % 60),
        (afternoon // 60, afternoon % 60, d[5] % 60),
    )
