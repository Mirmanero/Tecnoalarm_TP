import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import TecnoalarmTPCoordinator

_LOGGER = logging.getLogger(__name__)


def _device_info(entry: ConfigEntry) -> DeviceInfo:
    return DeviceInfo(
        identifiers={(DOMAIN, entry.entry_id)},
        name=entry.title,
        manufacturer="Tecnoalarm",
        model="TP42 (locale)",
    )


def _guess_device_class(name: str) -> BinarySensorDeviceClass:
    n = name.lower()
    if "porta" in n:
        return BinarySensorDeviceClass.DOOR
    if "fin" in n or "persian" in n or "scorrev" in n or "bascul" in n:
        return BinarySensorDeviceClass.WINDOW
    if "vol" in n or "dt" in n or "vx" in n or "sensore" in n or "movimento" in n:
        return BinarySensorDeviceClass.MOTION
    return BinarySensorDeviceClass.OPENING


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback) -> None:
    coordinator: TecnoalarmTPCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        ZoneBinarySensor(coordinator, idx, entry) for idx in coordinator.zone_indices
    )


class ZoneBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per una zona: on = aperta, off = chiusa."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TecnoalarmTPCoordinator, idx: int, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._entry = entry
        name = coordinator.zone_names.get(idx) or f"Zona {idx + 1}"
        self._attr_name = name
        self._attr_unique_id = f"{entry.entry_id}_zone_{idx}"
        self._attr_device_info = _device_info(entry)
        self._attr_device_class = _guess_device_class(name)

    @property
    def is_on(self) -> bool | None:
        zone = self.coordinator.data["zones"].get(self._idx)
        return bool(zone.open) if zone is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        zone = self.coordinator.data["zones"].get(self._idx)
        return {"excluded": bool(zone.excluded)} if zone is not None else {}
