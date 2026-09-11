# SynapseCTRL API

The public interface is a synchronous Python SDK and a noninteractive CLI. Both discover current Synapse state automatically. Normal calls use device and profile IDs or unambiguous names.

## Client

```python
from synapsectrl import SynapseClient, SynapseError

with SynapseClient(host="127.0.0.1", port=9229, timeout=8.0) as client:
    status = client.status()
    devices = client.list_devices()
```

`host` accepts `127.0.0.1` or `localhost`, normalized to the numeric loopback address. `timeout` is the inspector operation timeout in seconds and must be positive and finite. Connections are lazy. The context manager closes the client connection when leaving the block; `close()` is also available. Calls on one client are serialized, including verification. Separate simultaneous controllers can change the observed active state.

| Method | Return value | Behavior |
| --- | --- | --- |
| `list_devices()` | `tuple[Device, ...]` | Discover devices, profiles, active state, and controllability |
| `resolve_device(device)` | `Device` | Resolve a device ID or unambiguous name and return its current full snapshot |
| `list_profiles(device)` | `tuple[Profile, ...]` | Resolve one device and return its software profiles |
| `resolve_profile(device, profile)` | `Profile` | Resolve a profile ID or unambiguous name within one selected device |
| `switch_profile(device, profile, *, timeout=5.0, verify=True)` | `SwitchResult` | Resolve, send both Synapse switch messages, and optionally verify |
| `status()` | `Status` | Summarize health, returning unavailable state for expected connection/compatibility failures |
| `diagnostics()` | `dict` | Include status, bootstrap inspection, renderer and storage evidence, and device diagnostics |

`resolve_device()` and `resolve_profile()` expose the same selector logic used internally by `list_profiles()` and `switch_profile()`. Because they return normal model objects rather than only a string, one operation supports both name-to-ID and ID-to-name lookup while also returning current metadata:

```python
device = client.resolve_device("Naga")
print(device.name, device.id)

profile = client.resolve_profile(device.id, "Siege")
print(profile.name, profile.id)
```

Discovery runs against current state; applications should refresh after Synapse or device changes. Persist IDs rather than renderer names or internal routing. Reconnecting probes the available capabilities again.

Selectors resolve in this order:

1. Exact stable ID (case-insensitive).
2. Case-insensitive exact name.
3. A unique case-insensitive substring of the name.

No match raises `device_not_found` or `profile_not_found`. Multiple matches at the selected precedence raise `ambiguous_device` or `ambiguous_profile` with candidate information. An empty selector is invalid. Profile selection only searches the chosen device.

## Persistent service

`SynapseService` exposes the same `resolve_device(device)` and `resolve_profile(device, profile)` operations through its persistent client. Long-lived transports such as the stdio bridge and HTTP server use this service layer so they share the SDK's exact selector behavior instead of implementing separate lookup rules.

## Models

Public model attributes use Python `snake_case`; `to_dict()` produces JSON-ready `camelCase`. Collections in the Python API are tuples; their JSON representations are arrays. Treat device/profile results as snapshots and call discovery again for current state.

### Device

| Python attribute | JSON key | Meaning |
| --- | --- | --- |
| `id` | `id` | Normalized stable device identifier |
| `name` | `name` | Human-readable name, with a product-based fallback |
| `vendor_id` | `vendorId` | Vendor ID from discovered device identity |
| `product_id` | `productId` | Product ID |
| `container_id` | `containerId` | Windows container identity, when available |
| `serial_number` | `serialNumber` | Serial metadata, when available |
| `connected` | `connected` | Whether current discovery identifies a connected instance |
| `profiles_supported` | `profilesSupported` | Whether software profiles were discovered |
| `controllable` | `controllable` | Whether switching can safely target this device |
| `unavailable_reason` | `unavailableReason` | Explanation when switching is unavailable |
| `active_profile_id` | `activeProfileId` | Discovered active profile GUID, when recognized |
| `profiles` | `profiles` | Profile snapshots for this device |

Device identity uses `razer:VENDOR_ID:PRODUCT_ID:CONTAINER`, with decimal vendor/product IDs and a lowercase container GUID without braces. It is stable while that identity remains the same. It does not promise persistence across Windows device re-enumeration that changes the container ID. Serial metadata enriches the model without becoming a required routing input.

Several devices can share a product ID. Container-attributed profile state is required to safely control such devices when a shared product-level storage family cannot distinguish them. Unresolved routing or active-state ambiguity makes the device unavailable for switching; inspect `unavailable_reason` and `diagnostics()`.

### Profile

| Attribute / JSON key | Meaning |
| --- | --- |
| `id` | Synapse profile GUID |
| `name` | Readable software-profile name |
| `active` | Whether this GUID matches the device's recognized active profile |

GUIDs survive profile renaming but can change when profiles are deleted and recreated. The API controls Synapse software profiles rather than onboard hardware profile slots.

### SwitchResult

| Python attribute | JSON key | Meaning |
| --- | --- | --- |
| `status` | `status` | `verified`, `sent`, `already_active`, `timeout`, or `failed` |
| `device_id` | `deviceId` | Resolved stable device ID |
| `profile_id` | `profileId` | Resolved target GUID |
| `previous_profile_id` | `previousProfileId` | Active GUID discovered before the request, when available |
| `sent` | `sent` | Whether the request was confirmed sent |
| `verified` | `verified` | Whether the target was observed as active |
| `elapsed_ms` | `elapsedMs` | Elapsed operation time in milliseconds |
| `error` | `error` | Structured failure information or `null` |

`verified` means a fresh discovery observed the target as active. `already_active` means the target was active during initial discovery and no switch was needed (`sent=False`, `verified=True`). `sent` is returned when verification is explicitly disabled. A `timeout` is an unconfirmed outcome and must not be reported as a verified switch. The request might have taken effect after the deadline; refresh discovery before deciding whether to send another request. `failed` includes a structured reason.

The verification deadline begins after dispatch and is separate from the inspector operation timeout for initial discovery and sending. Read operations can reconnect, but a switch request is never automatically sent a second time. If delivery fails during dispatch, `sent=False` means delivery was not confirmed; `error.details.deliveryUnknown=True` indicates the messages might have reached Synapse. Read the current profile before retrying.

The SDK verifies Synapse's exposed active state, not physical hardware behavior. A device can disconnect, Synapse can restart, or another application can switch profiles while a request is in progress. Failures before a switch can raise `SynapseError`; inspect the result for a returned operation outcome rather than assuming every failure is an exception.

### Status

| Python attribute | JSON key | Meaning |
| --- | --- | --- |
| `state` | `state` | `ready`, `degraded`, or `unavailable` |
| `synapse_running` | `synapseRunning` | `true`, `false`, or `null` when process state is unknown |
| `inspector_reachable` | `inspectorReachable` | Inspector discovery is reachable |
| `browser_process` | `browserProcess` | Target is the Electron browser process |
| `electron_available` | `electronAvailable` | Electron APIs required by the integration are available |
| `device_count` | `deviceCount` | Number of discovered devices |
| `controllable_device_count` | `controllableDeviceCount` | Number currently safe to switch |
| `versions` | `versions` | Synapse runtime versions plus SynapseCTRL backend and managed hook metadata |
| `issues` | `issues` | Current problems |
| `repair` | `repair` | Actionable next steps |

`versions` retains runtime entries such as `electron`, `chrome`, and `node`, and also exposes the local integration versions when available:

| Key | Meaning |
| --- | --- |
| `synapseCtrl` | Installed SynapseCTRL backend/package version |
| `hook` | Installed numeric hook revision |
| `hookExpected` | Hook revision expected by this backend |
| `hookProtocol` | Installed hook protocol revision |
| `hookProtocolExpected` | Protocol revision expected by this backend |
| `hookBuild` | Installed exact build ID, such as `v3+1a2b3c4d5e6f` |
| `hookExpectedBuild` | Exact hook build packaged with this backend |
| `hookInstalledBy` | SynapseCTRL version that last installed/repaired the managed hook |

The build ID incorporates a SHA-256 fingerprint of the packaged hook implementation, so it changes automatically when that hook code changes even when the numeric protocol stays compatible.

`status()` returns an unavailable result for expected inspector/compatibility problems so callers can display repair guidance without parsing exceptions. An otherwise live Synapse session can report `degraded` when the persistent launch hook is stale or mismatched, because the next normal Synapse launch would not be using the hook build expected by the current backend. Discovery and switching raise structured errors when their prerequisites fail.

## Errors

`SynapseError(code, message, details=None)` exposes `.code`, `.details`, the message through `str(error)`, and `.to_dict()`:

```json
{
  "code": "ambiguous_device",
  "message": "Multiple devices match this selector.",
  "details": {
    "matches": [
      {"id": "device-id-a", "name": "Razer Mouse"},
      {"id": "device-id-b", "name": "Razer Mouse"}
    ]
  }
}
```

Applications should branch on `code`; human messages and diagnostic details may gain additional context.

| Code | Caller action |
| --- | --- |
| `invalid_argument` | Fix the selector, port, host, or timeout |
| `device_not_found`, `profile_not_found` | Refresh discovery and choose a current ID |
| `ambiguous_device`, `ambiguous_profile` | Use an exact ID from the candidates |
| `device_unavailable` | Inspect the device reason and diagnostic report |
| `inspector_unreachable` | Start Synapse and inspect/repair automatic inspector launch |
| `inspector_protocol_error` | Inspect the endpoint and diagnostic compatibility evidence |
| `incompatible_synapse` | Use the supplied capability and renderer diagnostics after an update |
| `transport_lost` | Refresh state after reconnecting; a sent mutation may have an uncertain outcome |
| `verification_timeout` | Refresh active state before considering another switch |
| `switch_failed` | Inspect the result error and rediscover the target |

The CLI also emits `io_error` for report-file failures and `interrupted` for Ctrl+C.

## CLI JSON contract

`synapsectrl ... --json` emits exactly one JSON object on stdout, without a progress banner. Successful discovery, resolution, or operation outcomes use `data`.

Resolver examples:

```powershell
SynapseCTRL resolve device "Naga" --json
SynapseCTRL resolve profile "Naga" "Siege" --json
```

A device resolver returns one full device object in `data`; a profile resolver returns one full profile object. This is distinct from `devices` and `profiles`, which return arrays.

A switch result uses:

```json
{
  "apiVersion": "1",
  "data": {
    "status": "verified",
    "deviceId": "device-id-from-discovery",
    "profileId": "profile-guid-from-discovery",
    "previousProfileId": "previous-profile-guid",
    "sent": true,
    "verified": true,
    "elapsedMs": 412,
    "error": null
  }
}
```

`devices` and `profiles` return arrays in `data`; `status` returns a status object. `doctor` returns a diagnostic object containing its own `status`. A failed command that raises an error instead uses:

```json
{
  "apiVersion": "1",
  "error": {
    "code": "profile_not_found",
    "message": "No profile matches the requested selector.",
    "details": {}
  }
}
```

A `SwitchResult` with `status: "timeout"` or `status: "failed"` remains in `data`, with its own `error`, and exits nonzero. A degraded/unavailable `status` or `doctor` report also remains in `data` and exits `1`. Check both exit code and structured outcome.

| Exit code | Meaning |
| --- | --- |
| `0` | Successful command or explicitly unverified sent request |
| `1` | Runtime/I/O failure or degraded/unavailable health report |
| `2` | Invalid command/argument or failed/ambiguous selector resolution |
| `3` | Verification deadline expired |
| `130` | Interrupted |

The envelope version describes the normal public schema. Diagnostic payloads contain private Synapse evidence and may grow or change with Synapse releases. Raw renderer names, channels, and storage keys are diagnostic output rather than normal API inputs.

The diagnostic report contains `status`, `bootstrap`, `capabilities`, `renderers`, `rendererCount`, `storageKeys`, `devices`, `deviceDetails`, and `warnings`. `bootstrap` reports whether the filtered automatic launch hook is installed and healthy, the installed and expected hook revisions/protocols/build fingerprints, the SynapseCTRL version that installed it, the install timestamp, the selected versioned launcher, issues, and repair steps. `renderers` omits full storage values. Inspect bootstrap health separately from current runtime health: an already-running inspector may work while automatic launch is stale and requires repair.

`doctor --out FILE` atomically writes the same UTF-8 JSON envelope, creating parent directories as needed. A successful write replaces an existing report at that path. Report-file failures return `io_error` without claiming that the report was saved.

## Boundaries

The SDK connects locally to the inspector; it does not start a network service or expose evaluation primitives. The inspector itself is a powerful code-execution interface inside Synapse and must remain bound to loopback. Keep the host restricted and review diagnostic metadata before sharing it.

Use the [managed hook setup](Setup.md) for normal automatic-launch installation and repair. The low-level native hook script remains in the repository for installer development. The [supplied diagnostics](../astra/tools/README.md) are the investigation path when a Synapse update changes internal behavior. The original controller and observed handoff values provide regression evidence rather than compatibility guarantees for every device.
