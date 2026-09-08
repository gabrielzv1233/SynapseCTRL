# HTTP / REST API

SynapseCTRL can expose its persistent service core as a small local REST API using **Starlette** and **Uvicorn**.

HTTP support is optional. Stream Deck plugins and other local child-process integrations can continue using the stdio bridge without installing any web dependencies.

## Install HTTP support

With uv tool:

```powershell
uv tool install "SynapseCTRL[http]"
```

With pip:

```powershell
python -m pip install "SynapseCTRL[http]"
```

The `http` extra installs Starlette and Uvicorn. They are not installed by the base `SynapseCTRL` package.

## Start the server

```powershell
SynapseCTRL serve
```

Defaults:

```text
HTTP address:    127.0.0.1
HTTP port:       8765
Inspector port:  9229
```

The root endpoint is therefore:

```text
http://127.0.0.1:8765/
```

The process stays alive until it is stopped. It uses the same persistent `SynapseService` core as bridge mode, including state polling, reconnect behavior, immediate refresh after verified profile switches, and change events.

## Server options

Choose a different HTTP port:

```powershell
SynapseCTRL serve --port 9000
```

Choose a different listen address:

```powershell
SynapseCTRL serve --host 0.0.0.0 --port 8765
```

Use a non-default Synapse inspector port:

```powershell
SynapseCTRL serve --inspector-port 9333
```

Change polling/reconnect timing:

```powershell
SynapseCTRL serve --poll-interval 1 --unavailable-interval 3
```

Disable per-request Uvicorn access logs:

```powershell
SynapseCTRL serve --no-access-log
```

## Security

The default bind address is loopback-only:

```text
127.0.0.1
```

That is the recommended configuration for normal use.

If `--host` is set to a non-loopback address such as `0.0.0.0`, SynapseCTRL prints a warning. The current HTTP API does **not** provide authentication. Anyone who can reach that port may be able to inspect devices/profiles, subscribe to state events, or switch active profiles.

Only expose the server to a trusted network and protect it with the host firewall or another trusted access-control layer.

CORS is not enabled by default. This is intentional: arbitrary web pages should not be granted browser access to a local unauthenticated profile-control API.

## Response envelope

Successful JSON responses use the same versioned shape as the CLI JSON interface:

```json
{
  "apiVersion": "1",
  "data": {}
}
```

Errors use:

```json
{
  "apiVersion": "1",
  "error": {
    "code": "device_not_found",
    "message": "No device matches ...",
    "details": {}
  }
}
```

Common HTTP mappings include:

| SynapseCTRL error | HTTP status |
| --- | ---: |
| `invalid_argument` / `invalid_json` | `400` |
| `device_not_found` / `profile_not_found` | `404` |
| `ambiguous_device` / `ambiguous_profile` | `409` |
| `device_unavailable` / `inspector_unreachable` / `transport_lost` | `503` |
| `verification_timeout` | `504` |

A profile switch that returns a normal `SwitchResult` remains a successful HTTP response even when the result itself reports `timeout` or `failed`; inspect the returned `status`, `sent`, `verified`, and `error` fields just as you would with the Python SDK.

## Endpoints

### Service information

```http
GET /
```

Returns the SynapseCTRL version, HTTP API version, and basic endpoint information. This endpoint does not require Synapse to be available.

### Full Synapse status

```http
GET /v1/status
```

Equivalent to the SDK status operation. A returned status can report `ready`, `degraded`, or `unavailable`.

### Cached persistent state

```http
GET /v1/state
```

Returns the most recent state held by `SynapseService` without forcing a new Synapse read.

### Live events

```http
GET /v1/events
Accept: text/event-stream
```

Opens a **Server-Sent Events (SSE)** stream backed by the same `SynapseService` event source used by stdio bridge mode.

The first message is always an immediate snapshot:

```text
event: service.snapshot
data: {"apiVersion":"1","event":"service.snapshot","data":{"state":"ready","synapseAvailable":true,"devices":[],"error":null,"updatedAtMs":123}}
```

After that, the stream forwards meaningful service events such as:

- `synapse.available`
- `synapse.unavailable`
- `profile.changed`
- `devices.changed`
- `device.changed`

Example profile-change frame:

```text
event: profile.changed
data: {"apiVersion":"1","event":"profile.changed","data":{"deviceId":"DEVICE_ID","previousProfileId":"OLD_GUID","profileId":"NEW_GUID"}}
```

SynapseCTRL sends an SSE comment roughly every 15 seconds while no events are occurring:

```text
: keep-alive
```

These heartbeats help proxies and HTTP clients keep the connection open. They are not application events and should be ignored by SSE parsers.

Quick test with curl:

```powershell
curl.exe -N -H "Accept: text/event-stream" "http://127.0.0.1:8765/v1/events"
```

The stream remains open until the client disconnects or the server stops. Each client receives its own bounded event queue. If a client falls far enough behind to fill that queue, older queued events are discarded in favor of newer state changes; clients should treat the stream as live state notification rather than a durable event log.

### Force a refresh

```http
POST /v1/refresh
```

Forces an immediate device/state refresh and returns the discovered devices.

### List devices

```http
GET /v1/devices
```

Returns discovered devices including profile lists and `activeProfileId`.

### List one device's profiles

```http
GET /v1/devices/{device}/profiles
```

`{device}` may be a stable device ID or an unambiguous name selector. Stable IDs are recommended for integrations.

URL-encode the path segment when necessary.

Example with curl:

```powershell
curl.exe "http://127.0.0.1:8765/v1/devices/DEVICE_ID/profiles"
```

### Read the active profile

```http
GET /v1/devices/{device}/active-profile
```

Returns the active profile object or `null` if no active software profile can be identified.

### Activate a profile

```http
POST /v1/devices/{device}/profiles/{profile}/activate
Content-Type: application/json
```

`{profile}` may be a stable profile GUID or an unambiguous profile name. Stable GUIDs are recommended.

The JSON body is optional. Defaults are:

```json
{
  "timeout": 5,
  "verify": true
}
```

Example:

```powershell
curl.exe -X POST `
  -H "Content-Type: application/json" `
  -d '{"timeout":5,"verify":true}' `
  "http://127.0.0.1:8765/v1/devices/DEVICE_ID/profiles/PROFILE_GUID/activate"
```

Example response:

```json
{
  "apiVersion": "1",
  "data": {
    "status": "verified",
    "deviceId": "DEVICE_ID",
    "profileId": "PROFILE_GUID",
    "previousProfileId": "OLD_PROFILE_GUID",
    "sent": true,
    "verified": true,
    "elapsedMs": 142,
    "error": null
  }
}
```

## Why HTTP is separate from bridge mode

Both transports use the same service core:

```text
                 +--> NDJSON stdio bridge
SynapseService --+
                 +--> Starlette REST + SSE API
```

Use the stdio bridge when one local application owns a SynapseCTRL child process, such as SynapseDeck.

Use HTTP when multiple tools, scripts, languages, or machines on a trusted network need a conventional REST interface or a shared event stream.

The HTTP server is not required for SynapseDeck and does not need to run separately for bridge users.

## Events vs polling

Clients that only need occasional state can use ordinary REST requests such as `/v1/state` or `/v1/devices`.

Clients that need immediate profile/device/Synapse state changes should prefer `/v1/events` and use the initial `service.snapshot` to establish current state before processing subsequent events.

The SSE endpoint intentionally does not provide durable replay. If a client disconnects, reconnect and use the new `service.snapshot` as the source of truth before handling later change events.
