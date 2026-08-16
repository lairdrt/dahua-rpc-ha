"""Tests for Dahua RPC camera entities."""

from pathlib import Path
from unittest.mock import MagicMock

from dahua_rpc import Camera, StreamProfile
from homeassistant.components.camera import CameraEntityFeature

from custom_components.dahua_rpc import DahuaRpcRuntimeData, RecorderInfo
from custom_components.dahua_rpc.camera import (
    CameraDescription,
    DahuaRpcCamera,
    _discover_cameras,
)
from custom_components.dahua_rpc.const import DOMAIN


def _camera(channel: int, *, configured: bool = True) -> Camera:
    return Camera(
        channel=channel,
        name=f"Front {channel}",
        configured=configured,
        connected=True,
        address=None,
        device_type=None,
        serial_number=None,
        mac_address=None,
        protocol=None,
    )


def _profile(kind: str) -> StreamProfile:
    return StreamProfile(
        kind=kind,
        codec="H.264",
        width=1920,
        height=1080,
        fps=15,
        bitrate=2048,
        bitrate_control="CBR",
        audio_enabled=False,
        audio_codec=None,
    )


def _runtime(cameras, streams) -> DahuaRpcRuntimeData:
    client = MagicMock()
    client.cameras.list.return_value = tuple(cameras)
    client.cameras.streams.side_effect = lambda channel: streams[channel]
    return DahuaRpcRuntimeData(
        client=client,
        recorder=RecorderInfo("SERIAL-1", "Example NVR", "Example", "NVR", "1"),
    )


def test_discovery_filters_unconfigured_and_prefers_extra1():
    runtime = _runtime(
        [_camera(1), _camera(2, configured=False)],
        {1: (_profile("main"), _profile("sub"))},
    )
    descriptions = _discover_cameras(runtime)
    assert [(item.camera.channel, item.subtype) for item in descriptions] == [(1, 1)]
    runtime.client.cameras.streams.assert_called_once_with(1)


def test_discovery_falls_back_to_main_and_skips_no_streams():
    runtime = _runtime(
        [_camera(1), _camera(2)],
        {1: (_profile("main"),), 2: ()},
    )
    descriptions = _discover_cameras(runtime)
    assert [(item.camera.channel, item.subtype) for item in descriptions] == [(1, 0)]


def _entity(*, subtype: int = 1) -> DahuaRpcCamera:
    return DahuaRpcCamera(
        description=CameraDescription(_camera(1), subtype),
        recorder=RecorderInfo("SERIAL-1", "Example NVR", None, "NVR", "1.2.3"),
        host="2001:db8::1",
        username="user@example.com",
        password="p@ss:/ word",
    )


async def test_entity_identity_device_and_stream_feature():
    entity = _entity()
    assert entity.unique_id == "SERIAL-1_channel_1"
    assert entity.name == "Front 1"
    assert entity.available
    assert entity.supported_features == CameraEntityFeature.STREAM
    assert entity.device_info["identifiers"] == {(DOMAIN, "SERIAL-1")}
    assert entity.device_info["model"] == "NVR"
    assert "manufacturer" not in entity.device_info
    assert not entity.extra_state_attributes


async def test_extra1_rtsp_url_encodes_credentials():
    source = await _entity(subtype=1).stream_source()
    assert source == (
        "rtsp://user%40example.com:p%40ss%3A%2F%20word@[2001:db8::1]:554/"
        "cam/realmonitor?channel=1&subtype=1"
    )


async def test_main_rtsp_url_uses_subtype_zero():
    source = await _entity(subtype=0).stream_source()
    assert source.endswith("/cam/realmonitor?channel=1&subtype=0")


def test_runtime_contains_no_forbidden_transport_references():
    runtime_dir = Path(__file__).parents[1] / "custom_components" / DOMAIN
    forbidden = (
        "dahua_cgi",
        "dahua-cgi-sdk",
        "snapshot.cgi",
        "configManager.cgi",
        "realmonitor.cgi",
        "mjpg/video.cgi",
        "magicBox.cgi",
        "RPC_Loadfile",
        "_Connection",
        "LiveStream.receive",
    )
    runtime_text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in runtime_dir.rglob("*")
        if path.is_file()
    )
    assert not any(value in runtime_text for value in forbidden)

