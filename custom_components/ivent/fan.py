"""Fan platform for i-Vent rekuperator."""
from __future__ import annotations

from typing import Any

from homeassistant.components.fan import FanEntity, FanEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity
from homeassistant.util.percentage import (
    ordered_list_item_to_percentage,
    percentage_to_ordered_list_item,
)

from .const import (
    CLOUD_FAN_MODE_MAP,
    CLOUD_SPECIAL_OFF,
    DOMAIN,
    MANUFACTURER,
)
from .coordinator import IVentCoordinator

ORDERED_NAMED_FAN_SPEEDS = ["low", "medium", "high", "boost"]


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Set up i-Vent fan entities — one per group."""
    entry_data = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([
        IVentFan(coordinator, entry)
        for coordinator in entry_data["coordinators"]
    ])


class IVentFan(CoordinatorEntity[IVentCoordinator], FanEntity):
    """Representation of an i-Vent unit as a fan entity."""

    _attr_has_entity_name = True
    _attr_name = "Ventilator"
    _attr_supported_features = (
        FanEntityFeature.SET_SPEED
        | FanEntityFeature.PRESET_MODE
        | FanEntityFeature.TURN_ON
        | FanEntityFeature.TURN_OFF
    )
    _attr_preset_modes = ORDERED_NAMED_FAN_SPEEDS
    _attr_speed_count = len(ORDERED_NAMED_FAN_SPEEDS)

    def __init__(
        self,
        coordinator: IVentCoordinator,
        entry: ConfigEntry,
    ) -> None:
        """Initialize i-Vent fan entity."""
        super().__init__(coordinator)
        self._attr_unique_id = f"{coordinator.device_uid}_fan"
        self._attr_device_info = {
            "identifiers": {(DOMAIN, coordinator.device_uid)},
            "name": f"i-Vent {coordinator.device_name}",
            "manufacturer": MANUFACTURER,
            "model": "HRV",
        }

    @property
    def is_on(self) -> bool:
        """Return if fan is on."""
        if self.coordinator.data:
            return self.coordinator.data.is_on
        return False

    @property
    def percentage(self) -> int | None:
        """Return current speed percentage."""
        if self.coordinator.data and self.coordinator.data.fan_speed in ORDERED_NAMED_FAN_SPEEDS:
            return ordered_list_item_to_percentage(
                ORDERED_NAMED_FAN_SPEEDS, self.coordinator.data.fan_speed
            )
        return 0

    @property
    def preset_mode(self) -> str | None:
        """Return current preset mode."""
        if self.coordinator.data:
            return self.coordinator.data.fan_speed
        return None

    async def _set_fan(self, fan_mode: str) -> None:
        """Set fan speed via cloud API."""
        cloud = self.coordinator.cloud
        gid = self.coordinator.group_id

        if fan_mode == "off":
            await cloud.turn_off(gid)
        else:
            speed, special = CLOUD_FAN_MODE_MAP.get(fan_mode, (1, CLOUD_SPECIAL_OFF))
            await cloud.modify_group(group_id=gid, speed=speed, special_mode=special)
        await self.coordinator.async_request_refresh()

    async def async_set_percentage(self, percentage: int) -> None:
        """Set fan speed percentage."""
        if percentage == 0:
            await self._set_fan("off")
        else:
            speed = percentage_to_ordered_list_item(ORDERED_NAMED_FAN_SPEEDS, percentage)
            await self._set_fan(speed)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set preset mode."""
        await self._set_fan(preset_mode)

    async def async_turn_on(
        self,
        percentage: int | None = None,
        preset_mode: str | None = None,
        **kwargs: Any,
    ) -> None:
        """Turn on fan."""
        if preset_mode:
            await self._set_fan(preset_mode)
        elif percentage:
            await self.async_set_percentage(percentage)
        else:
            speed = self.coordinator.data.cloud_speed if self.coordinator.data else 1
            await self.coordinator.cloud.turn_on(self.coordinator.group_id, speed=max(speed, 1))
            await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Turn off fan."""
        await self.coordinator.cloud.turn_off(self.coordinator.group_id)
        await self.coordinator.async_request_refresh()
