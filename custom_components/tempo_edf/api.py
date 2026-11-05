"""Client minimal pour l'API RTE « Tempo Like Supply Contract »."""
from __future__ import annotations

import time
from datetime import datetime
from typing import Any
from urllib.parse import quote

from aiohttp import BasicAuth, ClientError, ClientSession, ClientTimeout
from yarl import URL

from .const import CALENDAR_URL, TOKEN_URL

TIMEOUT = ClientTimeout(total=30)


class RteAuthError(Exception):
    """Identifiants RTE invalides."""


class RteApiError(Exception):
    """Erreur de communication avec l'API RTE."""


class RteClient:
    def __init__(self, session: ClientSession, client_id: str, client_secret: str) -> None:
        self._session = session
        self._id = client_id
        self._secret = client_secret
        self._token: str | None = None
        self._expires_at = 0.0

    async def async_get_token(self, force: bool = False) -> str:
        if not force and self._token and time.monotonic() < self._expires_at:
            return self._token
        try:
            async with self._session.post(
                TOKEN_URL,
                auth=BasicAuth(self._id, self._secret),
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                timeout=TIMEOUT,
            ) as resp:
                if resp.status in (400, 401, 403):
                    raise RteAuthError(f"Token refusé (HTTP {resp.status})")
                resp.raise_for_status()
                data = await resp.json(content_type=None)
        except (ClientError, TimeoutError) as err:
            raise RteApiError(f"Token RTE injoignable : {err}") from err
        self._token = data["access_token"]
        # marge de 5 minutes avant expiration
        self._expires_at = time.monotonic() + int(data.get("expires_in", 7200)) - 300
        return self._token

    async def async_get_calendars(self, start: datetime, end: datetime) -> dict[str, Any]:
        """start/end : datetimes avec fuseau. Le '+' du fuseau doit être encodé (%2B)."""
        url = (
            f"{CALENDAR_URL}?start_date={quote(start.isoformat(), safe='')}"
            f"&end_date={quote(end.isoformat(), safe='')}"
        )
        for attempt in (0, 1):
            token = await self.async_get_token(force=attempt == 1)
            try:
                async with self._session.get(
                    URL(url, encoded=True),
                    headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    timeout=TIMEOUT,
                ) as resp:
                    if resp.status == 401 and attempt == 0:
                        continue  # token expiré : on réessaie avec un nouveau
                    if resp.status in (401, 403):
                        raise RteAuthError(f"Accès refusé à l'API Tempo (HTTP {resp.status})")
                    if resp.status >= 400:
                        body = (await resp.text())[:200]
                        raise RteApiError(f"HTTP {resp.status} : {body}")
                    return await resp.json(content_type=None)
            except (ClientError, TimeoutError) as err:
                raise RteApiError(f"API Tempo injoignable : {err}") from err
        raise RteApiError("Échec après renouvellement du token")

    async def async_check(self, start: datetime, end: datetime) -> None:
        """Valide les identifiants ET l'abonnement à l'API Tempo (lève RteAuthError / RteApiError)."""
        await self.async_get_token(force=True)
        await self.async_get_calendars(start, end)
