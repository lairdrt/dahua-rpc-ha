"""Tests for the Dahua RPC config flow."""

from unittest.mock import MagicMock, patch

from dahua_rpc.exceptions import AuthenticationError, RecorderConnectionError
from homeassistant import config_entries, data_entry_flow

from custom_components.dahua_rpc.const import DOMAIN

USER_INPUT = {"host": "nvr.local", "username": "admin", "password": "secret"}


def _client(*, serial: str = "SERIAL-1") -> MagicMock:
    client = MagicMock()
    client.serial_number = serial
    client.manufacturer = "Example"
    client.model = "NVR"
    client.firmware_version = "1.2.3"
    return client


async def test_user_form(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is data_entry_flow.FlowResultType.FORM
    assert result["step_id"] == "user"


async def test_success_uses_serial_and_closes(hass):
    client = _client()
    with patch(
        "custom_components.dahua_rpc.config_flow.DahuaClient", return_value=client
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )

    assert result["type"] is data_entry_flow.FlowResultType.CREATE_ENTRY
    assert result["result"].unique_id == "SERIAL-1"
    assert result["data"] == USER_INPUT
    client.close.assert_called_once_with()


async def test_duplicate_serial_aborts(hass):
    entry = config_entries.ConfigEntry(
        version=1,
        minor_version=1,
        domain=DOMAIN,
        title="Existing",
        data=USER_INPUT,
        source=config_entries.SOURCE_USER,
        unique_id="SERIAL-1",
        options={},
        discovery_keys={},
        subentries_data={},
    )
    entry.add_to_hass(hass)
    client = _client()
    with patch(
        "custom_components.dahua_rpc.config_flow.DahuaClient", return_value=client
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["type"] is data_entry_flow.FlowResultType.ABORT
    assert result["reason"] == "already_configured"
    client.close.assert_called_once_with()


async def test_authentication_error(hass):
    with patch(
        "custom_components.dahua_rpc.config_flow.DahuaClient",
        side_effect=AuthenticationError,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["errors"] == {"base": "invalid_auth"}


async def test_connection_error(hass):
    with patch(
        "custom_components.dahua_rpc.config_flow.DahuaClient",
        side_effect=RecorderConnectionError,
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_unknown_error_and_existing_client_closes(hass):
    client = _client(serial="")
    with patch(
        "custom_components.dahua_rpc.config_flow.DahuaClient", return_value=client
    ):
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": config_entries.SOURCE_USER},
            data=USER_INPUT,
        )
    assert result["errors"] == {"base": "unknown"}
    client.close.assert_called_once_with()

