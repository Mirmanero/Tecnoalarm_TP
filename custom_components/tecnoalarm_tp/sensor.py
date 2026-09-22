from homeassistant.components.sensor import SensorDeviceClass, SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TecnoalarmTPCoordinator
from .tecnoalarm_tp42 import PROGRAM_STATES


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Tecnoalarm",
        model="TP42 (locale)",
    )


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: TecnoalarmTPCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ProgramStateSensor(coordinator, idx, entry) for idx in coordinator.program_indices
    )


class ProgramStateSensor(CoordinatorEntity, SensorEntity):
    """Sensore con lo stato testuale completo di un programma (non solo
    inserito/disinserito, ma anche pre-uscita/in uscita/parziale/ecc.)."""

    _attr_has_entity_name = True
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = list(PROGRAM_STATES.values())
    _attr_icon = "mdi:shield-home"

    def __init__(self, coordinator: TecnoalarmTPCoordinator, idx: int, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._entry = entry
        base_name = coordinator.program_names.get(idx) or f"Programma {idx + 1}"
        self._attr_name = f"Stato Programma {base_name}"
        self._attr_unique_id = f"{entry.entry_id}_program_{idx}_state"
        self._attr_device_info = _device_info(entry)

    @property
    def native_value(self) -> str | None:
        program = self.coordinator.data["programs"].get(self._idx)
        return program.state if program is not None else None
