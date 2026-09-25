import logging

from homeassistant.components.switch import SwitchEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TecnoalarmTPCoordinator

_LOGGER = logging.getLogger(__name__)


def _device_info(coordinator: TecnoalarmTPCoordinator, entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Tecnoalarm",
        model=f"{coordinator.model_name} (locale)",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: TecnoalarmTPCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ProgramSwitch(coordinator, idx, entry) for idx in coordinator.program_indices
    )


class ProgramSwitch(CoordinatorEntity, SwitchEntity):
    """Switch che arma/disarma direttamente un programma della centrale."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TecnoalarmTPCoordinator, idx: int, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._entry = entry
        self._attr_name = coordinator.program_names.get(idx) or f"Programma {idx + 1}"
        self._attr_unique_id = f"{entry.entry_id}_program_{idx}"
        self._attr_device_info = _device_info(coordinator, entry)

    @property
    def is_on(self) -> bool:
        program = self.coordinator.data["programs"].get(self._idx)
        return bool(program and program.armed)

    @property
    def icon(self) -> str:
        return "mdi:shield-lock" if self.is_on else "mdi:shield-lock-open"

    async def async_turn_on(self, **kwargs) -> None:
        if await self.coordinator.async_arm(self._idx):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Arm fallito per il programma %s", self._attr_name)

    async def async_turn_off(self, **kwargs) -> None:
        if await self.coordinator.async_disarm(self._idx):
            await self.coordinator.async_request_refresh()
        else:
            _LOGGER.error("Disarm fallito per il programma %s", self._attr_name)
