"""Grilles tarifaires datées (logique pure)."""
from __future__ import annotations

from datetime import date
from typing import Any

# Tarif Bleu EDF, option Tempo, €/kWh TTC (identiques de 6 à 36 kVA).
# Sources : barèmes publiés aux 1er août 2025, 1er février 2026 et 1er août 2026.
DEFAULT_TARIFFS: list[dict[str, Any]] = [
    {"from": "2025-08-01", "prices": {"BLUE_HC": 0.1232, "BLUE_HP": 0.1494, "WHITE_HC": 0.1391,
                                      "WHITE_HP": 0.1730, "RED_HC": 0.1460, "RED_HP": 0.6468}},
    {"from": "2026-02-01", "prices": {"BLUE_HC": 0.1325, "BLUE_HP": 0.1612, "WHITE_HC": 0.1499,
                                      "WHITE_HP": 0.1871, "RED_HC": 0.1575, "RED_HP": 0.7060}},
    {"from": "2026-08-01", "prices": {"BLUE_HC": 0.1356, "BLUE_HP": 0.1654, "WHITE_HC": 0.1536,
                                      "WHITE_HP": 0.1921, "RED_HC": 0.1615, "RED_HP": 0.7295}},
]


def tariff_key(color: str, period: str) -> str:
    return f"{color}_{period}"


def tariff_at(tariffs: list[dict[str, Any]], day: date) -> dict[str, float] | None:
    """Grille en vigueur le jour `day` (None si antérieur à la première période)."""
    best = None
    for period in sorted(tariffs, key=lambda p: p["from"]):
        if period["from"] <= day.isoformat():
            best = period
    return {k: float(v) for k, v in best["prices"].items()} if best else None


def upsert_period(tariffs: list[dict[str, Any]], from_day: str, prices: dict[str, float]) -> list[dict[str, Any]]:
    """Ajoute une période (ou remplace celle qui a la même date d'effet)."""
    out = [p for p in tariffs if p["from"] != from_day]
    out.append({"from": from_day, "prices": {k: round(float(v), 5) for k, v in prices.items()}})
    return sorted(out, key=lambda p: p["from"])


def same_prices(a: dict[str, float], b: dict[str, float]) -> bool:
    return a.keys() == b.keys() and all(abs(a[k] - b[k]) < 1e-9 for k in a)
