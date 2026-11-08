"""Simulation de EnedisSync avec un Home Assistant factice et un faux client Enedis : python tests/test_sync.py"""
import asyncio, importlib.util, sys, types
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

pkg_dir = Path(__file__).parent.parent / "custom_components" / "tempo_edf"

# ---- Home Assistant factice -------------------------------------------------
def mod(name, **attrs):
    m = types.ModuleType(name); m.__dict__.update(attrs); sys.modules[name] = m; return m

NOW = {"v": datetime(2026, 11, 8, 9, 0, tzinfo=ZoneInfo("Europe/Paris"))}
CAPTURED = []                                           # (statistic_id, rows)
class Store:
    _db = {}
    def __init__(self, hass, version, key): self.key = key
    async def async_load(self): return Store._db.get(self.key)
    async def async_save(self, data): Store._db[self.key] = __import__("json").loads(__import__("json").dumps(data))
for n in ("homeassistant", "homeassistant.components", "homeassistant.components.recorder", "homeassistant.helpers", "homeassistant.util"):
    mod(n)
mod("homeassistant.components.recorder.models", StatisticMetaData=dict)
mod("homeassistant.components.recorder.statistics", async_add_external_statistics=lambda hass, meta, rows: CAPTURED.append((meta["statistic_id"], list(rows))))
mod("homeassistant.config_entries", ConfigEntry=object)
mod("homeassistant.core", HomeAssistant=object, callback=lambda f: f)
mod("homeassistant.helpers.event", async_track_time_change=lambda *a, **k: (lambda: None))
mod("homeassistant.helpers.storage", Store=Store)
mod("homeassistant.util.dt", now=lambda: NOW["v"])
sys.modules["homeassistant.util"].dt = sys.modules["homeassistant.util.dt"]

pkg = types.ModuleType("tempo_edf"); pkg.__path__ = [str(pkg_dir)]; sys.modules["tempo_edf"] = pkg
def load(name):
    spec = importlib.util.spec_from_file_location(f"tempo_edf.{name}", pkg_dir / f"{name}.py")
    m = importlib.util.module_from_spec(spec); sys.modules[f"tempo_edf.{name}"] = m; spec.loader.exec_module(m); return m
for n in ("const", "tempo", "enedis_parse", "tariffs", "enedis_stats", "enedis_api", "enedis_sync"):
    load(n)
from tempo_edf.enedis_sync import EnedisSync
from tempo_edf.enedis_api import EnedisAuthError, EnedisApiError
from tempo_edf.tariffs import DEFAULT_TARIFFS

# ---- faux client / entrée / coordinateur ------------------------------------
class FakeClient:
    def __init__(self): self.calls, self.fail = [], None
    async def async_get(self, dtype, start, end):
        self.calls.append((dtype, start, end))
        if self.fail: raise self.fail
        pts, ts, stop = [], datetime(start.year, start.month, start.day) + timedelta(minutes=30), datetime(end.year, end.month, end.day)
        while ts <= stop:
            pts.append({"v": "1000", "d": ts.strftime("%Y-%m-%d %H:%M:%S"), "p": "PT30M"}); ts += timedelta(minutes=30)
        return {"grandeur": [{"grandeurMetier": "CONS", "unite": "W", "points": pts}]}
class Entry:
    entry_id = "e1"
    options = {"enedis_prm": "00000000000000", "enedis_history_days": 12, "tariffs": DEFAULT_TARIFFS}
    def async_on_unload(self, f): pass
    def async_create_background_task(self, hass, coro, name): coro.close()
class Coord:
    days = {(datetime(2026, 10, 20) + timedelta(days=i)).strftime("%Y-%m-%d"): "BLUE" for i in range(40)}
    def async_update_listeners(self): pass

def totals(captured, prefix):
    last = {}
    for sid, rows in captured:
        if sid.startswith(prefix) and rows: last[sid] = rows[-1]["sum"]
    return round(sum(last.values()), 3)

async def main():
    client, sync = FakeClient(), None
    sync = EnedisSync(object(), Entry(), Coord(), client)
    asyncio.get_event_loop  # noqa

    # 1. première synchro : 12 jours d'historique = 2 requêtes de 6 jours, du plus récent au plus ancien
    r = await sync.async_sync("initial")
    assert r["requests"] == 2 and r["days_remaining"] == 0 and sync.status == "À jour", r
    assert [(c[1].isoformat(), c[2].isoformat()) for c in client.calls] == [("2026-11-02", "2026-11-08"), ("2026-10-27", "2026-11-02")], client.calls
    assert len(CAPTURED) == 12 and sync.complete_days == 12 and sync.last_day.isoformat() == "2026-11-07"
    assert totals(CAPTURED, "tempo_edf:conso_") == 288.0, totals(CAPTURED, "tempo_edf:conso_")   # 12 j x 24 kWh
    expected_cost = round(sum(0.1356 if h < 6 or h >= 22 else 0.1654 for _ in range(12) for h in range(24)), 3)
    # coûts : bleu, grille du 1er août 2026 (1 kWh par heure)
    assert abs(totals(CAPTURED, "tempo_edf:cout_") - expected_cost) < 0.01, (totals(CAPTURED, "tempo_edf:cout_"), expected_cost)
    full_rows = len(next(rows for sid, rows in CAPTURED if sid == "tempo_edf:conso_blue_hp"))
    assert full_rows == 12 * 24

    # 2. le lendemain même jour : rien à demander
    CAPTURED.clear(); client.calls.clear()
    r = await sync.async_sync("daily"); assert r["requests"] == 0 and not client.calls and not CAPTURED

    # 3. jour suivant : 1 seule requête (la veille), publication de la queue seulement, cumuls cohérents
    NOW["v"] += timedelta(days=1)
    r = await sync.async_sync("daily")
    assert r["requests"] == 1 and (client.calls[0][1].isoformat(), client.calls[0][2].isoformat()) == ("2026-11-08", "2026-11-09"), client.calls
    tail_rows = len(next(rows for sid, rows in CAPTURED if sid == "tempo_edf:conso_blue_hp"))
    assert tail_rows <= 72 + 1 and tail_rows < full_rows
    assert totals(CAPTURED, "tempo_edf:conso_") == 312.0, totals(CAPTURED, "tempo_edf:conso_")   # cumul continu : 13 jours

    # 4. réessai de l'après-midi : rien si la veille est déjà là
    client.calls.clear(); r = await sync.async_sync("retry"); assert r["requests"] == 0

    # 5. données anciennes ajoutées plus tard (historique étendu) : republication complète, cumuls toujours cohérents
    sync.entry.options = {**Entry.options, "enedis_history_days": 18}
    CAPTURED.clear(); client.calls.clear()
    r = await sync.async_sync("daily")
    assert r["requests"] == 1 and (client.calls[0][1].isoformat(), client.calls[0][2].isoformat()) == ("2026-10-22", "2026-10-27"), client.calls
    assert totals(CAPTURED, "tempo_edf:conso_") == 312.0 + 5 * 24
    assert len(next(rows for sid, rows in CAPTURED if sid == "tempo_edf:conso_blue_hp")) > full_rows   # tout republié

    # 6. erreur d'authentification : arrêt net, pas de nouvelle tentative automatique
    NOW["v"] += timedelta(days=1); client.calls.clear(); client.fail = EnedisAuthError("401")
    r = await sync.async_sync("daily"); assert r["requests"] == 1 and "token refusé" in sync.status
    client.calls.clear(); r = await sync.async_sync("daily"); assert not client.calls                  # bloqué
    client.fail = None; r = await sync.async_sync("manual"); assert r["requests"] == 1 and sync.status == "À jour"

    # 7. erreur réseau : une seule requête, statut d'erreur, pas de boucle
    NOW["v"] += timedelta(days=1); client.calls.clear(); client.fail = EnedisApiError("HTTP 500")
    r = await sync.async_sync("daily"); assert r["requests"] == 1 and sync.status.startswith("Erreur")

    # 8. persistance : un nouvel objet retrouve l'état sans rien redemander
    sync2 = EnedisSync(object(), Entry(), Coord(), FakeClient())
    await sync2.async_setup()
    assert sync2.hourly == sync.hourly and sync2.start_day == sync.start_day
    print("OK sync")

asyncio.run(main())
