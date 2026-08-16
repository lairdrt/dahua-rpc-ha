"""Config flow for Dahua RPC."""

from __future__ import annotations

from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant import config_entries

from dahua_rpc import DahuaClient
from dahua_rpc.exceptions import AuthenticationError, DahuaError, TransportError

from . import recorder_info
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_HOST): str,
        vol.Required(CONF_USERNAME): str,
        vol.Required(CONF_PASSWORD): str,
    }
)


class DahuaRpcConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle the Dahua RPC config flow."""

    VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ):
        """Validate recorder credentials and create an entry."""
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {
                CONF_HOST: user_input[CONF_HOST].strip(),
                CONF_USERNAME: user_input[CONF_USERNAME].strip(),
                CONF_PASSWORD: user_input[CONF_PASSWORD],
            }
            try:
                info = await self._async_validate(data)
            except AuthenticationError:
                errors["base"] = "invalid_auth"
            except (TransportError, TimeoutError, OSError):
                errors["base"] = "cannot_connect"
            except (DahuaError, ValueError):
                errors["base"] = "unknown"
            except Exception:  # Recorder validation must not leak sensitive details.
                errors["base"] = "unknown"
            else:
                await self.async_set_unique_id(info.serial)
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info.name, data=data)

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def _async_validate(self, data: dict[str, Any]):
        client = await self.hass.async_add_executor_job(
            partial(
                DahuaClient,
                host=data[CONF_HOST],
                username=data[CONF_USERNAME],
                password=data[CONF_PASSWORD],
            )
        )
        try:
            return recorder_info(client)
        finally:
            await self.hass.async_add_executor_job(client.close)
