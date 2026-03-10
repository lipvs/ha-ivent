"""Sensor platform for i-Vent rekuperator."""
from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER
from .coordinator import IVentCoordinator, IVentState


SENSOR_TYPES: list[dict] = [
    {
        "key": "supply_temp",
        "name": "Dovod temperatura",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:thermometer-plus",
    },
    {
        "key": "exhaust_temp",
        "name": "Odvod temperatura",
        "device_class": SensorDeviceClass.TEMPERATURE,
        "unit": UnitOfTemperature.CELSIUS,
        "icon": "mdi:thermometer-minus",
    },
    {
        "key": "humidity",
        "name": "Vlaznost",
        "device_class": SensorDeviceClass.HUMIDITY,
        "unit": PERCENTAGE,
        "icon": "mdi:water-percent",
    },
]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up i-Vent sensor entities — sensors for each group."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    entities = []
    for coordinator in entry_data["coordinators"]:
        for sensor_type in SENSOR_TYPES:
            entities.append(IVentSensor(coordinator, entry, sensor_type))
        entities.append(IVentFilterSensor(coordinator, entry))
    async_add_entities(entities)


class IVentSensor(CoordinatorEntity[IVentCoordinator], SensorEntity):
    """i-Vent sensor entity."""

    _attr_has_entity_name = True
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(
        self,
        coordinator: IVentCoordinator,
        entry: ConfigEntry,
        sensor_type: dict,
    ) -> None:
        """Initialize sensor."""
        super().__init__(coordinator)
        self._key = sensor_type["key"]
        self._attr_name = sensor_type["name"]
        self._attr_unique_id = f"{coordinator.device_uid}_{self._key}"
        self._attr_device_class = sensor_type["device_class"]
        self._attr_native_unit_of_measurement = sensor_type["unit"]
        self._attr_icon = sensor_type["icon"]
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_uid)},
            "name": f"i-Vent {coordinator.device_name}",
            "manufacturer": MANUFACTURER,
            "model": "HRV",
        }

    @property
    def native_value(self) -> float | int | None:
        """Return sensor value."""
        if self.coordinator.data:
            return getattr(self.coordinator.data, self._key, None)
        return None


class IVentFilterSensor(CoordinatorEntity[IVentCoordinator], SensorEntity):
    """i-Vent filter status sensor."""

    _attr_has_entity_name = True
    _attr_name = "Filter"
    _attr_icon = "mdi:air-filter"

    def __init__(
        self,
        coordinator: IVentCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize filter sensor."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_uid}_filter"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_uid)},
            "name": f"i-Vent {coordinator.device_name}",
            "manufacturer": MANUFACTURER,
            "model": "HRV",
        }

    @property
    def native_value(self) -> str | None:
        """Return filter status."""
        if self.coordinator.data:
            return self.coordinator.data.filter_status
        return None
