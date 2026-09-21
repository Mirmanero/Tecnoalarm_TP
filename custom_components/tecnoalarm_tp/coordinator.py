"""Coordinator per l'integrazione Tecnoalarm TP.

Mantiene una connessione persistente verso la centrale (una sola sessione
autenticata per tutta la vita della config entry, come raccomandato dalla
libreria tecnoalarm_tp42) e la interroga a intervalli regolari.
"""
import logging
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import ZONE_POLL_EVERY_N_TICKS
from .tecnoalarm_tp42 import TP42Panel

_LOGGER = logging.getLogger(__name__)


class TecnoalarmTPCoordinator(DataUpdateCoordinator):
    def __init__(self, hass: HomeAssistant, panel: TP42Panel, update_interval: int) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name="TecnoalarmTPCoordinator",
            update_interval=timedelta(seconds=update_interval),
        )
        self.panel = panel
        self.program_indices: list[int] = []
        self.zone_indices: list[int] = []
        self.program_names: dict[int, str] = {}
        self.zone_names: dict[int, str] = {}
        self._tick = 0
        self._last_zones: dict[int, object] = {}
        self._last_battery: dict[int, bool] = {}

    async def _async_setup(self) -> None:
        """Connessione iniziale + individuazione di programmi/zone configurati."""
        _LOGGER.debug("Setup Tecnoalarm TP coordinator")
        try:
            await self.hass.async_add_executor_job(self.panel.connect)

            program_names = await self.hass.async_add_executor_job(self.panel.program_names)
            zones = await self.hass.async_add_executor_job(self.panel.get_zones)
        except Exception as err:
            raise UpdateFailed(f"Connessione/autenticazione fallita: {err}") from err

        self.program_indices = [i for i, name in enumerate(program_names) if name.strip()]
        self.program_names = {i: program_names[i] for i in self.program_indices}

        self.zone_indices = [z.n - 1 for z in zones if z.configured]
        self.zone_names = {z.n - 1: z.name for z in zones if z.configured}
        self._last_zones = {z.n - 1: z for z in zones if z.configured}

        try:
            battery = await self.hass.async_add_executor_job(self.panel.get_zone_battery)
            self._last_battery = {n - 1: low for n, low in battery.items()}
        except Exception as err:
            _LOGGER.warning("Lettura iniziale batteria zone fallita: %s", err)

        _LOGGER.debug(
            "Trovati %d programmi e %d zone configurate",
            len(self.program_indices), len(self.zone_indices),
        )

    def _poll(self):
        """Eseguito nell'executor: legge programmi (sempre) e zone (ogni N tick)."""
        programs = self.panel.program_states()

        self._tick += 1
        if self._tick % ZONE_POLL_EVERY_N_TICKS == 0:
            zones = self.panel.get_zones(names=[self.zone_names.get(i, "") for i in range(self.panel.n_zones)])
            self._last_zones = {z.n - 1: z for z in zones if z.configured}

            try:
                battery = self.panel.get_zone_battery()
                self._last_battery = {n - 1: low for n, low in battery.items()}
            except Exception as err:
                _LOGGER.warning("Lettura batteria zone fallita, mantengo l'ultimo valore noto: %s", err)

        if not self.panel.connected:
            raise UpdateFailed("Connessione alla centrale persa")

        return programs

    async def _async_update_data(self):
        try:
            programs = await self.hass.async_add_executor_job(self._poll)
        except UpdateFailed:
            raise
        except Exception as err:
            raise UpdateFailed(f"Errore aggiornamento Tecnoalarm TP: {err}") from err

        program_data = {i: programs[i] for i in self.program_indices if i < len(programs)}
        return {
            "programs": program_data,
            "zones": dict(self._last_zones),
            "battery": dict(self._last_battery),
        }

    async def async_arm(self, idx: int) -> bool:
        return await self.hass.async_add_executor_job(self.panel.arm, idx + 1)

    async def async_disarm(self, idx: int) -> bool:
        return await self.hass.async_add_executor_job(self.panel.disarm, idx + 1)

    async def async_close(self) -> None:
        await self.hass.async_add_executor_job(self.panel.close)
