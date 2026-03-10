"""Climate platform for i-Vent rekuperator."""
from __future__ import annotations

from homeassistant.components.climate import (
    ClimateEntity,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import UnitOfTemperature
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import (
    CLOUD_FAN_MODE_MAP,
    CLOUD_MODE_RECOVERY,
    CLOUD_SPECIAL_OFF,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import IVentCoordinator


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up i-Vent climate entities — one per group."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        IVentClimate(coordinator, entry)
        for coordinator in entry_data["coordinators"]
    ])


class IVentClimate(CoordinatorEntity[IVentCoordinator], ClimateEntity):
    """Representation of an i-Vent unit as a climate entity."""

    _attr_has_entity_name = True
    _attr_name = None
    _attr_temperature_unit = UnitOfTemperature.CELSIUS
    _attr_supported_features = (
        ClimateEntityFeature.FAN_MODE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )
    _attr_hvac_modes = [HVACMode.OFF, HVACMode.FAN_ONLY, HVACMode.HEAT_COOL]
    _attr_fan_modes = ["off", "low", "medium", "high", "boost"]
    _attr_min_temp = 16
    _attr_max_temp = 33
    _attr_target_temperature_step = 1

    def __init__(
        self,
        coordinator: IVentCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize i-Vent climate entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_uid}_climate"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_uid)},
            "name": f"i-Vent {coordinator.device_name}",
            "manufacturer": MANUFACTURER,
            "model": "HRV",
        }

    @property
    def current_temperature(self) -> float | None:
        """Return extract/exhaust duct temperature as proxy for room temp."""
        if self.coordinator.data:
            return self.coordinator.data.exhaust_temp
        return None

    @property
    def target_temperature(self) -> float | None:
        """Return target temperature setpoint from device."""
        if self.coordinator.data and self.coordinator.data.target_temp is not None:
            return float(self.coordinator.data.target_temp)
        return None

    @property
    def hvac_mode(self) -> HVACMode:
        """Return current HVAC mode."""
        if self.coordinator.data and self.coordinator.data.is_on:
            if self.coordinator.data.mode == "recovery":
                return HVACMode.HEAT_COOL
            return HVACMode.FAN_ONLY
        return HVACMode.OFF

    @property
    def fan_mode(self) -> str | None:
        """Return current fan mode."""
        if self.coordinator.data:
            return self.coordinator.data.fan_speed
        return None

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set HVAC mode via cloud API."""
        cloud = self.coordinator.cloud
        gid = self.coordinator.group_id

        if hvac_mode == HVACMode.OFF:
            await cloud.turn_off(gid)
        elif hvac_mode == HVACMode.HEAT_COOL:
            # Recovery mode at current speed
            speed = self.coordinator.data.cloud_speed if self.coordinator.data else 1
            await cloud.modify_group(
                group_id=gid,
                work_mode=CLOUD_MODE_RECOVERY,
                special_mode=CLOUD_SPECIAL_OFF,
                speed=speed,
            )
        elif hvac_mode == HVACMode.FAN_ONLY:
            speed = self.coordinator.data.cloud_speed if self.coordinator.data else 1
            await cloud.set_work_mode(gid, "IVentOn")
        await self.coordinator.async_request_refresh()

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set fan mode via cloud API."""
        cloud = self.coordinator.cloud
        gid = self.coordinator.group_id

        if fan_mode == "off":
            await cloud.turn_off(gid)
        else:
            speed, special = CLOUD_FAN_MODE_MAP.get(fan_mode, (1, CLOUD_SPECIAL_OFF))
            await cloud.modify_group(
                group_id=gid,
                speed=speed,
                special_mode=special,
            )
        await self.coordinator.async_request_refresh()

    async def async_turn_on(self) -> None:
        """Turn on via cloud API."""
        speed = self.coordinator.data.cloud_speed if self.coordinator.data else 1
        await self.coordinator.cloud.turn_on(self.coordinator.group_id, speed=max(speed, 1))
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self) -> None:
        """Turn off via cloud API."""
        await self.coordinator.cloud.turn_off(self.coordinator.group_id)
        await self.coordinator.async_request_refresh()
