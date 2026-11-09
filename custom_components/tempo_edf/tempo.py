"""Logique pure (sans dépendance Home Assistant) : saisons, jours Tempo, parsing."""
from __future__ import annotations

import csv
import io
from datetime import date, datetime, timedelta
from typing import Any

from .const import ANNOUNCE_HOUR, ANNOUNCE_MINUTE, COLORS, DAY_START_HOUR, HC_START_HOUR


def season_start(d: date) -> date:
    """Premier jour (1er septembre) de la saison contenant la date d."""
    year = d.year if d.month >= 9 else d.year - 1
    return date(year, 9, 1)


def season_label(d: date) -> str:
    start = season_start(d)
    return f"{start.year}-{start.year + 1}"


def tempo_day(now: datetime) -> date:
    """Jour Tempo en cours : la journée change à 06:00."""
    return (now - timedelta(hours=DAY_START_HOUR)).date()


def is_hc(now: datetime) -> bool:
    return now.hour >= HC_START_HOUR or now.hour < DAY_START_HOUR


def parse_calendar(payload: Any) -> dict[str, str]:
    """Transforme la réponse RTE en {'YYYY-MM-DD': 'BLUE'|'WHITE'|'RED'}."""
    out: dict[str, str] = {}
    try:
        values = payload["tempo_like_calendars"]["values"]
    except (KeyError, TypeError):
        return out
    for item in values or []:
        color = str(item.get("value", "")).upper()
        day = str(item.get("start_date", ""))[:10]
        if color in COLORS and len(day) == 10:
            out[day] = color
    return out


def daterange(start: date, end: date):
    """Dates de start à end inclus."""
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def count_days(days: dict[str, str], today: date) -> dict[str, Any]:
    """Compte les jours connus de la saison jusqu'à today inclus."""
    start = season_start(today)
    counts = {"BLUE": 0, "WHITE": 0, "RED": 0}
    elapsed = known = 0
    for d in daterange(start, today):
        elapsed += 1
        color = days.get(d.isoformat())
        if color in counts:
            counts[color] += 1
            known += 1
    return {"counts": counts, "elapsed": elapsed, "known": known}


def season_status(days: dict[str, str], today: date) -> dict[str, Any]:
    """Comme count_days, mais le jour de demain est déduit dès qu'il est annoncé."""
    tomorrow = today + timedelta(days=1)
    upto = tomorrow if tomorrow.isoformat() in days else today
    return count_days(days, upto)


def has_gaps(days: dict[str, str], today: date) -> bool:
    return any(d.isoformat() not in days for d in daterange(season_start(today), today))


def past_season_bounds(today: date, n: int) -> tuple[date, date]:
    """n-ième saison passée (n=1 : la précédente) -> (1er sept., 1er sept. suivant, exclu)."""
    start = date(season_start(today).year - n, 9, 1)
    return start, date(start.year + 1, 9, 1)


FR_TO_CODE = {"bleu": "BLUE", "blanc": "WHITE", "rouge": "RED"}


def parse_jourtempo_json(payload: Any) -> dict[str, str]:
    """tempo.json (calendrier de la saison + aujourdhui/demain) -> {'YYYY-MM-DD': 'BLUE'|...}."""
    out: dict[str, str] = {}
    if not isinstance(payload, dict):
        return out
    calendar = payload.get("calendrier")
    if isinstance(calendar, dict):
        for day, color in calendar.items():
            code = FR_TO_CODE.get(str(color).strip().lower())
            if code and len(str(day)) == 10:
                out[str(day)] = code
    for key in ("aujourdhui", "demain"):  # "inconnu" est ignoré (absent de FR_TO_CODE)
        item = payload.get(key)
        if isinstance(item, dict):
            code = FR_TO_CODE.get(str(item.get("code", "")).strip().lower())
            day = str(item.get("date", ""))
            if code and len(day) == 10:
                out[day] = code
    return out


def parse_jourtempo_csv(text: str) -> dict[str, str]:
    """tempo-historique.csv (colonnes date, couleur, saison) -> {'YYYY-MM-DD': 'BLUE'|...}."""
    out: dict[str, str] = {}
    reader = csv.DictReader(io.StringIO(text.lstrip("\ufeff")))
    date_col = "date" if reader.fieldnames and "date" in reader.fieldnames else (reader.fieldnames or [None])[0]
    for row in reader:
        code = FR_TO_CODE.get(str(row.get("couleur", "")).strip().lower())
        day = str(row.get(date_col, "")).strip()[:10]
        if code and len(day) == 10:
            out[day] = code
    return out


def parse_jourtempo_quotas(payload: Any) -> dict[str, int]:
    """saison.compteurs.<couleur>.quota de tempo.json -> {'BLUE': 300, ...} (vide si absent)."""
    out: dict[str, int] = {}
    try:
        counters = payload["saison"]["compteurs"]
    except (KeyError, TypeError):
        return out
    for fr, code in FR_TO_CODE.items():
        try:
            quota = int(counters[fr]["quota"])
        except (KeyError, TypeError, ValueError):
            continue
        if quota > 0:
            out[code] = quota
    return out


def needs_colors(days: dict[str, str], today: date, now_local: datetime) -> bool:
    """Faut-il interroger une source ? Oui si la couleur du jour manque, ou si celle de demain manque
    ET a déjà pu être annoncée (la veille, ou aujourd'hui à partir de 10 h 30)."""
    if today.isoformat() not in days:
        return True
    tomorrow = today + timedelta(days=1)
    if tomorrow.isoformat() in days:
        return False
    if tomorrow <= now_local.date():  # entre 0 h et 6 h : le « demain » Tempo est le jour civil en cours
        return True
    return (now_local.hour, now_local.minute) >= (ANNOUNCE_HOUR, ANNOUNCE_MINUTE)
