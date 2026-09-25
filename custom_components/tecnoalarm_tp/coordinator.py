"""Coordinator per l'integrazione Tecnoalarm TP.

Mantiene una connessione persistente verso la centrale (una sola sessione
autenticata per tutta la vita della config entry, come raccomandato dalla
libreria tecnoalarm_tp42) e la interroga a intervalli regolari.
"""
import logging
import time
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import BATTERY_POLL_INTERVAL_SECONDS, ZONE_POLL_EVERY_N_TICKS
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
        self.model_id: int | None = None
        self.model_name: str = "TP42"
        self.program_indices: list[int] = []
        self.zone_indices: list[int] = []
        self.program_names: dict[int, str] = {}
        self.zone_names: dict[int, str] = {}
        self._tick = 0
        self._last_zones: dict[int, object] = {}
        self._last_battery: dict[int, bool] = {}
        self._last_battery_monotonic: float = 0.0
        # Zone aperte per programma (idx 0-based -> lista numeri zona
        # 1-based), lette dalla centrale stessa (comando 24) - vedi _poll.
        self._last_open_zones_by_program: dict[int, list[int]] = {}
        # Zone isolate automaticamente per permettere l'ultimo arm di un
        # programma (idx 0-based -> lista numeri zona 1-based), da
        # reintegrare al disarm dello stesso programma.
        self._auto_isolated_zones: dict[int, list[int]] = {}

    async def _async_setup(self) -> None:
        """Connessione iniziale + individuazione di programmi/zone configurati."""
        _LOGGER.debug("Setup Tecnoalarm TP coordinator")
        try:
            await self.hass.async_add_executor_job(self.panel.connect)

            try:
                info = await self.hass.async_add_executor_job(self.panel.get_panel_info)
                self.model_id = info["model_id"]
                self.model_name = info["model"]
                self.panel.n_programs = info["max_programs"]
                self.panel.n_zones = info["max_zones"]
                _LOGGER.info(
                    "Centrale rilevata: %s (model_id=%s) - %d programmi, %d zone max",
                    self.model_name, self.model_id, self.panel.n_programs, self.panel.n_zones,
                )
            except Exception as err:
                _LOGGER.warning(
                    "Rilevamento modello centrale fallito, uso i limiti di default (%d programmi, %d zone): %s",
                    self.panel.n_programs, self.panel.n_zones, err,
                )

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
            self._last_battery_monotonic = time.monotonic()
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

            for idx in self.program_indices:
                try:
                    self._last_open_zones_by_program[idx] = self.panel.list_open_zones_for_program(idx + 1)
                except Exception as err:
                    _LOGGER.warning(
                        "Lettura zone aperte per il programma %d fallita, mantengo l'ultimo valore noto: %s",
                        idx + 1, err,
                    )

        # La batteria cambia lentissimamente: intervallo proprio, molto piu'
        # largo di quello delle zone (vedi BATTERY_POLL_INTERVAL_SECONDS).
        if time.monotonic() - self._last_battery_monotonic >= BATTERY_POLL_INTERVAL_SECONDS:
            try:
                battery = self.panel.get_zone_battery()
                self._last_battery = {n - 1: low for n, low in battery.items()}
                self._last_battery_monotonic = time.monotonic()
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
            "open_zones_by_program": dict(self._last_open_zones_by_program),
        }

    def _arm_with_isolation(self, idx: int) -> tuple[bool, list[int]]:
        """Esegue nell'executor: isola le zone aperte del programma (se ce ne
        sono), poi arma. Se l'isolamento di una zona fallisce, reintegra
        quelle gia' isolate in questo tentativo e rinuncia all'arm (non ha
        senso armare con zone aperte non escluse). Se l'arm stesso fallisce
        dopo aver isolato zone, le reintegra subito (nessuna isolazione
        "orfana" senza un arm riuscito a giustificarla)."""
        zone_prog = idx + 1
        try:
            open_zones = self.panel.list_open_zones_for_program(zone_prog)
        except Exception as err:
            _LOGGER.warning(
                "Impossibile leggere le zone aperte del programma %d, procedo comunque con l'arm: %s",
                zone_prog, err,
            )
            open_zones = []

        isolated: list[int] = []
        for zone in open_zones:
            try:
                if not self.panel.isolate_zone(zone):
                    raise RuntimeError("isolamento rifiutato (NAK)")
                isolated.append(zone)
            except Exception as err:
                _LOGGER.error(
                    "Isolamento zona %d fallito (%s): rinuncio all'arm del programma %d e reintegro le zone gia' isolate",
                    zone, err, zone_prog,
                )
                for z in isolated:
                    try:
                        self.panel.reintegrate_zone(z)
                    except Exception:
                        pass
                return False, []

        ok = self.panel.arm(zone_prog)
        if ok:
            if isolated:
                self._auto_isolated_zones[idx] = isolated
            return True, isolated

        for z in isolated:
            try:
                self.panel.reintegrate_zone(z)
            except Exception:
                pass
        return False, []

    def _disarm_with_reintegration(self, idx: int) -> tuple[bool, list[int]]:
        """Esegue nell'executor: disarma, poi reintegra le zone che erano
        state isolate automaticamente per l'ultimo arm di questo programma."""
        ok = self.panel.disarm(idx + 1)
        reintegrated: list[int] = []
        if ok:
            for zone in self._auto_isolated_zones.pop(idx, []):
                try:
                    if self.panel.reintegrate_zone(zone):
                        reintegrated.append(zone)
                    else:
                        _LOGGER.warning("Reintegrazione zona %d rifiutata (NAK)", zone)
                except Exception as err:
                    _LOGGER.warning("Reintegrazione zona %d fallita: %s", zone, err)
        return ok, reintegrated

    async def async_arm(self, idx: int) -> bool:
        ok, isolated = await self.hass.async_add_executor_job(self._arm_with_isolation, idx)
        if ok and isolated:
            names = ", ".join(self.zone_names.get(z - 1, f"Zona {z}") for z in isolated)
            pname = self.program_names.get(idx, f"Programma {idx + 1}")
            _LOGGER.warning("Arm %s: zone aperte escluse automaticamente: %s", pname, names)
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": "Tecnoalarm TP - Zone escluse",
                    "message": (
                        f"Inserendo '{pname}' sono state escluse automaticamente le zone "
                        f"aperte: {names}. Verranno reintegrate al disinserimento."
                    ),
                    "notification_id": f"tecnoalarm_tp_isolated_{idx}",
                },
            )
        return ok

    async def async_disarm(self, idx: int) -> bool:
        ok, reintegrated = await self.hass.async_add_executor_job(self._disarm_with_reintegration, idx)
        if reintegrated:
            names = ", ".join(self.zone_names.get(z - 1, f"Zona {z}") for z in reintegrated)
            _LOGGER.info("Disarm programma %d: zone reintegrate: %s", idx + 1, names)
        return ok

    async def async_close(self) -> None:
        await self.hass.async_add_executor_job(self.panel.close)
