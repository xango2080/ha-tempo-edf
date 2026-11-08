"""Tests de la logique pure : python tests/test_tempo.py"""
import importlib.util, sys, types
from datetime import date, datetime
from pathlib import Path

pkg_dir = Path(__file__).parent.parent / "custom_components" / "tempo_edf"
pkg = types.ModuleType("tempo_edf"); pkg.__path__ = [str(pkg_dir)]; sys.modules["tempo_edf"] = pkg
for name in ("const", "tempo"):
    spec = importlib.util.spec_from_file_location(f"tempo_edf.{name}", pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[f"tempo_edf.{name}"] = mod; spec.loader.exec_module(mod)
from tempo_edf.tempo import *  # noqa

assert season_start(date(2026, 11, 5)) == date(2026, 9, 1)
assert season_start(date(2027, 3, 1)) == date(2026, 9, 1)
assert season_start(date(2026, 9, 1)) == date(2026, 9, 1)
assert season_label(date(2027, 3, 1)) == "2026-2027"
assert tempo_day(datetime(2026, 11, 5, 3, 0)) == date(2026, 11, 4)
assert tempo_day(datetime(2026, 11, 5, 6, 0)) == date(2026, 11, 5)
assert tempo_day(datetime(2026, 11, 5, 23, 0)) == date(2026, 11, 5)
assert is_hc(datetime(2026, 1, 1, 22, 0)) and is_hc(datetime(2026, 1, 1, 5, 59))
assert not is_hc(datetime(2026, 1, 1, 6, 0)) and not is_hc(datetime(2026, 1, 1, 21, 59))

payload = {"tempo_like_calendars": {"values": [
    {"start_date": "2026-11-04T00:00:00+01:00", "end_date": "2026-11-05T00:00:00+01:00", "value": "BLUE"},
    {"start_date": "2026-11-05T00:00:00+01:00", "end_date": "2026-11-06T00:00:00+01:00", "value": "white"},
    {"start_date": "2026-11-06T00:00:00+01:00", "value": "???"},
]}}
parsed = parse_calendar(payload)
assert parsed == {"2026-11-04": "BLUE", "2026-11-05": "WHITE"}, parsed
assert parse_calendar(None) == {} and parse_calendar({}) == {}

days = {"2026-09-01": "BLUE", "2026-09-02": "RED", "2026-09-03": "BLUE"}
r = count_days(days, date(2026, 9, 3))
assert r == {"counts": {"BLUE": 2, "WHITE": 0, "RED": 1}, "elapsed": 3, "known": 3}, r
assert not has_gaps(days, date(2026, 9, 3)) and has_gaps(days, date(2026, 9, 4))
assert past_season_bounds(date(2026, 11, 5), 1) == (date(2025, 9, 1), date(2026, 9, 1))
assert past_season_bounds(date(2027, 3, 1), 2) == (date(2024, 9, 1), date(2025, 9, 1))
print("OK")

# ---------- Enedis (payloads SYNTHÉTIQUES basés sur les hypothèses documentées, pas sur de vraies données) ----------
for name in ("enedis_parse",):
    spec = importlib.util.spec_from_file_location(f"tempo_edf.{name}", pkg_dir / f"{name}.py")
    mod = importlib.util.module_from_spec(spec); sys.modules[f"tempo_edf.{name}"] = mod; spec.loader.exec_module(mod)
from datetime import timedelta  # noqa
from tempo_edf.enedis_parse import *  # noqa

assert parse_timestamp("2026-11-05 06:00:00").isoformat() == "2026-11-05T05:00:00+00:00"   # Paris hiver = UTC+1
assert parse_timestamp("2026-11-05T06:00:00+01:00").isoformat() == "2026-11-05T05:00:00+00:00"
assert parse_timestamp("2026-07-01 06:00:00").isoformat() == "2026-07-01T04:00:00+00:00"   # été = UTC+2

lc = {"grandeur": [
    {"grandeurMetier": "CONS", "points": [
        {"d": "2026-11-05 05:30:00", "v": "1000"},   # fin d'intervalle 05:30 -> 05:00-05:30 : HC, couleur du 04/11
        {"d": "2026-11-05 06:00:00", "v": "2000"},   # 05:30-06:00 : HC encore
        {"d": "2026-11-05 06:30:00", "v": "4000"},   # 06:00-06:30 : HP, jour du 05/11
    ]},
    {"grandeurMetier": "PROD", "points": [{"d": "2026-11-05 06:30:00", "v": "99999"}]},
]}
iv = load_curve_to_intervals(lc)
assert len(iv) == 3 and abs(iv[0][2] - 0.5) < 1e-9 and abs(iv[2][2] - 2.0) < 1e-9, iv   # W x 0,5 h / 1000
assert (iv[2][1] - iv[2][0]) == timedelta(minutes=30)
split = split_by_tariff(iv, {"2026-11-04": "BLUE", "2026-11-05": "RED"})
assert split == {("BLUE", "HC"): 0.5 + 1.0, ("RED", "HP"): 2.0}, split
assert split_by_tariff(iv, {}) == {None: 3.5}
iv2 = load_curve_to_intervals(lc, ts_is_end=False)
assert iv2[0][0] == iv[0][1]

daily = {"grandeur": [{"grandeurMetier": "CONS", "points": [{"d": "2026-11-04", "v": "12345"}]}]}
assert daily_to_kwh(daily) == [(date(2026, 11, 4), 12.345)]
assert load_curve_to_intervals({}) == [] and daily_to_kwh(None) == []

assert date_chunks(date(2026, 1, 1), date(2026, 1, 16), 7) == [
    (date(2026, 1, 1), date(2026, 1, 8)), (date(2026, 1, 8), date(2026, 1, 15)), (date(2026, 1, 15), date(2026, 1, 16))]
m = merge_payloads([daily, daily]); assert len(m["grandeur"][0]["points"]) == 2
s = summarize(m); assert s["grandeurs"][0]["points_count"] == 2 and "raw_head" in s
print("OK enedis")
