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

## Phase 2A historical metadata API

Phase 2A adds two authenticated, admin-only Home Assistant WebSocket commands:

- `dahua_rpc/recordings`
- `dahua_rpc/snapshots`

Both require `entity_id`, `start`, and `end`. Times are ISO 8601 values with
explicit timezone offsets, `end` must be later than `start`, and the maximum
query window is 24 hours. Results are ordered oldest to newest.

The backend path is:

```text
HA frontend
  -> authenticated HA WebSocket command
  -> dahua-rpc-ha
  -> Home Assistant executor
  -> shared DahuaClient from ConfigEntry.runtime_data
  -> media.recordings() / media.snapshots()
  -> recorder RPC media index
```

Live video remains `HA Camera Stream -> RTSP`. The standard current-frame
Snapshot action remains `HA Stream -> stream-derived still`. Historical
snapshot metadata uses `WebSocket -> SDK media.snapshots()`, while historical
recording metadata uses `WebSocket -> SDK media.recordings()`.

The new commands return metadata only: no DAV, JPEG, base64, RTSP media, or
other media bytes. `file_path` is an opaque recorder-internal reference, not a
frontend-fetchable path. Each result has a deterministic SHA-256 `media_id`
derived from config-entry and immutable recorder metadata. A later retrieval
phase can resolve it by bounded re-query around the returned timestamp; Phase
2A intentionally has no persistent media-ID registry or playback API.

## Development setup

Create/activate the Python environment used for Home Assistant and tests, then
make the sibling SDK importable without copying it:

```powershell
pip install -e C:\Users\laird\Documents\Projects\dahua-rpc-sdk
pip install -e ".[test]"
```

The integration manifest pins the validated SDK Git commit so Home Assistant
installs the exact supported `dahua_rpc` version.

## Development deployment

With the Samba share installed and enabled on HAOS, deploy the integration from
Windows PowerShell with:

```powershell
.\deploy-ha.ps1 -Host <HA-IP>
```

The script mirrors only `custom_components/dahua_rpc` to the matching folder
under the HAOS `config` share. It excludes `__pycache__` directories and Python
bytecode files. Restart Home Assistant or reload the integration manually after
deployment.

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
