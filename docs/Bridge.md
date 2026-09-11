# Persistent Bridge

SynapseCTRL includes a long-lived bridge mode for integrations that need frequent state updates without repeatedly starting Python and reconnecting to Synapse.

The bridge is intended for applications such as Stream Deck plugins, desktop tools, and other local processes that own a SynapseCTRL child process for their lifetime.

## Start the bridge

```powershell
SynapseCTRL bridge
```

The current/default transport is newline-delimited JSON over standard input/output. You may select it explicitly:

```powershell
SynapseCTRL bridge --stdio
```

For child-process ownership, pass the parent PID:

```powershell
SynapseCTRL bridge --stdio --parent-pid 12345
```

The bridge exits when stdin reaches EOF, when it receives a `shutdown` request, or when the supplied parent PID no longer exists.

## Why use bridge mode?

Normal CLI commands are intentionally short-lived:

```text
start Python -> connect -> perform one operation -> exit
```

Bridge mode keeps one `SynapseClient` and one background state watcher alive:

```text
host application
    |
    | NDJSON stdin/stdout
    v
SynapseCTRL bridge
    |
    | persistent SynapseService / SynapseClient
    v
Razer Synapse 4
```

This avoids repeatedly spawning Python for polling-heavy integrations.

## Stream rules

When bridge mode is running:

- **stdout is reserved for protocol JSON only**
- one complete JSON object is written per line
- requests are read as one JSON object per stdin line
- logs or startup failures belong on stderr
- event messages do not have request IDs
- request responses preserve the request `id`

A host application should treat stdout as a strict NDJSON stream rather than human-readable CLI output.

## Protocol version

The bridge protocol currently uses:

```json
{"protocolVersion":"1"}
```

Each response and event includes `protocolVersion` so integrations can reject incompatible future protocol versions cleanly.

## Handshake

Request:

```json
{"id":1,"method":"hello"}
```

Example response:

```json
{
  "protocolVersion": "1",
  "id": 1,
  "result": {
    "protocolVersion": "1",
    "synapseCtrlVersion": "0.3.1",
    "transport": "stdio",
    "service": {
      "state": "ready",
      "synapseAvailable": true,
      "devices": [],
      "error": null,
      "updatedAtMs": 0
    }
  }
}
```

The `synapseCtrlVersion` value is illustrative; applications should use the value returned by the installed package.

## Requests

### Cached service state

```json
{"id":2,"method":"service.state"}
```

This does not force a Synapse read. It returns the most recently cached watcher state.

### Force a refresh

```json
{"id":3,"method":"service.refresh"}
```

### List devices

```json
{"id":4,"method":"devices.list"}
```

### Resolve a device

`device` and `deviceId` accept either a stable device ID or an unambiguous name selector.

```json
{
  "id":5,
  "method":"device.resolve",
  "params":{"device":"Naga"}
}
```

The result is the normal full device object, so callers can use the same operation for name-to-ID or ID-to-name lookup.

### List profiles

```json
{"id":6,"method":"profiles.list","params":{"deviceId":"DEVICE_ID"}}
```

### Resolve a profile

`profile` and `profileId` accept either a profile GUID or an unambiguous profile name within the selected device.

```json
{
  "id":7,
  "method":"profile.resolve",
  "params":{
    "device":"Naga",
    "profile":"Siege"
  }
}
```

The result is the normal full profile object.

### Get full status

```json
{"id":8,"method":"status.get"}
```

`status.get` returns the normal `Status` model. Its `versions` object includes the installed SynapseCTRL backend plus managed hook metadata when available:

```json
{
  "protocolVersion": "1",
  "id": 8,
  "result": {
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

The build suffix comes from the packaged hook SHA-256 fingerprint, so integrations can tell the difference between two hook implementations even when they share a compatible numeric protocol. A stale/mismatched persistent hook can make status `degraded` while the currently-running Synapse instance is still reachable.

### Activate a profile

```json
{
  "id":9,
  "method":"profile.activate",
  "params":{
    "deviceId":"DEVICE_ID",
    "profileId":"PROFILE_GUID",
    "timeout":5,
    "verify":true
  }
}
```

### Shut down

```json
{"id":10,"method":"shutdown"}
```

The bridge responds before exiting:

```json
{
  "protocolVersion":"1",
  "id":10,
  "result":{"shuttingDown":true}
}
```

## Events

The service watcher polls Synapse while the bridge is alive. It emits events only when meaningful state changes occur.

### Synapse becomes available

```json
{
  "protocolVersion":"1",
  "event":"synapse.available",
  "data":{"state":"ready"}
}
```

### Synapse becomes unavailable

```json
{
  "protocolVersion":"1",
  "event":"synapse.unavailable",
  "data":{
    "state":"unavailable",
    "error":{
      "code":"inspector_unreachable",
      "message":"...",
      "details":{}
    }
  }
}
```

### Active profile changes

```json
{
  "protocolVersion":"1",
  "event":"profile.changed",
  "data":{
    "deviceId":"DEVICE_ID",
    "previousProfileId":"OLD_GUID",
    "profileId":"NEW_GUID"
  }
}
```

The bridge may also emit `devices.changed` and `device.changed` when the discovered device set or relevant device metadata changes.

Events have no `id` because they are unsolicited notifications rather than responses to requests.

## Errors

Request errors remain machine-readable:

```json
{
  "protocolVersion":"1",
  "id":12,
  "error":{
    "code":"device_not_found",
    "message":"No device matches ...",
    "details":{}
  }
}
```

Malformed protocol input uses bridge-specific errors such as:

- `invalid_json`
- `invalid_request`
- `invalid_params`
- `method_not_found`

One bad request does not terminate the bridge.

## Polling and reconnect behavior

Defaults:

```text
ready state:       0.75 seconds
unavailable state: 2.0 seconds
```

Override them when launching:

```powershell
SynapseCTRL bridge --poll-interval 1 --unavailable-interval 3
```

The persistent service keeps running when Synapse itself becomes unavailable. It records the unavailable state, emits an event, backs off to the unavailable polling interval, and automatically reports availability again after Synapse recovers.

## Inspector options

Use a non-default inspector port or connection timeout when needed:

```powershell
SynapseCTRL bridge --port 9333 --connect-timeout 4
```

These affect the Synapse inspector connection, not the bridge transport.

## Recommended ownership model

An integration should normally spawn the bridge itself with stdin/stdout pipes and keep the child process private.

For example, SynapseDeck is expected to start a bridge when its Stream Deck plugin process starts, pass its own PID with `--parent-pid`, communicate over stdin/stdout, and allow the bridge to exit automatically when the plugin stops.

Users should not need to manually keep a separate bridge terminal open.

## Bridge vs HTTP

The persistent service core is transport-independent:

```text
                 +--> SynapseCTRL bridge --stdio
SynapseService --+
                 +--> SynapseCTRL serve
```

Use the bridge when one local application owns SynapseCTRL for its lifetime and wants efficient event-driven communication without opening a network port.

Use the optional HTTP API when conventional REST clients are a better fit. HTTP support is installed with `SynapseCTRL[http]` and documented in [HTTP / REST API](HTTP.md).

SynapseDeck should use the stdio bridge, so SynapseDeck users do not need the HTTP extra or a separately managed HTTP server.
