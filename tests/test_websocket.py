from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, call, patch
from zoneinfo import ZoneInfo

import pytest
import voluptuous as vol
from dahua_rpc import Recording, Snapshot
from dahua_rpc.exceptions import (
    AuthenticationError,
    InvalidResponseError,
    RecorderConnectionError,
)
from homeassistant.exceptions import Unauthorized

from custom_components.dahua_rpc import DahuaRpcRuntimeData, RecorderInfo
from custom_components.dahua_rpc.const import DOMAIN
from custom_components.dahua_rpc.websocket import (
    COMMAND_RECORDINGS,
    COMMAND_SNAPSHOTS,
    MAX_QUERY_WINDOW,
    _handle_media_query,
    _media_id,
    _parse_time_window,
    _recordings,
    _resolve_camera,
    _search_and_serialize,
    _serialize_recording,
    _serialize_snapshot,
    _snapshots,
    async_register_websocket_commands,
    websocket_recordings,
    websocket_snapshots,
)

RECORDER_TIMEZONE = ZoneInfo("America/Los_Angeles")


def _recording(*, cluster: int = 108756, minute: int = 27) -> Recording:
    return Recording(
        channel=1,
        cluster=cluster,
        disk=1,
        partition=1,
        start_time=datetime(2026, 8, 14, 5, minute, 10, tzinfo=RECORDER_TIMEZONE),
        end_time=datetime(2026, 8, 14, 5, minute, 25, tzinfo=RECORDER_TIMEZONE),
        file_path=f"/mnt/dvr/{cluster}.dav",
        type="dav",
        video_stream="Main",
        events=("VideoMotion",),
        flags=("Event",),
        length=41943040,
        cut_length=0,
    )


def _snapshot(*, cluster: int = 108687, second: int = 6) -> Snapshot:
    timestamp = datetime(
        2026, 8, 14, 5, 23, second, tzinfo=RECORDER_TIMEZONE
    )
    return Snapshot(
        channel=1,
        start=timestamp,
        end=timestamp,
        file_path=f"/mnt/dvr/{cluster}.jpg",
        length=28672,
        disk=1,
        cluster=cluster,
        partition=1,
        video_stream="Main",
    )


def _runtime(client=None) -> DahuaRpcRuntimeData:
    return DahuaRpcRuntimeData(
        client=client or MagicMock(),
        recorder=RecorderInfo("SERIAL-1", "NVR", "Dahua", "NVR", "1"),
    )


def test_registers_both_commands_at_domain_scope(hass):
    with patch(
        "custom_components.dahua_rpc.websocket.websocket_api.async_register_command"
    ) as register:
        async_register_websocket_commands(hass)
    assert register.call_args_list == [
        call(hass, websocket_recordings),
        call(hass, websocket_snapshots),
    ]
    assert websocket_recordings._ws_command == COMMAND_RECORDINGS
    assert websocket_snapshots._ws_command == COMMAND_SNAPSHOTS


def test_command_schema_rejects_missing_entity():
    with pytest.raises(vol.Invalid):
        websocket_recordings._ws_schema(
            {
                "id": 1,
                "type": COMMAND_RECORDINGS,
                "start": "2026-08-14T05:20:00-07:00",
                "end": "2026-08-14T05:40:00-07:00",
            }
        )


def test_commands_require_admin(hass):
    connection = MagicMock()
    connection.user.is_admin = False
    with pytest.raises(Unauthorized):
        websocket_recordings(
            hass,
            connection,
            {
                "id": 1,
                "type": COMMAND_RECORDINGS,
                "entity_id": "camera.front_door",
                "start": "2026-08-14T05:20:00-07:00",
                "end": "2026-08-14T05:40:00-07:00",
            },
        )


def test_maximum_query_window_is_24_hours():
    assert MAX_QUERY_WINDOW == timedelta(hours=24)
    start, end = _parse_time_window(
        "2026-08-14T05:20:00-07:00", "2026-08-15T05:20:00-07:00"
    )
    assert end - start == MAX_QUERY_WINDOW


@pytest.mark.parametrize(
    ("start", "end", "code"),
    [
        ("bad", "2026-08-14T05:40:00-07:00", "invalid_time"),
        ("2026-08-14T05:20:00", "2026-08-14T05:40:00-07:00", "timezone_required"),
        ("2026-08-14T05:20:00-07:00", "2026-08-14T05:40:00", "timezone_required"),
        (
            "2026-08-14T05:20:00-07:00",
            "2026-08-14T05:20:00-07:00",
            "invalid_time_range",
        ),
        (
            "2026-08-14T05:20:00-07:00",
            "2026-08-13T05:20:00-07:00",
            "invalid_time_range",
        ),
        (
            "2026-08-14T05:20:00-07:00",
            "2026-08-15T05:20:01-07:00",
            "query_window_too_large",
        ),
    ],
)
def test_invalid_time_windows_are_rejected(start, end, code):
    with pytest.raises(Exception) as raised:
        _parse_time_window(start, end)
    assert raised.value.code == code


def test_resolves_dahua_entity_to_config_entry_and_public_channel(hass):
    entity = MagicMock(
        platform=DOMAIN,
        config_entry_id="entry-1",
        unique_id="SERIAL-1_channel_11",
    )
    registry = MagicMock()
    registry.async_get.return_value = entity
    entry = MagicMock(
        entry_id="entry-1", domain=DOMAIN, runtime_data=_runtime()
    )
    hass.config_entries.async_get_entry.return_value = entry
    with patch(
        "custom_components.dahua_rpc.websocket.er.async_get",
        return_value=registry,
    ):
        resolved_entry, channel = _resolve_camera(hass, "camera.front_door")
    assert resolved_entry is entry
    assert channel == 11


@pytest.mark.parametrize(
    ("entity", "code"),
    [
        (None, "entity_not_found"),
        (
            MagicMock(
                platform="other",
                config_entry_id="entry-1",
                unique_id="other",
            ),
            "invalid_entity",
        ),
    ],
)
def test_missing_or_non_dahua_entity_is_rejected(hass, entity, code):
    registry = MagicMock()
    registry.async_get.return_value = entity
    with patch(
        "custom_components.dahua_rpc.websocket.er.async_get",
        return_value=registry,
    ):
        with pytest.raises(Exception) as raised:
            _resolve_camera(hass, "camera.example")
    assert raised.value.code == code


async def test_recordings_use_shared_client_public_channel_and_executor(hass):
    client = MagicMock()
    entry = MagicMock(
        entry_id="entry-1", domain=DOMAIN, runtime_data=_runtime(client)
    )
    connection = MagicMock()
    hass.async_add_executor_job = AsyncMock(
        side_effect=lambda job: job()
    )
    search = MagicMock(return_value=[_recording()])
    msg = {
        "id": 1,
        "entity_id": "camera.front_door",
        "start": "2026-08-14T05:20:00-07:00",
        "end": "2026-08-14T05:40:00-07:00",
    }

    with patch(
        "custom_components.dahua_rpc.websocket._resolve_camera",
        return_value=(entry, 1),
    ):
        await _handle_media_query(
            hass,
            connection,
            msg,
            response_key="recordings",
            search=search,
            serialize=_serialize_recording,
        )

    hass.async_add_executor_job.assert_awaited_once()
    search.assert_called_once()
    assert search.call_args.args[0] is client
    assert search.call_args.args[1] == 1
    assert search.call_args.args[2].tzinfo is not None
    result = connection.send_result.call_args.args[1]
    assert result["count"] == 1
    assert result["recordings"][0]["cluster"] == 108756


def test_public_media_methods_receive_aware_bounds_and_one_based_channel():
    client = MagicMock()
    start = datetime(2026, 8, 14, 5, 20, tzinfo=RECORDER_TIMEZONE)
    end = datetime(2026, 8, 14, 5, 40, tzinfo=RECORDER_TIMEZONE)

    _recordings(client, 11, start, end)
    _snapshots(client, 11, start, end)

    client.media.recordings.assert_called_once_with(
        channel=11, start=start, end=end
    )
    client.media.snapshots.assert_called_once_with(
        channel=11, start=start, end=end
    )


def test_search_serializes_oldest_first_and_media_ids_are_deterministic():
    newer = _recording(cluster=2, minute=28)
    older = _recording(cluster=1, minute=27)
    search = MagicMock(return_value=[newer, older])
    first = _search_and_serialize(
        MagicMock(),
        "entry-1",
        1,
        datetime.now(UTC),
        datetime.now(UTC),
        search,
        _serialize_recording,
    )
    second = _search_and_serialize(
        MagicMock(),
        "entry-1",
        1,
        datetime.now(UTC),
        datetime.now(UTC),
        search,
        _serialize_recording,
    )
    assert [item["cluster"] for item in first] == [1, 2]
    assert [item["media_id"] for item in first] == [
        item["media_id"] for item in second
    ]
    assert "secret" not in _media_id("secret-entry", "recording", older)


def test_recording_serialization_preserves_public_model_fields_only():
    result = _serialize_recording(_recording(), "entry-1")
    assert result == {
        "media_id": _media_id("entry-1", "recording", _recording()),
        "channel": 1,
        "start": "2026-08-14T05:27:10-07:00",
        "end": "2026-08-14T05:27:25-07:00",
        "file_path": "/mnt/dvr/108756.dav",
        "length": 41943040,
        "disk": 1,
        "cluster": 108756,
        "partition": 1,
        "type": "dav",
        "video_stream": "Main",
        "events": ["VideoMotion"],
        "flags": ["Event"],
        "cut_length": 0,
    }


def test_snapshot_serialization_has_no_resolution_or_media_bytes():
    result = _serialize_snapshot(_snapshot(), "entry-1")
    assert result == {
        "media_id": _media_id("entry-1", "snapshot", _snapshot()),
        "channel": 1,
        "start": "2026-08-14T05:23:06-07:00",
        "end": "2026-08-14T05:23:06-07:00",
        "file_path": "/mnt/dvr/108687.jpg",
        "length": 28672,
        "disk": 1,
        "cluster": 108687,
        "partition": 1,
        "video_stream": "Main",
    }
    assert not {"resolution", "width", "height", "bytes", "base64"} & result.keys()


@pytest.mark.parametrize(
    ("error", "code"),
    [
        (AuthenticationError("secret detail"), "authentication_failed"),
        (RecorderConnectionError("host detail"), "recorder_unavailable"),
        (InvalidResponseError("raw response"), "media_search_failed"),
    ],
)
async def test_sdk_errors_map_to_safe_websocket_errors(hass, error, code):
    entry = MagicMock(
        entry_id="entry-1", domain=DOMAIN, runtime_data=_runtime()
    )
    connection = MagicMock()
    hass.async_add_executor_job = AsyncMock(side_effect=error)
    with patch(
        "custom_components.dahua_rpc.websocket._resolve_camera",
        return_value=(entry, 1),
    ):
        await _handle_media_query(
            hass,
            connection,
            {
                "id": 1,
                "entity_id": "camera.front_door",
                "start": "2026-08-14T05:20:00-07:00",
                "end": "2026-08-14T05:40:00-07:00",
            },
            response_key="snapshots",
            search=MagicMock(),
            serialize=_serialize_snapshot,
        )
    assert connection.send_error.call_args.args[1] == code
    assert "secret detail" not in connection.send_error.call_args.args[2]
    assert "host detail" not in connection.send_error.call_args.args[2]
    assert "raw response" not in connection.send_error.call_args.args[2]


def test_phase_2a_runtime_contains_no_forbidden_media_paths():
    runtime_dir = Path(__file__).parents[1] / "custom_components" / DOMAIN
    forbidden = (
        "snapshot.cgi",
        "configManager.cgi",
        "realmonitor.cgi",
        "mjpg/video.cgi",
        "magicBox.cgi",
        "RPC_Loadfile",
        "recording_bytes(",
        "snapshot_bytes(",
        "playback(",
        "LiveStream.receive(",
    )
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in runtime_dir.rglob("*")
        if path.is_file()
    )
    assert not any(value in runtime_text for value in forbidden)
