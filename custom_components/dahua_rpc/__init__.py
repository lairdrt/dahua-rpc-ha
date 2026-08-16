"""Dahua RPC integration setup."""

from __future__ import annotations

from dataclasses import dataclass
from functools import partial

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.typing import ConfigType

from dahua_rpc import DahuaClient

from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, PLATFORMS


@dataclass(frozen=True, slots=True)
class RecorderInfo:
    """Immutable recorder identity used by entities."""

    serial: str
    name: str
    manufacturer: str | None
    model: str | None
    firmware_version: str | None


@dataclass(slots=True)
class DahuaRpcRuntimeData:
    """Runtime resources shared by all entities for one recorder."""

    client: DahuaClient
    recorder: RecorderInfo


type DahuaRpcConfigEntry = ConfigEntry[DahuaRpcRuntimeData]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Set up integration-wide services."""
    from .websocket import async_register_websocket_commands

    async_register_websocket_commands(hass)
    return True


def recorder_info(client: DahuaClient) -> RecorderInfo:
    """Build recorder identity from a validated SDK client."""
    serial = client.serial_number
    if not serial:
        raise ValueError("Recorder did not provide a serial number")
    name = " ".join(value for value in (client.manufacturer, client.model) if value)
    return RecorderInfo(
        serial=serial,
        name=name or "Dahua RPC recorder",
        manufacturer=client.manufacturer,
        model=client.model,
        firmware_version=client.firmware_version,
    )


async def async_setup_entry(
    hass: HomeAssistant, entry: DahuaRpcConfigEntry
) -> bool:
    """Set up a Dahua RPC config entry."""
    client = await hass.async_add_executor_job(
        partial(
            DahuaClient,
            host=entry.data[CONF_HOST],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
        )
    )
    try:
        entry.runtime_data = DahuaRpcRuntimeData(
            client=client, recorder=recorder_info(client)
        )
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    except Exception:
        await hass.async_add_executor_job(client.close)
        raise
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DahuaRpcConfigEntry
) -> bool:
    """Unload a Dahua RPC config entry."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await hass.async_add_executor_job(entry.runtime_data.client.close)
    return True
