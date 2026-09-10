# Python SDK

Use the Python SDK when your application is already Python or when you want a persistent SynapseCTRL client instead of spawning the CLI repeatedly.

## Basic usage

```python
from synapsectrl import SynapseClient

with SynapseClient() as client:
    device = client.resolve_device("Naga")
    profile = client.resolve_profile(device.id, "Siege")

    print(device.name, device.id)
    print(profile.name, profile.id)

    result = client.switch_profile(device.id, profile.id)
    print(result.status, result.verified)
```

## Core methods

```python
client.status()
client.list_devices()
client.resolve_device(device)
client.list_profiles(device)
client.resolve_profile(device, profile)
client.switch_profile(device, profile, timeout=5.0, verify=True)
client.diagnostics()
```

`resolve_device()` and `resolve_profile()` accept the same selectors as the rest of SynapseCTRL and return the normal `Device` or `Profile` object. This makes name-to-ID and ID-to-name lookup explicit without maintaining a separate mapping API:

```python
device = client.resolve_device("Razer Naga V2 Hyperspeed")
print(device.id)

same_device = client.resolve_device(device.id)
print(same_device.name)

profile = client.resolve_profile(device.id, "Siege")
print(profile.id)
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

Resolved objects use the same models:

```python
resolved = client.resolve_profile("Naga", "Siege").to_dict()
```

This is the recommended path when building your own local HTTP, IPC, or plugin service around SynapseCTRL.

## Persistent services

For a high-frequency integration, use `SynapseService`, which exposes the same resolver operations while keeping the persistent client/state watcher architecture used by bridge and HTTP modes:

```python
from synapsectrl import SynapseService

with SynapseService() as service:
    device = service.resolve_device("Naga")
    profile = service.resolve_profile(device.id, "Siege")
```

Do not expose the underlying Electron inspector to other machines. Keep that bound to loopback and expose only your own authenticated application-level interface.

## Errors

Catch `SynapseError` and branch on `.code` rather than human-readable text:

```python
from synapsectrl import SynapseClient, SynapseError

try:
    with SynapseClient() as client:
        client.resolve_profile("Naga", "Siege")
except SynapseError as error:
    print(error.code)
    print(error.details)
```

See [API reference](API.md) for all models, error codes, selector rules, and switch-result semantics.
