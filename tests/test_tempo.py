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

# ---------- Jour Tempo (échantillons recopiés de la documentation https://jourtempo.fr/api/) ----------
doc_json = {"aujourdhui": {"date": "2026-12-03", "code": "blanc"}, "demain": {"date": "2026-12-04", "code": "rouge"},
            "calendrier": {"2026-09-01": "bleu", "2026-12-03": "blanc"}}
assert parse_jourtempo_json(doc_json) == {"2026-09-01": "BLUE", "2026-12-03": "WHITE", "2026-12-04": "RED"}
doc_json["demain"]["code"] = "inconnu"          # pas encore annoncé : ignoré
assert "2026-12-04" not in parse_jourtempo_json(doc_json)
assert parse_jourtempo_json(None) == {} and parse_jourtempo_json({"calendrier": []}) == {}
csv_text = "\ufeffdate,couleur,saison\n2014-09-01,bleu,2014-2015\n2014-12-05,rouge,2014-2015\nbad,??,x\n"
assert parse_jourtempo_csv(csv_text) == {"2014-09-01": "BLUE", "2014-12-05": "RED"}
assert parse_jourtempo_csv("") == {}
print("OK jourtempo")

d = {"2026-09-01": "BLUE", "2026-09-02": "RED", "2026-09-03": "BLUE"}
r = season_status(d, date(2026, 9, 2))            # demain (3 sept.) déjà annoncé : déduit
assert r["counts"] == {"BLUE": 2, "WHITE": 0, "RED": 1} and r["known"] == r["elapsed"] == 3, r
r = season_status({"2026-09-01": "BLUE", "2026-09-02": "RED"}, date(2026, 9, 2))   # demain inconnu
assert r["counts"]["BLUE"] == 1 and r["elapsed"] == 2
r = season_status({"2026-09-02": "RED"}, date(2026, 9, 2))                          # historique incomplet
assert r["known"] != r["elapsed"]
print("OK season_status")

q = {"saison": {"compteurs": {"bleu": {"quota": 300, "tombes": 68, "restants": 232},
                               "blanc": {"quota": 43, "tombes": 1, "restants": 42},
                               "rouge": {"quota": "22", "tombes": 0, "restants": 22}}}}
assert parse_jourtempo_quotas(q) == {"BLUE": 300, "WHITE": 43, "RED": 22}
assert parse_jourtempo_quotas({"saison": {"compteurs": {"rouge": {"quota": 0}}}}) == {}
assert parse_jourtempo_quotas(None) == {} and parse_jourtempo_quotas({}) == {}
print("OK quotas")

# ---------- Format réel observé (structure recopiée d'une vraie réponse ; PRM et valeurs fictifs) ----------
from datetime import datetime as _dt
pts = []
for i in range(1, 97):                                  # 2 jours de points à 30 min : 02/11 00:30 -> 04/11 00:00
    ts = _dt(2026, 11, 2) + timedelta(minutes=30 * i)
    pts.append({"v": "1000", "d": ts.strftime("%Y-%m-%d %H:%M:%S"), "p": "PT30M", "n": "B", "iv": "0", "ec": "0"})
real = {"idPrm": "00000000000000", "etapeMetier": "BRUT", "modeCalcul": "MESURE", "contexte": {},
        "periode": {"dateDebut": "2026-11-02", "dateFin": "2026-11-04"},
        "grandeur": [{"grandeurMetier": "CONS", "grandeurPhysique": "PA", "unite": "W", "calendrier": [], "points": pts}]}
iv = load_curve_to_intervals(real)
assert len(iv) == 96
assert iv[0][0].isoformat() == "2026-11-01T23:00:00+00:00"        # 1er intervalle = 00:00-00:30 heure de Paris
assert iv[-1][1].isoformat() == "2026-11-03T23:00:00+00:00"       # dernier = 23:30-00:00, fin = minuit du 4
assert abs(sum(k for _, _, k in iv) - 48.0) < 1e-9               # 96 x 1000 W x 0,5 h = 48 kWh
cols = {"2026-11-01": "BLUE", "2026-11-02": "WHITE", "2026-11-03": "RED"}
sp = split_by_tariff(iv, cols)
# 02/11 00:00-06:00 = HC de la veille (bleu) : 12 intervalles ; 06:00-22:00 = HP blanc : 32 ; 22:00-06:00 = HC blanc : 16 ; ...
assert abs(sp[("BLUE", "HC")] - 6.0) < 1e-9 and abs(sp[("WHITE", "HP")] - 16.0) < 1e-9, sp
assert abs(sp[("WHITE", "HC")] - 8.0) < 1e-9 and abs(sp[("RED", "HP")] - 16.0) < 1e-9 and abs(sp[("RED", "HC")] - 2.0) < 1e-9, sp
assert abs(sum(sp.values()) - 48.0) < 1e-9
print("OK format reel")

# ---------- index_consommation : structure observée (PRM fictif, valeurs recopiées de la vraie réponse) ----------
idx = {"idPrm": "00000000000000", "periode": {"dateDebut": "2026-11-06", "dateFin": "2026-11-08"}, "grandeur": [],
       "contexte": [{"etapeMetier": "BRUT", "contexteReleve": "COL", "typeReleve": "AQ", "grandeur": [
           {"grandeurMetier": "CONS", "grandeurPhysique": "EA", "unite": "Wh", "points": [], "calendrier": [
               {"idCalendrier": "DI000003", "libelleCalendrier": "4 cadrans", "classeTemporelle": [
                   {"idClasseTemporelle": "HCH", "libelleClasseTemporelle": "HC Hiver", "codeCadran": "IDX_EAS_D3",
                    "valeur": [{"d": "2026-11-06 00:00:00", "v": 6228544, "iv": 0}, {"d": "2026-11-07 00:00:00", "v": 6241690, "iv": 0}]},
                   {"idClasseTemporelle": "HPH", "libelleClasseTemporelle": "HP Hiver", "codeCadran": "IDX_EAS_D4",
                    "valeur": [{"d": "2026-11-06 00:00:00", "v": 7069969, "iv": 0}, {"d": "2026-11-07 00:00:00", "v": 7091481, "iv": 0}]}]},
               {"idCalendrier": "FC000050", "libelleCalendrier": "6 cadrans", "classeTemporelle": [
                   {"idClasseTemporelle": "BCHC", "valeur": [{"d": "2026-11-06 00:00:00", "v": "100", "iv": 0}]}]}]}]}]}
pi = parse_index(idx)
assert set(pi) == {"DI000003", "FC000050"}
hch = pi["DI000003"]["HCH"]
assert hch[1][1] - hch[0][1] == 13146 and pi["DI000003"]["HPH"][1][1] - pi["DI000003"]["HPH"][0][1] == 21512
assert pi["FC000050"]["BCHC"] == [(date(2026, 11, 6), 100.0)]
sm = summarize(idx)
assert [c["calendrier"] for c in sm["index_calendriers"]] == ["DI000003", "FC000050"]
assert sm["index_calendriers"][0]["classes"][0]["cadran"] == "IDX_EAS_D3"
assert parse_index(None) == {} and parse_index({"contexte": {}}) == {}
print("OK index")

# ---------- consommation_quotidienne / puissance max : formats observés ----------
dq = {"idPrm": "00000000000000", "typeValeur": "GLOBALE", "modeCalcul": "DIFF.INDEX", "pas": "P1D",
      "grandeur": [{"grandeurMetier": "CONS", "grandeurPhysique": "EA", "unite": "Wh",
                    "points": [{"v": "34658", "d": "2026-11-06"}, {"v": "34763", "d": "2026-11-07"}], "calendrier": []}],
      "contexte": []}
assert daily_to_kwh(dq) == [(date(2026, 11, 6), 34.658), (date(2026, 11, 7), 34.763)]
assert "index_calendriers" not in summarize(dq)             # contexte vide : pas de résumé d'index
assert kwh_per_day(iv) == {"2026-11-02": 24.0, "2026-11-03": 24.0}, kwh_per_day(iv)   # 1000 W en continu = 24 kWh / jour
print("OK quotidien")
