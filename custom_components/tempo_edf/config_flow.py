"""Config flow : source des couleurs (RTE facultatif), puis tarifs datés, historique et Enedis en options."""
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    DateSelector,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)
from homeassistant.util import dt as dt_util

from .api import RteApiError, RteAuthError, RteClient
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_EFFECTIVE_DATE,
    CONF_ENEDIS_HISTORY_DAYS,
    CONF_ENEDIS_PRM,
    CONF_ENEDIS_TOKEN,
    CONF_HISTORY_SEASONS,
    CONF_TARIFFS,
    DEFAULT_ENEDIS_HISTORY_DAYS,
    DEFAULT_HISTORY_SEASONS,
    DOMAIN,
    MAX_ENEDIS_HISTORY_DAYS,
    MAX_HISTORY_SEASONS,
    TARIFFS,
    price_key,
)
from .jourtempo_api import JourTempoClient, JourTempoError
from .tariffs import DEFAULT_TARIFFS, same_prices, tariff_at, upsert_period

USER_SCHEMA = vol.Schema(
    {vol.Optional(CONF_CLIENT_ID): str, vol.Optional(CONF_CLIENT_SECRET): str}
)


class TempoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Identifiants RTE facultatifs : sans eux, la source gratuite Jour Tempo est utilisée."""
        errors: dict[str, str] = {}
        if user_input is not None:
            cid = (user_input.get(CONF_CLIENT_ID) or "").strip()
            secret = (user_input.get(CONF_CLIENT_SECRET) or "").strip()
            session = async_get_clientsession(self.hass)
            if bool(cid) != bool(secret):
                errors["base"] = "incomplete"
            elif cid:
                try:
                    now = dt_util.now()
                    await RteClient(session, cid, secret).async_check(
                        now - timedelta(days=2), now - timedelta(days=1)
                    )
                except RteAuthError:
                    errors["base"] = "invalid_auth"
                except RteApiError:
                    errors["base"] = "cannot_connect"
            else:
                try:
                    await JourTempoClient(session).async_get_current()
                except JourTempoError:
                    errors["base"] = "cannot_connect"
            if not errors:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()
                data = {CONF_CLIENT_ID: cid, CONF_CLIENT_SECRET: secret} if cid else {}
                return self.async_create_entry(title="EDF Tempo", data=data)
        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TempoOptionsFlow()


class TempoOptionsFlow(OptionsFlow):
    """Tarifs datés (€/kWh TTC), historique RTE et accès Enedis (optionnel)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        opts = self.config_entry.options
        tariffs = list(opts.get(CONF_TARIFFS) or DEFAULT_TARIFFS)
        today = dt_util.now().date()
        current = tariff_at(tariffs, today) or {}
        errors: dict[str, str] = {}

        if user_input is not None:
            token = (user_input.get(CONF_ENEDIS_TOKEN) or "").strip()
            prm = (user_input.get(CONF_ENEDIS_PRM) or "").strip().replace(" ", "")
            if bool(token) != bool(prm) or (prm and not re.fullmatch(r"\d{14}", prm)):
                errors["base"] = "invalid_enedis"
            try:
                effective = date.fromisoformat(str(user_input.get(CONF_EFFECTIVE_DATE) or today.isoformat()))
            except ValueError:
                effective = None
                errors["base"] = "invalid_date"
            prices: dict[str, float | None] = {}
            for color, period in TARIFFS:
                raw = user_input.get(price_key(color, period))
                key = f"{color}_{period}"
                prices[key] = float(raw) if raw not in (None, "") else current.get(key)
            if not errors and any(v is None for v in prices.values()):
                errors["base"] = "incomplete_prices"

            if not errors:
                in_effect = tariff_at(tariffs, effective)
                if in_effect is None or not same_prices(in_effect, prices):
                    tariffs = upsert_period(tariffs, effective.isoformat(), prices)
                data: dict[str, Any] = {
                    CONF_TARIFFS: tariffs,
                    CONF_HISTORY_SEASONS: int(user_input.get(CONF_HISTORY_SEASONS, DEFAULT_HISTORY_SEASONS)),
                    CONF_ENEDIS_HISTORY_DAYS: int(
                        user_input.get(CONF_ENEDIS_HISTORY_DAYS, DEFAULT_ENEDIS_HISTORY_DAYS)
                    ),
                }
                if token:
                    data[CONF_ENEDIS_TOKEN] = token
                    data[CONF_ENEDIS_PRM] = prm
                return self.async_create_entry(data=data)

        price = NumberSelector(NumberSelectorConfig(min=0, max=5, step="any", mode=NumberSelectorMode.BOX))
        fields: dict = {vol.Optional(price_key(c, p)): price for c, p in TARIFFS}
        fields[vol.Optional(CONF_EFFECTIVE_DATE, default=today.isoformat())] = DateSelector()
        fields[vol.Optional(CONF_HISTORY_SEASONS, default=DEFAULT_HISTORY_SEASONS)] = NumberSelector(
            NumberSelectorConfig(min=0, max=MAX_HISTORY_SEASONS, step=1, mode=NumberSelectorMode.BOX)
        )
        fields[vol.Optional(CONF_ENEDIS_TOKEN)] = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))
        fields[vol.Optional(CONF_ENEDIS_PRM)] = TextSelector(TextSelectorConfig())
        fields[vol.Optional(CONF_ENEDIS_HISTORY_DAYS, default=DEFAULT_ENEDIS_HISTORY_DAYS)] = NumberSelector(
            NumberSelectorConfig(min=1, max=MAX_ENEDIS_HISTORY_DAYS, step=1, mode=NumberSelectorMode.BOX)
        )
        suggested = {price_key(c, p): current.get(f"{c}_{p}") for c, p in TARIFFS}
        suggested.update({k: v for k, v in opts.items() if k != CONF_TARIFFS})
        suggested.update(user_input or {})
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(vol.Schema(fields), suggested),
            description_placeholders={"periods": ", ".join(p["from"] for p in tariffs)},
            errors=errors,
        )
