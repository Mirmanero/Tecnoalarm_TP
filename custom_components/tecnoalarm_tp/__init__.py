import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import (
    CONF_CODE,
    CONF_PASSPHRASE,
    CONF_UPDATE_INTERVAL,
    CONNECT_TIMEOUT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    PROBE_N_PROGRAMS,
    PROBE_N_ZONES,
)
from .coordinator import TecnoalarmTPCoordinator
from .tecnoalarm_tp42 import TP42Panel

_LOGGER = logging.getLogger(__name__)

PLATFORMS = ["switch", "binary_sensor", "sensor"]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    _LOGGER.info("Setting up Tecnoalarm TP entry for %s", entry.data.get("host"))

    data = entry.data
    update_interval = entry.options.get(
        CONF_UPDATE_INTERVAL, data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL)
    )

    panel = TP42Panel(
        data["host"],
        data["port"],
        code=data[CONF_CODE],
        passphrase=data.get(CONF_PASSPHRASE, ""),
        n_programs=PROBE_N_PROGRAMS,
        n_zones=PROBE_N_ZONES,
        timeout=CONNECT_TIMEOUT,
    )

    coordinator = TecnoalarmTPCoordinator(hass, panel, update_interval)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator: TecnoalarmTPCoordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_close()
    return unload_ok


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    _LOGGER.info("Options updated; reloading entry")
    await hass.config_entries.async_reload(entry.entry_id)
