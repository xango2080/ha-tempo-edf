"""Client Conso API (passerelle open-source vers l'API Enedis « Mesure synchrone V2 »)."""
from __future__ import annotations

import asyncio
from datetime import date
from typing import Any

from aiohttp import ClientError, ClientSession, ClientTimeout

from .const import ENEDIS_BASE_URL, ENEDIS_USER_AGENT
from .enedis_parse import date_chunks

TIMEOUT = ClientTimeout(total=60)
PAUSE_BETWEEN_CALLS = 1.5  # Conso API est gratuit : on ménage le service


class EnedisAuthError(Exception):
    """Token Conso API invalide, expiré ou sans accès à ce PRM."""


class EnedisApiError(Exception):
    """Erreur Conso API / Enedis (réessayer plus tard)."""


class ConsoApiClient:
    def __init__(self, session: ClientSession, token: str, prm: str) -> None:
        self._session = session
        self._token = token
        self._prm = prm

    async def async_get(self, data_type: str, start: date, end: date) -> dict[str, Any]:
        """start inclus, end exclu (format YYYY-MM-DD)."""
        try:
            async with self._session.get(
                f"{ENEDIS_BASE_URL}/{data_type}",
                params={
                    "pointId": self._prm,
                    "dateDebut": start.isoformat(),
                    "dateFin": end.isoformat(),
                },
                headers={
                    "Authorization": f"Bearer {self._token}",
                    "User-Agent": ENEDIS_USER_AGENT,
                    "Accept": "application/json",
                },
                timeout=TIMEOUT,
            ) as resp:
                if resp.status == 401:
                    raise EnedisAuthError("Token refusé (consentement expiré ou refait ?)")
                if resp.status == 404:  # Enedis : aucune mesure sur la période
                    return {"grandeur": []}
                if resp.status >= 400:
                    body = (await resp.text())[:300]
                    raise EnedisApiError(f"HTTP {resp.status} : {body}")
                return await resp.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise EnedisApiError(f"Conso API injoignable : {err}") from err

    async def async_get_range(
        self, data_type: str, start: date, end: date, chunk_days: int
    ) -> list[dict[str, Any]]:
        """Plusieurs requêtes espacées si la période dépasse chunk_days."""
        payloads = []
        for i, (a, b) in enumerate(date_chunks(start, end, chunk_days)):
            if i:
                await asyncio.sleep(PAUSE_BETWEEN_CALLS)
            payloads.append(await self.async_get(data_type, a, b))
        return payloads
