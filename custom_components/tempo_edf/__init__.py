"""Intégration EDF Tempo : couleurs, tarifs et historique."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import RteClient
from .const import CONF_CLIENT_ID, CONF_CLIENT_SECRET, DOMAIN
from .coordinator import TempoCoordinator

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]

type TempoConfigEntry = ConfigEntry[TempoCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TempoConfigEntry) -> bool:
    client = RteClient(
        async_get_clientsession(hass),
        entry.data[CONF_CLIENT_ID],
        entry.data[CONF_CLIENT_SECRET],
    )
    coordinator = TempoCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator

    @callback
    def _tick(_now) -> None:
        # 06:00 : nouveau jour Tempo + passage en HP ; 22:00 : passage en HC.
        coordinator.async_update_listeners()

    entry.async_on_unload(async_track_time_change(hass, _tick, hour=[6, 22], minute=0, second=1))
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    # Historique des saisons passées : en tâche de fond pour ne pas retarder le démarrage.
    entry.async_create_background_task(hass, coordinator.async_backfill(), f"{DOMAIN}_backfill")
    return True


async def _async_reload(hass: HomeAssistant, entry: TempoConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TempoConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
