"""The i-Vent Rekuperator integration."""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .cloud_api import IVentCloudClient
from .const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_LOCATION_ID,
    DOMAIN,
)
from .coordinator import IVentCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CLIMATE, Platform.FAN, Platform.SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up i-Vent from a config entry.

    Creates one IVentCloudClient for the location, then discovers all groups
    and creates a coordinator per group. Entity platforms iterate over all
    coordinators to create entities for every room.
    """
    data = entry.data

    cloud = IVentCloudClient(
        api_key=data[CONF_API_KEY],
        location_id=data[CONF_LOCATION_ID],
        session=async_get_clientsession(hass),
    )

    # Discover all groups with devices
    try:
        info = await cloud.get_info()
    except Exception as exc:
        _LOGGER.error("Failed to fetch i-Vent cloud info: %s", exc)
        raise

    groups = [g for g in info.get("groups", []) if g.get("devices")]
    location_id = data[CONF_LOCATION_ID]

    coordinators: list[IVentCoordinator] = []
    for group in groups:
        group_id = group["id"]
        group_name = group["name"]
        device_uid = f"ivent_{location_id}_{group_id}"

        coordinator = IVentCoordinator(
            hass,
            cloud_client=cloud,
            group_id=group_id,
            device_uid=device_uid,
            device_name=group_name,
        )
        await coordinator.async_config_entry_first_refresh()
        coordinators.append(coordinator)

    hass.data.setdefault(DOMAIN, {})
    hass.data[DOMAIN][entry.entry_id] = {
        "cloud": cloud,
        "coordinators": coordinators,
    }

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        entry_data = hass.data[DOMAIN].pop(entry.entry_id)
        for coordinator in entry_data["coordinators"]:
            await coordinator.async_shutdown()
    return unload_ok
