"""Authenticated WebSocket API for historical media metadata."""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Callable, Iterable
from datetime import datetime, timedelta
from functools import partial
from typing import Any

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_registry as er

from dahua_rpc import DahuaClient, Recording, Snapshot
from dahua_rpc.exceptions import (
    AuthenticationError,
    DahuaError,
    InvalidResponseError,
    TransportError,
)

from . import DahuaRpcConfigEntry, DahuaRpcRuntimeData
from .const import DOMAIN

COMMAND_RECORDINGS = f"{DOMAIN}/recordings"
COMMAND_SNAPSHOTS = f"{DOMAIN}/snapshots"
MAX_QUERY_WINDOW = timedelta(hours=24)

_LOGGER = logging.getLogger(__name__)
_COMMAND_SCHEMA = {
    vol.Required("entity_id"): cv.entity_id,
    vol.Required("start"): str,
    vol.Required("end"): str,
}


@callback
def async_register_websocket_commands(hass: HomeAssistant) -> None:
    """Register integration-wide WebSocket commands once during domain setup."""
    websocket_api.async_register_command(hass, websocket_recordings)
    websocket_api.async_register_command(hass, websocket_snapshots)


@websocket_api.websocket_command(
    {vol.Required("type"): COMMAND_RECORDINGS, **_COMMAND_SCHEMA}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_recordings(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return recording metadata for one Dahua camera and time window."""
    await _handle_media_query(
        hass,
        connection,
        msg,
        response_key="recordings",
        search=_recordings,
        serialize=_serialize_recording,
    )


@websocket_api.websocket_command(
    {vol.Required("type"): COMMAND_SNAPSHOTS, **_COMMAND_SCHEMA}
)
@websocket_api.require_admin
@websocket_api.async_response
async def websocket_snapshots(
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
) -> None:
    """Return stored snapshot metadata for one Dahua camera and time window."""
    await _handle_media_query(
        hass,
        connection,
        msg,
        response_key="snapshots",
        search=_snapshots,
        serialize=_serialize_snapshot,
    )


async def _handle_media_query[MediaT: (Recording, Snapshot)](
    hass: HomeAssistant,
    connection: websocket_api.ActiveConnection,
    msg: dict[str, Any],
    *,
    response_key: str,
    search: Callable[
        [DahuaClient, int, datetime, datetime], Iterable[MediaT]
    ],
    serialize: Callable[[MediaT, str], dict[str, Any]],
) -> None:
    try:
        start, end = _parse_time_window(msg["start"], msg["end"])
        entry, channel = _resolve_camera(hass, msg["entity_id"])
    except _WebSocketQueryError as err:
        connection.send_error(msg["id"], err.code, err.message)
        return

    try:
        items = await hass.async_add_executor_job(
            partial(
                _search_and_serialize,
                entry.runtime_data.client,
                entry.entry_id,
                channel,
                start,
                end,
                search,
                serialize,
            )
        )
    except AuthenticationError:
        connection.send_error(
            msg["id"], "authentication_failed", "Recorder authentication failed."
        )
        return
    except TransportError:
        connection.send_error(
            msg["id"], "recorder_unavailable", "Recorder is unavailable."
        )
        return
    except InvalidResponseError:
        connection.send_error(
            msg["id"], "media_search_failed", "Recorder media search failed."
        )
        return
    except DahuaError:
        connection.send_error(
            msg["id"], "media_search_failed", "Recorder media search failed."
        )
        return
    except Exception:
        _LOGGER.exception("Unexpected Dahua historical media search failure")
        connection.send_error(
            msg["id"], "media_search_failed", "Recorder media search failed."
        )
        return

    connection.send_result(
        msg["id"],
        {
            "entity_id": msg["entity_id"],
            "start": start.isoformat(),
            "end": end.isoformat(),
            "count": len(items),
            response_key: items,
        },
    )


def _parse_time_window(start_value: str, end_value: str) -> tuple[datetime, datetime]:
    try:
        start = datetime.fromisoformat(start_value)
        end = datetime.fromisoformat(end_value)
    except ValueError as exc:
        raise _WebSocketQueryError(
            "invalid_time", "start and end must be valid ISO 8601 timestamps."
        ) from exc
    if start.tzinfo is None or start.utcoffset() is None:
        raise _WebSocketQueryError(
            "timezone_required", "start must include a timezone offset."
        )
    if end.tzinfo is None or end.utcoffset() is None:
        raise _WebSocketQueryError(
            "timezone_required", "end must include a timezone offset."
        )
    if end <= start:
        raise _WebSocketQueryError(
            "invalid_time_range", "end must be later than start."
        )
    if end - start > MAX_QUERY_WINDOW:
        raise _WebSocketQueryError(
            "query_window_too_large", "The maximum query window is 24 hours."
        )
    return start, end


def _resolve_camera(
    hass: HomeAssistant, entity_id: str
) -> tuple[DahuaRpcConfigEntry, int]:
    entity = er.async_get(hass).async_get(entity_id)
    if entity is None:
        raise _WebSocketQueryError("entity_not_found", "Camera entity not found.")
    if not entity_id.startswith("camera.") or entity.platform != DOMAIN:
        raise _WebSocketQueryError(
            "invalid_entity", "Entity is not a Dahua RPC camera."
        )
    if entity.config_entry_id is None:
        raise _WebSocketQueryError(
            "invalid_entity", "Dahua RPC camera has no config entry."
        )
    entry = hass.config_entries.async_get_entry(entity.config_entry_id)
    if entry is None or entry.domain != DOMAIN:
        raise _WebSocketQueryError(
            "invalid_entity", "Entity is not a Dahua RPC camera."
        )
    try:
        runtime = entry.runtime_data
    except AttributeError as exc:
        raise _WebSocketQueryError(
            "entity_unavailable", "Dahua RPC recorder is not loaded."
        ) from exc
    if not isinstance(runtime, DahuaRpcRuntimeData):
        raise _WebSocketQueryError(
            "entity_unavailable", "Dahua RPC recorder is not loaded."
        )
    prefix = f"{runtime.recorder.serial}_channel_"
    if not entity.unique_id.startswith(prefix):
        raise _WebSocketQueryError(
            "invalid_entity", "Entity has an invalid Dahua RPC identity."
        )
    try:
        channel = int(entity.unique_id.removeprefix(prefix))
    except ValueError as exc:
        raise _WebSocketQueryError(
            "invalid_entity", "Entity has an invalid Dahua RPC channel."
        ) from exc
    if channel < 1:
        raise _WebSocketQueryError(
            "invalid_entity", "Entity has an invalid Dahua RPC channel."
        )
    return entry, channel


def _search_and_serialize[MediaT: (Recording, Snapshot)](
    client: DahuaClient,
    config_entry_id: str,
    channel: int,
    start: datetime,
    end: datetime,
    search: Callable[
        [DahuaClient, int, datetime, datetime], Iterable[MediaT]
    ],
    serialize: Callable[[MediaT, str], dict[str, Any]],
) -> list[dict[str, Any]]:
    items = list(search(client, channel, start, end))
    items.sort(key=_media_sort_key)
    return [serialize(item, config_entry_id) for item in items]


def _recordings(
    client: DahuaClient, channel: int, start: datetime, end: datetime
) -> Iterable[Recording]:
    return client.media.recordings(channel=channel, start=start, end=end)


def _snapshots(
    client: DahuaClient, channel: int, start: datetime, end: datetime
) -> Iterable[Snapshot]:
    return client.media.snapshots(channel=channel, start=start, end=end)


def _media_sort_key(media: Recording | Snapshot) -> tuple[datetime, datetime, str]:
    if isinstance(media, Recording):
        return media.start_time, media.end_time, media.file_path
    return media.start, media.end, media.file_path


def _serialize_recording(
    recording: Recording, config_entry_id: str
) -> dict[str, Any]:
    return {
        "media_id": _media_id(config_entry_id, "recording", recording),
        "channel": recording.channel,
        "start": _aware_isoformat(recording.start_time),
        "end": _aware_isoformat(recording.end_time),
        "file_path": recording.file_path,
        "length": recording.length,
        "disk": recording.disk,
        "cluster": recording.cluster,
        "partition": recording.partition,
        "type": recording.type,
        "video_stream": recording.video_stream,
        "events": list(recording.events),
        "flags": list(recording.flags),
        "cut_length": recording.cut_length,
    }


def _serialize_snapshot(snapshot: Snapshot, config_entry_id: str) -> dict[str, Any]:
    return {
        "media_id": _media_id(config_entry_id, "snapshot", snapshot),
        "channel": snapshot.channel,
        "start": _aware_isoformat(snapshot.start),
        "end": _aware_isoformat(snapshot.end),
        "file_path": snapshot.file_path,
        "length": snapshot.length,
        "disk": snapshot.disk,
        "cluster": snapshot.cluster,
        "partition": snapshot.partition,
        "video_stream": snapshot.video_stream,
    }


def _media_id(
    config_entry_id: str, media_type: str, media: Recording | Snapshot
) -> str:
    identity = json.dumps(
        [
            config_entry_id,
            media_type,
            media.channel,
            media.file_path,
            media.disk,
            media.cluster,
            media.partition,
        ],
        ensure_ascii=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def _aware_isoformat(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("SDK returned a timezone-naive media timestamp")
    return value.isoformat()


class _WebSocketQueryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
