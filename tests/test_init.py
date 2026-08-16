"""Tests for Dahua RPC config-entry setup."""

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.config_entries import ConfigEntry

from custom_components.dahua_rpc import (
    async_setup,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.dahua_rpc.const import DOMAIN


def _entry() -> ConfigEntry:
    return ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="NVR",
        data={"host": "nvr.local", "username": "admin", "password": "secret"},
        source="user",
        unique_id="SERIAL-1",
        options={},
        discovery_keys={},
        subentries_data={},
    )


async def test_domain_setup_registers_websocket_commands_once(hass):
    with patch(
        "custom_components.dahua_rpc.websocket.async_register_websocket_commands"
    ) as register:
        assert await async_setup(hass, {})
    register.assert_called_once_with(hass)


async def test_setup_creates_one_client_and_forwards_camera(hass):
    entry = _entry()
    client = MagicMock(
        serial_number="SERIAL-1",
        manufacturer="Example",
        model="NVR",
        firmware_version="1.2.3",
    )
    with (
        patch("custom_components.dahua_rpc.DahuaClient", return_value=client) as ctor,
        patch.object(
            hass.config_entries, "async_forward_entry_setups", new=AsyncMock()
        ) as forward,
        patch(
            "custom_components.dahua_rpc.websocket.async_register_websocket_commands"
        ) as register,
    ):
        assert await async_setup_entry(hass, entry)
    ctor.assert_called_once()
    assert entry.runtime_data.client is client
    forward.assert_awaited_once_with(entry, ["camera"])
    register.assert_not_called()


async def test_unload_closes_shared_client(hass):
    entry = _entry()
    client = MagicMock()
    entry.runtime_data = MagicMock(client=client)
    with patch.object(
        hass.config_entries,
        "async_unload_platforms",
        new=AsyncMock(return_value=True),
    ) as unload:
        assert await async_unload_entry(hass, entry)
    unload.assert_awaited_once_with(entry, ["camera"])
    client.close.assert_called_once_with()
