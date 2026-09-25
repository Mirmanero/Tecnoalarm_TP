import logging
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.core import callback

from .const import (
    CONF_CODE,
    CONF_PASSPHRASE,
    CONF_UPDATE_INTERVAL,
    CONNECT_TIMEOUT,
    DEFAULT_PORT,
    DEFAULT_UPDATE_INTERVAL,
    DOMAIN,
    MAX_UPDATE_INTERVAL,
    MIN_UPDATE_INTERVAL,
    PROBE_N_PROGRAMS,
    PROBE_N_ZONES,
)
from .tecnoalarm_tp42 import TP42Panel, TP42Error

_LOGGER = logging.getLogger(__name__)

VOL_SCHEMA_USER = vol.Schema(
    {
        vol.Required("host"): str,
        vol.Required("port", default=DEFAULT_PORT): vol.All(vol.Coerce(int), vol.Range(min=1, max=65535)),
        vol.Required(CONF_CODE): str,
        vol.Optional(CONF_PASSPHRASE, default=""): str,
        vol.Optional(CONF_UPDATE_INTERVAL, default=DEFAULT_UPDATE_INTERVAL): vol.All(
            vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
        ),
    }
)


def _try_connect(host, port, code, passphrase):
    with TP42Panel(
        host, port, code=code, passphrase=passphrase,
        n_programs=PROBE_N_PROGRAMS, n_zones=PROBE_N_ZONES, timeout=CONNECT_TIMEOUT,
    ):
        pass


class ConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        errors: dict[str, str] = {}

        if user_input is not None:
            host = user_input["host"].strip()
            port = int(user_input["port"])

            await self.async_set_unique_id(f"{host}:{port}")
            self._abort_if_unique_id_configured()

            try:
                await self.hass.async_add_executor_job(
                    _try_connect,
                    host,
                    port,
                    user_input[CONF_CODE],
                    user_input.get(CONF_PASSPHRASE, ""),
                )
            except TP42Error as err:
                _LOGGER.debug("Autenticazione fallita: %s", err)
                errors["base"] = "cannot_connect"
            except Exception as err:  # noqa: BLE001
                _LOGGER.debug("Errore di connessione: %s", err)
                errors["base"] = "cannot_connect"

            if not errors:
                return self.async_create_entry(
                    title=f"Tecnoalarm TP ({host})",
                    data={
                        "host": host,
                        "port": port,
                        CONF_CODE: user_input[CONF_CODE],
                        CONF_PASSPHRASE: user_input.get(CONF_PASSPHRASE, ""),
                        CONF_UPDATE_INTERVAL: user_input[CONF_UPDATE_INTERVAL],
                    },
                )

        return self.async_show_form(step_id="user", data_schema=VOL_SCHEMA_USER, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        return OptionsFlowHandler(config_entry)


class OptionsFlowHandler(config_entries.OptionsFlow):
    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        super().__init__()
        self._config_entry = config_entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> config_entries.ConfigFlowResult:
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current = self._config_entry.options.get(
            CONF_UPDATE_INTERVAL,
            self._config_entry.data.get(CONF_UPDATE_INTERVAL, DEFAULT_UPDATE_INTERVAL),
        )
        schema = vol.Schema(
            {
                vol.Required(CONF_UPDATE_INTERVAL, default=current): vol.All(
                    vol.Coerce(int), vol.Range(min=MIN_UPDATE_INTERVAL, max=MAX_UPDATE_INTERVAL)
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)
