"""Intégration EDF Tempo : couleurs, tarifs et historique."""
from __future__ import annotations

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.event import async_track_time_change

from .api import RteClient
from .const import ANNOUNCE_SLOTS, ANNOUNCE_SLOTS_RTE, CONF_CLIENT_ID, CONF_CLIENT_SECRET, CONF_ENEDIS_PRM, CONF_ENEDIS_TOKEN, CONF_TARIFFS, DOMAIN
from .enedis_api import ConsoApiClient
from .enedis_parse import PARIS
from .enedis_sync import EnedisSync
from .jourtempo_api import JourTempoClient
from .coordinator import TempoCoordinator
from .services import async_register_services
from .tariffs import DEFAULT_TARIFFS

PLATFORMS = [Platform.SENSOR, Platform.CALENDAR]

type TempoConfigEntry = ConfigEntry[TempoCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: TempoConfigEntry) -> bool:
    if CONF_TARIFFS not in entry.options:  # première fois : historique des grilles Tempo livré avec l'intégration
        hass.config_entries.async_update_entry(
            entry, options={**entry.options, CONF_TARIFFS: [dict(p) for p in DEFAULT_TARIFFS]}
        )
    session = async_get_clientsession(hass)
    rte = None
    if entry.data.get(CONF_CLIENT_ID) and entry.data.get(CONF_CLIENT_SECRET):
        rte = RteClient(session, entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET])
    coordinator = TempoCoordinator(hass, entry, JourTempoClient(session), rte)
    token = entry.options.get(CONF_ENEDIS_TOKEN)
    prm = entry.options.get(CONF_ENEDIS_PRM)
    if token and prm:
        coordinator.enedis = ConsoApiClient(session, token, prm)
        coordinator.enedis_sync = EnedisSync(hass, entry, coordinator, coordinator.enedis)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    async_register_services(hass)

    @callback
    def _tick(_now) -> None:
        # 00:00 : changement de grille éventuel ; 06:00 : nouveau jour Tempo + HP ; 22:00 : HC.
        coordinator.async_update_listeners()

    slots = ANNOUNCE_SLOTS | (ANNOUNCE_SLOTS_RTE if coordinator.has_rte else set())

    @callback
    def _announce_tick(now) -> None:
        # Vérifie la couleur de demain juste après chaque relevé de la source ; sans effet si elle est déjà connue.
        local = now.astimezone(PARIS)
        if (local.hour, local.minute) in slots:
            entry.async_create_background_task(hass, coordinator.async_request_refresh(), f"{DOMAIN}_announce")

    entry.async_on_unload(
        async_track_time_change(hass, _announce_tick, hour=[10, 11, 12, 13], minute=[5, 35, 50], second=20)
    )
    entry.async_on_unload(async_track_time_change(hass, _tick, hour=[0, 6, 22], minute=0, second=1))
    entry.async_on_unload(entry.add_update_listener(_async_reload))

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    if coordinator.enedis_sync is not None:
        await coordinator.enedis_sync.async_setup()
    # Historique des saisons passées : en tâche de fond pour ne pas retarder le démarrage.
    entry.async_create_background_task(hass, coordinator.async_backfill(), f"{DOMAIN}_backfill")
    return True


async def _async_reload(hass: HomeAssistant, entry: TempoConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: TempoConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
