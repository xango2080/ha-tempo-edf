"""Logique pure (sans dépendance Home Assistant) : saisons, jours Tempo, parsing."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from .const import COLORS, DAY_START_HOUR, HC_START_HOUR


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


def has_gaps(days: dict[str, str], today: date) -> bool:
    return any(d.isoformat() not in days for d in daterange(season_start(today), today))


def past_season_bounds(today: date, n: int) -> tuple[date, date]:
    """n-ième saison passée (n=1 : la précédente) -> (1er sept., 1er sept. suivant, exclu)."""
    start = date(season_start(today).year - n, 9, 1)
    return start, date(start.year + 1, 9, 1)
