"""Cloud REST API client for i-Vent control commands.

Uses the official i-Vent Smart Home Cloud API at https://cloud.i-vent.com/api/v1.
Control commands go through the cloud (master device proxies to local devices).
Sensor data is still read locally via UDP for low latency.
"""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

_LOGGER = logging.getLogger(__name__)

CLOUD_BASE_URL = "https://cloud.i-vent.com/api/v1"


class IVentCloudClient:
    """REST API client for i-Vent cloud control."""

    def __init__(
        self,
        api_key: str,
        location_id: int,
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._api_key = api_key
        self._location_id = location_id
        self._session = session
        self._owns_session = False

    async def _ensure_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
            self._owns_session = True
        return self._session

    async def close(self) -> None:
        if self._owns_session and self._session and not self._session.closed:
            await self._session.close()

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }

    async def get_info(self) -> dict[str, Any]:
        """GET /live/{loc_id}/info — full system state."""
        session = await self._ensure_session()
        url = f"{CLOUD_BASE_URL}/live/{self._location_id}/info"
        async with session.get(url, headers=self._headers()) as resp:
            if resp.status == 404:
                raise ConnectionError("i-Vent cloud: location not found or device unreachable")
            resp.raise_for_status()
            return await resp.json()

    async def modify_group(
        self,
        group_id: int,
        work_mode: str = "IVentRecuperation1",
        special_mode: str = "IVentSpecialOff",
        speed: int = 1,
        bypass_rotation: str = "BypassForward",
        remote_control_work_mode: str = "Normal",
    ) -> bool:
        """POST /live/{loc_id}/modify_group — send control command."""
        session = await self._ensure_session()
        url = f"{CLOUD_BASE_URL}/live/{self._location_id}/modify_group"
        payload = {
            "group_id": group_id,
            "remote_work_mode": {
                "special_mode": special_mode,
                "work_mode": work_mode,
                "bypass_rotation": bypass_rotation,
                "remote_control_work_mode": remote_control_work_mode,
                "remote_control_speed": speed,
            },
        }
        _LOGGER.debug("Cloud modify_group: %s", payload)
        async with session.post(url, headers=self._headers(), json=payload) as resp:
            if resp.status == 200:
                _LOGGER.info(
                    "Cloud modify_group OK: group=%d mode=%s special=%s speed=%d",
                    group_id, work_mode, special_mode, speed,
                )
                return True
            body = await resp.text()
            _LOGGER.error("Cloud modify_group FAILED: %d %s", resp.status, body)
            return False

    async def get_group_state(self, group_id: int) -> dict[str, Any] | None:
        """Get state for a specific group from cloud info."""
        try:
            info = await self.get_info()
        except Exception:
            _LOGGER.warning("Cloud get_group_state failed", exc_info=True)
            return None
        for group in info.get("groups", []):
            if group.get("id") == group_id:
                return group
        return None

    async def set_fan_speed(self, group_id: int, speed: int) -> bool:
        """Set fan speed (1-3). Preserves current mode."""
        group = await self.get_group_state(group_id)
        if group:
            remote = group["remote"]
            return await self.modify_group(
                group_id=group_id,
                work_mode=remote["work_mode"],
                special_mode=remote["special_mode"],
                speed=speed,
                bypass_rotation=remote["bypass_rotation"],
                remote_control_work_mode=remote["remote_control_work_mode"],
            )
        return await self.modify_group(group_id=group_id, speed=speed)

    async def set_work_mode(self, group_id: int, work_mode: str) -> bool:
        """Set work mode. Preserves current speed."""
        group = await self.get_group_state(group_id)
        speed = group["remote"]["remote_control_speed"] if group else 1
        return await self.modify_group(
            group_id=group_id,
            work_mode=work_mode,
            speed=speed,
        )

    async def turn_off(self, group_id: int) -> bool:
        """Turn off the group."""
        return await self.modify_group(
            group_id=group_id,
            work_mode="IVentWorkOff",
            special_mode="IVentSpecialOff",
            speed=1,
        )

    async def turn_on(self, group_id: int, speed: int = 1) -> bool:
        """Turn on in recovery mode."""
        return await self.modify_group(
            group_id=group_id,
            work_mode="IVentRecuperation1",
            special_mode="IVentSpecialOff",
            speed=speed,
        )

    async def set_boost(self, group_id: int, speed: int = 3) -> bool:
        """Activate boost mode."""
        return await self.modify_group(
            group_id=group_id,
            work_mode="IVentRecuperation1",
            special_mode="IVentBoost",
            speed=speed,
        )
