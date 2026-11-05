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
