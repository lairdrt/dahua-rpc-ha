# Dahua RPC for Home Assistant

`Dahua RPC` is a Home Assistant custom integration for a single Dahua- or
Lorex-compatible recorder and its configured camera channels. It depends on
the separate [`dahua-rpc-sdk`](https://github.com/lairdrt/dahua-rpc-sdk)
Python distribution (`dahua_rpc` import); SDK code is not vendored here.

## Phase 1

Phase 1 provides UI configuration with recorder host, username, and password;
recorder identity keyed by its serial number; camera discovery; and one HA
camera entity per configured, stream-capable public channel. Availability is
the initial SDK `connected` state. Dynamic refresh is reserved for a later
polling/event phase.

Live viewing uses Home Assistant's native Camera/Stream pipeline. Each entity
returns a direct, authenticated RTSP URL. It prefers the SDK-advertised Extra1
profile (RTSP subtype 1), normally H.264, and falls back to Main (subtype 0)
only when Extra1 is absent. Credentials are percent-encoded and the URL is not
published as entity state or attributes.

The runtime uses RPC2 for identity and camera metadata and RTSP for live video.
It introduces no CGI and does not relay, decode, or transcode video in Python.

## Development setup

Create/activate the Python environment used for Home Assistant and tests, then
make the sibling SDK importable without copying it:

```powershell
pip install -e C:\Users\laird\Documents\Projects\dahua-rpc-sdk
pip install -e ".[test]"
```

The SDK currently is not listed in `manifest.json` requirements because it is
not published as an installable package for Home Assistant. The actual HA
runtime must independently install or otherwise provide `dahua_rpc`.

## Manual installation

1. Copy `custom_components/dahua_rpc` into
   `/config/custom_components/dahua_rpc`.
2. Make `dahua-rpc-sdk` importable as `dahua_rpc` in the exact Python runtime
   that starts Home Assistant. A sibling Windows checkout is not visible to HA
   OS or a container; build/install the SDK into that environment first.
3. Restart Home Assistant.
4. Open **Settings -> Devices & services -> Add Integration**.
5. Select **Dahua RPC** and enter host, username, and password.
6. Confirm the recorder device and its configured camera entities appear.
7. Open channel 1 and confirm live video. Extra1/H.264 is selected by default
   when the SDK reports it.
8. Confirm recorder metadata uses RPC2 and live media uses RTSP; no CGI is
   involved.

## Future work

Recording/event browsing, stored snapshots, recorded RTSP playback, timeline
UI, and a custom dashboard card are explicitly outside Phase 1.

