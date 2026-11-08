"""Client de l'API publique Jour Tempo (gratuite, sans clé) : https://jourtempo.fr/api/

Conditions : un appel toutes les 30 min suffit, jamais moins de 10 min d'écart ; citer RTE et Jour Tempo.
"""
from __future__ import annotations

import json

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import JOURTEMPO_CSV_URL, JOURTEMPO_JSON_URL, USER_AGENT
from .tempo import parse_jourtempo_csv, parse_jourtempo_json, parse_jourtempo_quotas

TIMEOUT = ClientTimeout(total=30)


class JourTempoError(Exception):
    """Jour Tempo injoignable ou réponse inattendue."""


class JourTempoClient:
    def __init__(self, session: ClientSession) -> None:
        self._session = session

    async def _get_text(self, url: str) -> str:
        try:
            async with self._session.get(
                url, headers={"User-Agent": USER_AGENT}, timeout=TIMEOUT
            ) as resp:
                if resp.status >= 400:
                    raise JourTempoError(f"HTTP {resp.status} sur {url}")
                return await resp.text()
        except (ClientError, TimeoutError) as err:
            raise JourTempoError(f"Jour Tempo injoignable : {err}") from err

    async def async_get_current(self) -> tuple[dict[str, str], dict[str, int]]:
        """(calendrier de la saison en cours jusqu'à demain si annoncé, quotas par couleur)."""
        try:
            payload = json.loads(await self._get_text(JOURTEMPO_JSON_URL))
        except ValueError as err:
            raise JourTempoError(f"tempo.json illisible : {err}") from err
        days = parse_jourtempo_json(payload)
        if not days:
            raise JourTempoError("tempo.json ne contient aucune couleur exploitable")
        return days, parse_jourtempo_quotas(payload)

    async def async_get_history(self) -> dict[str, str]:
        """Tout l'historique depuis septembre 2014."""
        days = parse_jourtempo_csv(await self._get_text(JOURTEMPO_CSV_URL))
        if not days:
            raise JourTempoError("tempo-historique.csv ne contient aucune couleur exploitable")
        return days
