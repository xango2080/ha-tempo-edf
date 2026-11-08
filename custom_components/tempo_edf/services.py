"""Service de diagnostic : tempo_edf.enedis_fetch (renvoie un résumé du format réel)."""
from __future__ import annotations

from datetime import timedelta

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError, ServiceValidationError
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN, ENEDIS_TYPES, LOAD_CURVE_CHUNK_DAYS, SERVICE_ENEDIS_FETCH
from .enedis_api import EnedisApiError, EnedisAuthError
from .enedis_parse import kwh_per_day, load_curve_to_intervals, merge_payloads, summarize

SCHEMA = vol.Schema(
    {
        vol.Required("data_type"): vol.In(ENEDIS_TYPES),
        vol.Required("start_date"): cv.date,
        vol.Required("end_date"): cv.date,
    }
)
MAX_DAYS = 31


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_ENEDIS_FETCH):
        return

    async def _handle(call: ServiceCall) -> dict:
        client = next(
            (
                e.runtime_data.enedis
                for e in hass.config_entries.async_entries(DOMAIN)
                if getattr(e, "runtime_data", None) and e.runtime_data.enedis
            ),
            None,
        )
        if client is None:
            raise ServiceValidationError("Enedis non configuré : renseigne le token et le PRM dans Configurer.")
        start, end, dtype = call.data["start_date"], call.data["end_date"], call.data["data_type"]
        if not start < end or end - start > timedelta(days=MAX_DAYS):
            raise ServiceValidationError(f"Période invalide : 1 à {MAX_DAYS} jours, date de fin exclue.")
        chunk = LOAD_CURVE_CHUNK_DAYS if "courbe" in dtype or "index" in dtype else MAX_DAYS
        try:
            payloads = await client.async_get_range(dtype, start, end, chunk)
        except EnedisAuthError as err:
            raise HomeAssistantError(f"Token Conso API refusé : {err}") from err
        except EnedisApiError as err:
            raise HomeAssistantError(str(err)) from err
        merged = merge_payloads(payloads)
        result = {"requests": len(payloads), **summarize(merged)}
        if dtype == "courbe_de_charge_consommation":
            # Contrôle : à comparer à consommation_quotidienne (jours complets uniquement).
            result["kwh_par_jour"] = kwh_per_day(load_curve_to_intervals(merged))
        return result

    hass.services.async_register(
        DOMAIN, SERVICE_ENEDIS_FETCH, _handle, schema=SCHEMA, supports_response=SupportsResponse.ONLY
    )
