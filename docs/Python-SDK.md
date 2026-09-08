# Python SDK

Use the Python SDK when your application is already Python or when you want a persistent SynapseCTRL client instead of spawning the CLI repeatedly.

## Basic usage

```python
from synapsectrl import SynapseClient

with SynapseClient() as client:
    for device in client.list_devices():
        print(device.id, device.name)

    result = client.switch_profile("Naga", "Siege")
    print(result.status, result.verified)
```

## Core methods

```python
client.status()
client.list_devices()
client.list_profiles(device)
client.switch_profile(device, profile, timeout=5.0, verify=True)
client.diagnostics()
```

## Prefer IDs for automation

Names are convenient for people:

```python
client.switch_profile("Naga", "Siege")
```

Stable IDs are better for unattended integrations:

```python
client.switch_profile(
    "razer:5426:180:DEVICE_CONTAINER_ID",
    "PROFILE_GUID",
)
```

Device IDs and profile GUIDs come from live discovery. Do not hardcode documentation examples.

## JSON-ready models

Public models expose Python attributes and `.to_dict()` for serialization:

```python
devices = [device.to_dict() for device in client.list_devices()]
```

This is the recommended path when building your own local HTTP, IPC, or plugin service around SynapseCTRL.

## Persistent services

For a high-frequency integration, keep a `SynapseClient` alive inside your own service:

```text
HTTP / IPC / plugin request
        ↓
your service
        ↓
SynapseClient
        ↓
Razer Synapse
```

Do not expose the underlying Electron inspector to other machines. Keep that bound to loopback and expose only your own authenticated application-level interface.

## Errors

Catch `SynapseError` and branch on `.code` rather than human-readable text:

```python
from synapsectrl import SynapseClient, SynapseError

try:
    with SynapseClient() as client:
        client.switch_profile("Naga", "Siege")
except SynapseError as error:
    print(error.code)
    print(error.details)
```

See [API reference](API.md) for all models, error codes, selector rules, and switch-result semantics.
