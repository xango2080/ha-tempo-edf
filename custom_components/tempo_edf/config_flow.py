"""Config flow : identifiants RTE, puis tarifs en options."""
from __future__ import annotations

import re
from datetime import timedelta
from typing import Any

import voluptuous as vol
from homeassistant.config_entries import ConfigEntry, ConfigFlow, ConfigFlowResult, OptionsFlow
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.util import dt as dt_util
from homeassistant.helpers.selector import (
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .api import RteApiError, RteAuthError, RteClient
from .const import (
    CONF_CLIENT_ID,
    CONF_CLIENT_SECRET,
    CONF_ENEDIS_PRM,
    CONF_ENEDIS_TOKEN,
    CONF_HISTORY_SEASONS,
    DEFAULT_HISTORY_SEASONS,
    DOMAIN,
    MAX_HISTORY_SEASONS,
    TARIFFS,
    price_key,
)

USER_SCHEMA = vol.Schema(
    {vol.Required(CONF_CLIENT_ID): str, vol.Required(CONF_CLIENT_SECRET): str}
)


class TempoConfigFlow(ConfigFlow, domain=DOMAIN):
    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            client = RteClient(
                async_get_clientsession(self.hass),
                user_input[CONF_CLIENT_ID].strip(),
                user_input[CONF_CLIENT_SECRET].strip(),
            )
            try:
                now = dt_util.now()
                await client.async_check(now - timedelta(days=2), now - timedelta(days=1))
            except RteAuthError:
                errors["base"] = "invalid_auth"
            except RteApiError:
                errors["base"] = "cannot_connect"
            else:
                await self.async_set_unique_id(user_input[CONF_CLIENT_ID].strip())
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title="EDF Tempo",
                    data={
                        CONF_CLIENT_ID: user_input[CONF_CLIENT_ID].strip(),
                        CONF_CLIENT_SECRET: user_input[CONF_CLIENT_SECRET].strip(),
                    },
                )
        return self.async_show_form(step_id="user", data_schema=USER_SCHEMA, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        return TempoOptionsFlow()


class TempoOptionsFlow(OptionsFlow):
    """Tarifs TTC (€/kWh), historique RTE et accès Enedis (optionnel)."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            token = (user_input.pop(CONF_ENEDIS_TOKEN, "") or "").strip()
            prm = (user_input.pop(CONF_ENEDIS_PRM, "") or "").strip().replace(" ", "")
            if bool(token) != bool(prm) or (prm and not re.fullmatch(r"\d{14}", prm)):
                errors["base"] = "invalid_enedis"
            else:
                if token:
                    user_input[CONF_ENEDIS_TOKEN] = token
                    user_input[CONF_ENEDIS_PRM] = prm
                return self.async_create_entry(data=user_input)

        price = NumberSelector(
            NumberSelectorConfig(min=0, max=5, step=0.0001, mode=NumberSelectorMode.BOX)
        )
        seasons = NumberSelector(
            NumberSelectorConfig(min=0, max=MAX_HISTORY_SEASONS, step=1, mode=NumberSelectorMode.BOX)
        )
        fields: dict = {vol.Optional(price_key(c, p)): price for c, p in TARIFFS}
        fields[vol.Optional(CONF_HISTORY_SEASONS, default=DEFAULT_HISTORY_SEASONS)] = seasons
        fields[vol.Optional(CONF_ENEDIS_TOKEN)] = TextSelector(
            TextSelectorConfig(type=TextSelectorType.PASSWORD)
        )
        fields[vol.Optional(CONF_ENEDIS_PRM)] = TextSelector(TextSelectorConfig())
        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(
                vol.Schema(fields), user_input or self.config_entry.options
            ),
            errors=errors,
        )
