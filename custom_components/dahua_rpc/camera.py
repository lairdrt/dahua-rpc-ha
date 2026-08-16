"""Camera platform for Dahua RPC."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import quote

from homeassistant.components.camera import Camera as HaCamera
from homeassistant.components.camera import CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from dahua_rpc import Camera

from . import DahuaRpcRuntimeData, RecorderInfo
from .const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, DOMAIN, RTSP_PORT


@dataclass(frozen=True, slots=True)
class CameraDescription:
    """Initial SDK state needed by one HA camera entity."""

    camera: Camera
    subtype: int


def _discover_cameras(runtime: DahuaRpcRuntimeData) -> list[CameraDescription]:
    descriptions: list[CameraDescription] = []
    for camera in runtime.client.cameras.list():
        if not camera.configured:
            continue
        profiles = runtime.client.cameras.streams(camera.channel)
        kinds = {profile.kind for profile in profiles}
        if "sub" in kinds:
            subtype = 1
        elif "main" in kinds:
            subtype = 0
        else:
            continue
        descriptions.append(CameraDescription(camera=camera, subtype=subtype))
    return descriptions


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry[DahuaRpcRuntimeData],
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up cameras discovered from the recorder."""
    descriptions = await hass.async_add_executor_job(
        _discover_cameras, entry.runtime_data
    )
    async_add_entities(
        DahuaRpcCamera(
            description=description,
            recorder=entry.runtime_data.recorder,
            host=entry.data[CONF_HOST],
            username=entry.data[CONF_USERNAME],
            password=entry.data[CONF_PASSWORD],
        )
        for description in descriptions
    )


class DahuaRpcCamera(HaCamera):
    """A configured recorder camera channel."""

    _attr_has_entity_name = True
    _attr_supported_features = CameraEntityFeature.STREAM

    def __init__(
        self,
        *,
        description: CameraDescription,
        recorder: RecorderInfo,
        host: str,
        username: str,
        password: str,
    ) -> None:
        super().__init__()
        camera = description.camera
        self._channel = camera.channel
        self._subtype = description.subtype
        self._host = host
        self._username = username
        self._password = password
        self._attr_unique_id = f"{recorder.serial}_channel_{camera.channel}"
        self._attr_name = camera.name or f"Channel {camera.channel}"
        self._attr_available = camera.configured and camera.connected

        device_info: DeviceInfo = DeviceInfo(
            identifiers={(DOMAIN, recorder.serial)},
            name=recorder.name,
        )
        if recorder.manufacturer is not None:
            device_info["manufacturer"] = recorder.manufacturer
        if recorder.model is not None:
            device_info["model"] = recorder.model
        if recorder.firmware_version is not None:
            device_info["sw_version"] = recorder.firmware_version
        self._attr_device_info = device_info

    async def stream_source(self) -> str | None:
        """Return the direct RTSP source consumed by HA's stream pipeline."""
        username = quote(self._username, safe="")
        password = quote(self._password, safe="")
        host = self._host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return (
            f"rtsp://{username}:{password}@{host}:{RTSP_PORT}"
            f"/cam/realmonitor?channel={self._channel}&subtype={self._subtype}"
        )

