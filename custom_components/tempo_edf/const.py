"""Constantes de l'intégration EDF Tempo."""
from __future__ import annotations

DOMAIN = "tempo_edf"

CONF_CLIENT_ID = "client_id"
CONF_CLIENT_SECRET = "client_secret"
CONF_HISTORY_SEASONS = "history_seasons"
DEFAULT_HISTORY_SEASONS = 3
MAX_HISTORY_SEASONS = 12

# --- Enedis (via la passerelle Conso API, API « Mesure synchrone V2 ») ---
CONF_ENEDIS_TOKEN = "enedis_token"
CONF_ENEDIS_PRM = "enedis_prm"
ENEDIS_BASE_URL = "https://conso.boris.sh/api"
ENEDIS_USER_AGENT = "github.com/xango2080/ha-tempo-edf"
ENEDIS_TYPES = [
    "consommation_quotidienne",
    "courbe_de_charge_consommation",
    "puissance_conso_max_quotidienne",
    "index_consommation",
]
LOAD_CURVE_CHUNK_DAYS = 6  # 6 jours = taille validée sur données réelles (288 points)
SERVICE_ENEDIS_FETCH = "enedis_fetch"

JOURTEMPO_JSON_URL = "https://jourtempo.fr/api/v1/tempo.json"
JOURTEMPO_CSV_URL = "https://jourtempo.fr/api/v1/tempo-historique.csv"
USER_AGENT = "ha-tempo-edf (github.com/xango2080/ha-tempo-edf)"
ATTRIBUTION = "Couleurs : RTE, via Jour Tempo (jourtempo.fr)"

TOKEN_URL = "https://digital.iservices.rte-france.com/token/oauth/"
CALENDAR_URL = (
    "https://digital.iservices.rte-france.com/open_api/"
    "tempo_like_supply_contract/v1/tempo_like_calendars"
)

STORE_VERSION = 1
POLL_INTERVAL_HOURS = 1

# Jour Tempo = de 06:00 à 06:00. Heures creuses = 22:00 -> 06:00.
DAY_START_HOUR = 6
HC_START_HOUR = 22

COLORS = {"BLUE": "Bleu", "WHITE": "Blanc", "RED": "Rouge"}
COLOR_CODE = {"BLUE": 1, "WHITE": 2, "RED": 3}
COLOR_EMOJI = {"BLUE": "🔵", "WHITE": "⚪", "RED": "🔴"}
COLOR_HEX = {"BLUE": "#1E6FD9", "WHITE": "#E8E8E8", "RED": "#D93025"}

# Nombre de jours par saison (1er sept -> 31 août). Modifiable si les règles changent.
SEASON_TOTALS = {"BLUE": 300, "WHITE": 43, "RED": 22}

PERIODS = ("HC", "HP")
TARIFFS = [(c, p) for c in ("BLUE", "WHITE", "RED") for p in PERIODS]

PRICE_UNIT = "EUR/kWh"


def price_key(color: str, period: str) -> str:
    """Clé d'option pour un tarif, ex: price_blue_hc."""
    return f"price_{color.lower()}_{period.lower()}"


# --- Tarifs datés et import Enedis -> Énergie ---
CONF_TARIFFS = "tariffs"  # [{"from": "2026-08-01", "prices": {"BLUE_HC": 0.1356, ...}}]
CONF_EFFECTIVE_DATE = "effective_date"
CONF_ENEDIS_HISTORY_DAYS = "enedis_history_days"
DEFAULT_ENEDIS_HISTORY_DAYS = 30
MAX_ENEDIS_HISTORY_DAYS = 365
LOAD_CURVE_TYPE = "courbe_de_charge_consommation"
SYNC_CHUNK_DAYS = 6          # jours par requête (taille validée)
MAX_REQUESTS_PER_RUN = 6     # plafond par synchronisation (rattrapage de l'historique étalé sur plusieurs jours)
MAX_REQUESTS_PER_HOUR = 10   # garde-fou interne, très en dessous des quotas Enedis (5/s, 10 000/h partagés)
SYNC_PAUSE_SECONDS = 2
MANUAL_SYNC_MIN_MINUTES = 30
SERVICE_ENEDIS_SYNC = "enedis_sync"

# --- Annonce de la couleur de demain ---
# RTE fixe la couleur du lendemain vers 10 h 30 ; Jour Tempo relève à 11:00, 11:30, 12:00, 12:30 (heure de Paris).
ANNOUNCE_HOUR, ANNOUNCE_MINUTE = 10, 30
# Créneaux de vérification (heure de Paris), calés 5 min après les relevés Jour Tempo (cache de 2 min).
ANNOUNCE_SLOTS = {(11, 5), (11, 35), (12, 5), (12, 35), (13, 5)}
ANNOUNCE_SLOTS_RTE = {(10, 35), (10, 50)}  # en plus, si l'API officielle RTE est configurée (annonce ~10 h 30)
