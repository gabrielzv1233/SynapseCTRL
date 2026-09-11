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
Authentication:  disabled unless configured
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

## Bearer authentication

Authentication is optional. When no token is configured, the API behaves exactly as before and `/v1/*` is unauthenticated.

Provide a token directly:

```powershell
SynapseCTRL serve --token "YOUR_RANDOM_TOKEN"
```

For scripts or services, the environment variable is usually preferable because it avoids putting the token directly in the process command line:

```powershell
$env:SYNAPSECTRL_HTTP_TOKEN = "YOUR_RANDOM_TOKEN"
SynapseCTRL serve
```

You can also ask SynapseCTRL to generate a strong random token for the current server process:

```powershell
SynapseCTRL serve --generate-token
```

The generated token is printed once when the server starts. Save/copy it before connecting clients; a new token is generated the next time you use `--generate-token`.

When authentication is enabled:

- `GET /` remains public so clients can discover the API version and that Bearer authentication is enabled
- every `/v1/*` endpoint requires the token
- the SSE event stream at `/v1/events` is protected too

Send the token as:

```http
Authorization: Bearer YOUR_RANDOM_TOKEN
```

Example:

```powershell
curl.exe `
  -H "Authorization: Bearer YOUR_RANDOM_TOKEN" `
  "http://127.0.0.1:8765/v1/state"
```

Missing or incorrect credentials return `401`:

```json
{
  "apiVersion": "1",
  "error": {
    "code": "unauthorized",
    "message": "A valid Bearer token is required.",
    "details": {}
  }
}
```

The response also includes:

```http
WWW-Authenticate: Bearer
```

## Security

The default bind address is loopback-only:

```text
127.0.0.1
```

That is still the recommended configuration for normal use.

If `--host` is set to a non-loopback address such as `0.0.0.0`, SynapseCTRL prints a warning.

Without a configured token, anyone who can reach that port may be able to inspect devices/profiles, subscribe to state events, or switch active profiles.

Bearer authentication protects API access, but the built-in Uvicorn configuration is still plain **HTTP**, not HTTPS. A token sent over an untrusted network can therefore be observed in transit. For anything beyond a trusted LAN, put SynapseCTRL behind a TLS-terminating reverse proxy or another trusted encrypted transport.

CORS is not enabled by default. This is intentional: arbitrary web pages should not be granted browser access to a local profile-control API.

Native browser `EventSource` does not provide a standard way to attach a custom `Authorization` header. If Bearer authentication is enabled and a browser client needs `/v1/events`, use a streaming `fetch` implementation or a trusted same-origin/reverse-proxy arrangement rather than placing the token in the query string.

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
| missing/invalid Bearer token | `401` |
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

Returns the SynapseCTRL version, HTTP API version, authentication mode, and basic endpoint information. This endpoint does not require Synapse to be available and remains public when Bearer authentication is enabled.

### Full Synapse status

```http
GET /v1/status
```

Equivalent to the SDK status operation. A returned status can report `ready`, `degraded`, or `unavailable`.

The `versions` object also exposes the SynapseCTRL backend and managed launch-hook versions, for example:

```json
{
  "apiVersion": "1",
  "data": {
    "state": "ready",
    "versions": {
      "synapseCtrl": "0.3.1",
      "hook": "3",
      "hookExpected": "3",
      "hookProtocol": "1",
      "hookProtocolExpected": "1",
      "hookBuild": "v3+1a2b3c4d5e6f",
      "hookExpectedBuild": "v3+1a2b3c4d5e6f",
      "hookInstalledBy": "0.3.1"
    }
  }
}
```

Runtime entries such as `electron`, `chrome`, and `node` can appear in the same object. The exact hook build suffix is derived from the packaged hook SHA-256 fingerprint and changes automatically when the hook implementation changes. An installed hook that is stale or mismatched contributes health issues and can make status `degraded` even while the current Synapse process is reachable.

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

Quick test without authentication:

```powershell
curl.exe -N -H "Accept: text/event-stream" "http://127.0.0.1:8765/v1/events"
```

With Bearer authentication:

```powershell
curl.exe -N `
  -H "Accept: text/event-stream" `
  -H "Authorization: Bearer YOUR_RANDOM_TOKEN" `
  "http://127.0.0.1:8765/v1/events"
```

The stream remains open until the client disconnects or the server stops. Each client receives its own bounded event queue. If a client falls far enough behind to fill that queue, older queued events are discarded in favor of newer state changes; clients should treat the stream as live state notification rather than a durable event log.
