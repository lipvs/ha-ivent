"""Data update coordinator for i-Vent."""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import timedelta

from homeassistant.core import HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .cloud_api import IVentCloudClient
from .const import (
    CLOUD_SPECIAL_BOOST,
    CLOUD_SPEED_TO_FAN,
    DOMAIN,
    UPDATE_INTERVAL,
)

_LOGGER = logging.getLogger(__name__)


@dataclass
class IVentState:
    """Merged state from cloud API + optional local UDP sensors."""

    # Identity
    device_uid: str
    name: str

    # From cloud API (authoritative for control state)
    is_on: bool
    fan_speed: str  # off, low, medium, high, boost
    mode: str  # recovery, off, supply
    work_mode: str  # raw cloud work_mode string
    special_mode: str  # raw cloud special_mode string
    cloud_speed: int  # raw 1-3

    # From local UDP sensors (or cloud if UDP unavailable)
    supply_temp: float | None
    exhaust_temp: float | None
    humidity: float | None
    target_temp: int | None
    filter_status: str | None
    firmware: str | None


class IVentCoordinator(DataUpdateCoordinator[IVentState]):
    """Coordinator to manage fetching i-Vent data via cloud API + local UDP."""

    def __init__(
        self,
        hass: HomeAssistant,
        cloud_client: IVentCloudClient,
        group_id: int,
        device_uid: str,
        device_name: str,
        udp_client=None,
    ) -> None:
        """Initialize coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            update_interval=timedelta(seconds=UPDATE_INTERVAL),
        )
        self.cloud = cloud_client
        self.group_id = group_id
        self.device_uid = device_uid
        self.device_name = device_name
        self.udp_client = udp_client

    async def _async_update_data(self) -> IVentState:
        """Fetch data from cloud API and optionally local UDP."""
        # 1. Get cloud state (authoritative for mode/speed/on-off)
        try:
            group = await self.cloud.get_group_state(self.group_id)
        except Exception as err:
            raise UpdateFailed(f"Cloud API error: {err}") from err

        if group is None:
            raise UpdateFailed(f"Group {self.group_id} not found in cloud")

        remote = group.get("remote", {})
        work_mode = remote.get("work_mode", "IVentWorkOff")
        special_mode = remote.get("special_mode", "IVentSpecialOff")
        cloud_speed = remote.get("remote_control_speed", 1)

        is_on = work_mode != "IVentWorkOff"
        is_boost = special_mode == CLOUD_SPECIAL_BOOST

        # Map cloud state to HA fan mode
        fan_speed = CLOUD_SPEED_TO_FAN.get((cloud_speed, is_boost), "low")
        if not is_on:
            fan_speed = "off"

        # Map cloud work_mode to HA mode name
        if not is_on:
            mode = "off"
        elif "Recuperation" in work_mode or "Recovery" in work_mode:
            mode = "recovery"
        elif "Bypass" in work_mode:
            mode = "supply"
        else:
            mode = "recovery"  # default

        # 2. Get local sensor data from UDP (optional)
        supply_temp = None
        exhaust_temp = None
        humidity = None
        target_temp = None
        firmware = None

        if self.udp_client:
            try:
                udp_status = await self.udp_client.get_status(self.device_uid)
                supply_temp = udp_status.supply_temp
                exhaust_temp = udp_status.exhaust_temp
                humidity = udp_status.humidity
                target_temp = udp_status.target_temp
                firmware = udp_status.firmware
            except Exception:
                _LOGGER.debug("UDP sensor read failed, using cloud only", exc_info=True)

        return IVentState(
            device_uid=self.device_uid,
            name=self.device_name,
            is_on=is_on,
            fan_speed=fan_speed,
            mode=mode,
            work_mode=work_mode,
            special_mode=special_mode,
            cloud_speed=cloud_speed,
            supply_temp=supply_temp,
            exhaust_temp=exhaust_temp,
            humidity=humidity,
            target_temp=target_temp,
            filter_status=None,
            firmware=firmware,
        )

    async def async_shutdown(self) -> None:
        """Clean up on shutdown."""
        await super().async_shutdown()
        await self.cloud.close()
        if self.udp_client:
            await self.udp_client.disconnect()
