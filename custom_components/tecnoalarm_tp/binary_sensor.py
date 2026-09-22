import logging

from homeassistant.components.binary_sensor import BinarySensorDeviceClass, BinarySensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo, EntityCategory
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


def _zone_label(coordinator: TecnoalarmTPCoordinator, idx: int) -> str:
    name = coordinator.zone_names.get(idx) or ""
    return f"Zona {idx + 1} {name}".strip()


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
    entities = []
    for idx in coordinator.zone_indices:
        entities.append(ZoneBinarySensor(coordinator, idx, entry))
        entities.append(ZoneBatteryBinarySensor(coordinator, idx, entry))
    async_add_entities(entities)


class ZoneBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per una zona: on = aperta, off = chiusa."""

    _attr_has_entity_name = True

    def __init__(self, coordinator: TecnoalarmTPCoordinator, idx: int, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._entry = entry
        self._attr_name = _zone_label(coordinator, idx)
        self._attr_unique_id = f"{entry.entry_id}_zone_{idx}"
        self._attr_device_info = _device_info(entry)
        self._attr_device_class = _guess_device_class(coordinator.zone_names.get(idx) or "")

    @property
    def is_on(self) -> bool | None:
        zone = self.coordinator.data["zones"].get(self._idx)
        return bool(zone.open) if zone is not None else None

    @property
    def extra_state_attributes(self) -> dict:
        zone = self.coordinator.data["zones"].get(self._idx)
        return {"excluded": bool(zone.excluded)} if zone is not None else {}


class ZoneBatteryBinarySensor(CoordinatorEntity, BinarySensorEntity):
    """Binary sensor per la batteria di una zona: on = batteria scarica."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.BATTERY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: TecnoalarmTPCoordinator, idx: int, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._idx = idx
        self._entry = entry
        self._attr_name = f"{_zone_label(coordinator, idx)} batteria"
        self._attr_unique_id = f"{entry.entry_id}_zone_{idx}_battery"
        self._attr_device_info = _device_info(entry)

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.data["battery"].get(self._idx)
