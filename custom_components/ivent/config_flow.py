"""Config flow for i-Vent integration."""
from __future__ import annotations

import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult

from .cloud_api import IVentCloudClient
from .const import (
    CONF_API_KEY,
    CONF_HOST,
    CONF_LOCATION_ID,
    DOMAIN,
)

_LOGGER = logging.getLogger(__name__)

DEFAULT_HOST = "192.168.1.164"

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_API_KEY): str,
        vol.Required(CONF_LOCATION_ID): str,
        vol.Optional(CONF_HOST, default=DEFAULT_HOST): str,
    }
)


class IVentConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for i-Vent."""

    VERSION = 3

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step — user enters API key and location ID."""
        errors: dict[str, str] = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            host = user_input.get(CONF_HOST, "")

            try:
                location_id = int(user_input[CONF_LOCATION_ID])
            except ValueError:
                errors[CONF_LOCATION_ID] = "invalid_location_id"

            if not errors:
                # Validate by fetching info from cloud
                cloud = IVentCloudClient(
                    api_key=api_key,
                    location_id=location_id,
                )
                try:
                    info = await cloud.get_info()
                    groups = [
                        g for g in info.get("groups", [])
                        if g.get("devices")
                    ]
                except ConnectionError:
                    errors["base"] = "cannot_connect"
                except Exception:
                    _LOGGER.exception("Error connecting to i-Vent cloud")
                    errors["base"] = "cannot_connect"
                finally:
                    await cloud.close()

                if not errors and not groups:
                    errors["base"] = "no_groups"

                if not errors:
                    # One entry per location
                    await self.async_set_unique_id(f"ivent_{location_id}")
                    self._abort_if_unique_id_configured()

                    return self.async_create_entry(
                        title="i-Vent",
                        data={
                            CONF_API_KEY: api_key,
                            CONF_LOCATION_ID: location_id,
                            CONF_HOST: host,
                        },
                    )

        return self.async_show_form(
            step_id="user",
            data_schema=STEP_USER_DATA_SCHEMA,
            errors=errors,
        )
