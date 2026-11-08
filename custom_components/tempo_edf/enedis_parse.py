"""Lecture des réponses Enedis « Mesure synchrone V2 » (logique pure, testable sans HA).

HYPOTHÈSES NON VÉRIFIÉES (Enedis ne permet pas de tester avant bascule, cf. PR Gladys #246) :
  - forme : {"grandeur": [{"grandeurMetier": "CONS", "points": [{"d": ..., "v": ...}]}]}  (documentée)
  - courbe de charge : v = puissance moyenne en W sur le pas, d = FIN d'intervalle (comme la v5)
  - consommation quotidienne : v en Wh
  - champ "unite" éventuel : nom deviné
Le service `tempo_edf.enedis_fetch` sert à confirmer tout ça sur tes vraies données.
"""
from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo

from .tempo import is_hc, tempo_day

PARIS = ZoneInfo("Europe/Paris")
DEFAULT_STEP = timedelta(minutes=30)
LOAD_CURVE_TS_IS_END = True  # NON VÉRIFIÉ en v2


def parse_timestamp(raw: Any) -> datetime:
    """'2026-11-05 00:30:00' (heure de Paris) ou ISO avec offset/Z -> datetime UTC."""
    dt = datetime.fromisoformat(str(raw).strip().replace(" ", "T"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=PARIS)
    return dt.astimezone(UTC)


def extract_points(payload: Any) -> tuple[list[tuple[datetime, float]], str | None]:
    """Points de consommation (grandeurMetier CONS) triés + unité annoncée si présente."""
    points: list[tuple[datetime, float]] = []
    unit: str | None = None
    grandeurs = payload.get("grandeur") if isinstance(payload, dict) else None
    for g in grandeurs or []:
        if g.get("grandeurMetier", "CONS") != "CONS":
            continue
        unit = g.get("unite", unit)
        for p in g.get("points") or []:
            try:
                points.append((parse_timestamp(p["d"]), float(p["v"])))
            except (KeyError, TypeError, ValueError):
                continue
    points.sort(key=lambda x: x[0])
    return points, unit


def infer_step(points: list[tuple[datetime, float]]) -> timedelta:
    diffs = [b[0] - a[0] for a, b in zip(points, points[1:]) if b[0] > a[0]]
    return median(diffs) if diffs else DEFAULT_STEP


def _to_kwh(value: float, step: timedelta, unit: str | None) -> float:
    u = (unit or "").strip().lower()
    hours = step.total_seconds() / 3600
    if u == "kwh":
        return value
    if u == "wh":
        return value / 1000
    if u == "kw":
        return value * hours
    return value * hours / 1000  # défaut : puissance moyenne en W


def load_curve_to_intervals(
    payload: Any, ts_is_end: bool = LOAD_CURVE_TS_IS_END
) -> list[tuple[datetime, datetime, float]]:
    """Courbe de charge -> [(début, fin, kWh)] en UTC."""
    points, unit = extract_points(payload)
    if not points:
        return []
    step = infer_step(points)
    out = []
    for ts, v in points:
        start, end = (ts - step, ts) if ts_is_end else (ts, ts + step)
        out.append((start, end, _to_kwh(v, step, unit)))
    return out


def daily_to_kwh(payload: Any) -> list[tuple[date, float]]:
    """Consommation quotidienne -> [(jour, kWh)] (Wh par défaut)."""
    out = []
    grandeurs = payload.get("grandeur") if isinstance(payload, dict) else None
    for g in grandeurs or []:
        if g.get("grandeurMetier", "CONS") != "CONS":
            continue
        unit = str(g.get("unite", "")).lower()
        for p in g.get("points") or []:
            try:
                day = date.fromisoformat(str(p["d"])[:10])
                v = float(p["v"])
            except (KeyError, TypeError, ValueError):
                continue
            out.append((day, v if unit == "kwh" else v / 1000))
    return sorted(out)


def split_by_tariff(
    intervals: list[tuple[datetime, datetime, float]], days: dict[str, str]
) -> dict[tuple[str, str] | None, float]:
    """kWh par (couleur, 'HC'|'HP'). La clé None regroupe les jours dont la couleur est inconnue."""
    out: dict[tuple[str, str] | None, float] = {}
    for start, _end, kwh in intervals:
        local = start.astimezone(PARIS)
        color = days.get(tempo_day(local).isoformat())
        key = (color, "HC" if is_hc(local) else "HP") if color else None
        out[key] = out.get(key, 0.0) + kwh
    return out


def date_chunks(start: date, end: date, days: int) -> list[tuple[date, date]]:
    """Découpe [start, end) en tranches de `days` jours maximum."""
    out, cur = [], start
    while cur < end:
        nxt = min(cur + timedelta(days=days), end)
        out.append((cur, nxt))
        cur = nxt
    return out


def merge_payloads(payloads: list[dict]) -> dict:
    """Fusionne les points de plusieurs réponses (même structure) en une seule."""
    if not payloads:
        return {}
    merged = json.loads(json.dumps(payloads[0]))
    for extra in payloads[1:]:
        for i, g in enumerate(extra.get("grandeur") or []):
            grandeurs = merged.setdefault("grandeur", [])
            if i < len(grandeurs):
                grandeurs[i].setdefault("points", []).extend(g.get("points") or [])
            else:
                grandeurs.append(g)
    return merged


def summarize(payload: Any) -> dict[str, Any]:
    """Résumé compact d'une réponse brute, pour valider le format réel."""
    out: dict[str, Any] = {"raw_head": json.dumps(payload, ensure_ascii=False)[:1500]}
    if isinstance(payload, dict):
        out["keys"] = sorted(payload.keys())
        out["grandeurs"] = [
            {
                "meta": {k: v for k, v in g.items() if k != "points"},
                "points_count": len(g.get("points") or []),
                "first": (g.get("points") or [])[:3],
                "last": (g.get("points") or [])[-3:],
            }
            for g in payload.get("grandeur") or []
            if isinstance(g, dict)
        ]
    return out
