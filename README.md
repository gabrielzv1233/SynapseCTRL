# SynapseCTRL

Control Razer Synapse 4 **software profiles** from Python or a terminal. Discover devices, list their profiles, and switch by stable identifiers with active-state verification.

SynapseCTRL runs locally on Windows alongside Synapse. It uses Synapse's own software-profile switching path through the Electron browser process. Device names, profile GUIDs, and internal routing are discovered automatically.

```powershell
uv run synapsectrl devices
uv run synapsectrl profiles "Naga"
uv run synapsectrl switch "Naga" "Seige"
```

Names above are examples. Use the devices and profiles reported by your installation; use their IDs for unattended scripts.

## Install and connect

Requirements: Windows, Razer Synapse 4 with a supported connected device, Python 3.13 or newer, and a local inspector enabled for the Razer App Engine browser process. Compatibility is checked through available capabilities rather than a fixed Synapse version.

From this checkout:

```powershell
uv sync
uv run synapsectrl status
```

With ordinary Python packaging instead:

```powershell
python -m pip install .
synapsectrl status
```

From the source checkout, enable automatic inspector launch once using the supplied installer. This script is included with the source distribution; it is not installed as a command inside the Python wheel. Windows requests administrator elevation because this installs a filtered Image File Execution Options (IFEO) hook and a launch shim under Program Files:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-SynapseInspectHook.ps1 -NoPause
```

The installer waits for completion and returns a nonzero exit code if installation fails. `-NoPause` avoids a final Enter prompt; it does not bypass Windows elevation. The installer does not terminate Synapse. After installation, fully exit Synapse from its tray menu and launch it normally. Subsequent normal launches enable the inspector at `127.0.0.1:9229`; the shim locates the newest versioned App Engine installation after updates. No separate debug launcher is needed.

```powershell
uv run synapsectrl doctor
uv run synapsectrl devices
```

The installer does not need to run for each profile change. To remove automatic inspector launch:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-SynapseInspectHook.ps1 -Uninstall -NoPause
```

Exit and reopen Synapse normally after removal to stop the inspector in an already-running process.

## Command line

| Command | Result |
| --- | --- |
| `synapsectrl status` | Connection, compatibility, device counts, and repair guidance |
| `synapsectrl devices` | Device IDs, names, connection state, and active profiles |
| `synapsectrl profiles DEVICE` | Profile GUIDs, names, and active markers |
| `synapsectrl switch DEVICE PROFILE` | A switch with active-state verification |
| `synapsectrl doctor --out report.json` | Diagnostic report, including launch-hook status |

Every command accepts `--json`, before or after the command. JSON output is a single UTF-8 object with `apiVersion: "1"` and either `data` or `error`. Diagnostic files use the same envelope. Commands never prompt for device selection.

```powershell
uv run synapsectrl devices --json
uv run synapsectrl profiles "DEVICE_ID_FROM_DISCOVERY" --json
uv run synapsectrl switch "DEVICE_ID_FROM_DISCOVERY" "PROFILE_GUID" --timeout 5 --json
```

Device and profile selectors resolve by exact ID, case-insensitive exact name, then unique name substring. Ambiguous names fail with candidate IDs. The profile lookup is always scoped to the selected device.

`switch --timeout SECONDS` controls the verification deadline after dispatch; initial discovery and dispatch use the separate inspector timeout. `--no-verify` returns after sending. A timeout means the active profile could not be confirmed, and the request may still take effect. Global `--timeout` (before the command) or `--connect-timeout` sets the inspector operation timeout; the default is eight seconds. `--port` selects another local inspector port if one was configured separately.

| Exit code | Meaning |
| --- | --- |
| `0` | Command succeeded; a switch is `verified`, `already_active`, or explicitly `sent` with verification disabled |
| `1` | Operation failed, or status/doctor reports `degraded` or `unavailable` |
| `2` | Invalid arguments, missing selector match, or ambiguous selection |
| `3` | Switch verification timed out |
| `130` | Interrupted by the user |

The [API reference](docs/API.md) defines models, JSON examples, error codes, and the difference between sent and verified outcomes.

## Python SDK

```python
from synapsectrl import SynapseClient, SynapseError

try:
    with SynapseClient() as synapse:
        for device in synapse.list_devices():
            print(device.id, device.name, device.controllable)
            for profile in device.profiles:
                print("*" if profile.active else " ", profile.id, profile.name)

        result = synapse.switch_profile("DEVICE_ID_FROM_DISCOVERY", "PROFILE_GUID")
        if result.verified:
            print("Active profile confirmed:", result.profile_id)
        else:
            print("Switch outcome:", result.status, result.error)
except SynapseError as error:
    print(error.code, str(error))
```

Replace the placeholder IDs with discovery results. See [examples/switch_profile.py](examples/switch_profile.py) for a runnable example with arguments and exit codes. `python -m synapsectrl` also supports the full CLI.

## Identity and compatibility

Device IDs use `razer:VENDOR_ID:PRODUCT_ID:CONTAINER`, with decimal numeric IDs and a lowercase container GUID without braces. They remain consistent across Synapse renderer reloads, rediscovery, and restarts while Windows reports the same container. A hardware/driver reinstall or a changed Windows container can change the ID. Profile IDs come from Synapse's profile GUIDs; renaming a profile preserves its identity, while deleting and recreating it may produce a new GUID.

Discovery supports multiple devices and does not hardcode a product, vendor, renderer count, or profile. Devices sharing a product ID require state that can be attributed to the correct container. When Synapse exposes only shared product-level state for identical devices, SynapseCTRL reports them as unavailable for switching instead of guessing the destination or verified active state.

Synapse updates can change private interfaces. `status` distinguishes ready, degraded, and unavailable states; `doctor` reports capabilities, renderer identities, storage discovery, and reasons a device cannot be controlled. Verification confirms Synapse's reported active profile. It does not independently measure the physical device's applied settings.

## Troubleshooting

Start with the product diagnostic report:

```powershell
uv run synapsectrl doctor --out .\astra\diagnostics\product.json
```

If the inspector is unreachable, ensure Synapse is running, inspect the automatic launch hook, and follow the report's repair guidance. If an update changes discovery, use the supplied handoff diagnostics:

```powershell
uv run python .\astra\tools\probe.py
uv run python .\astra\tools\renderers.py
uv run python .\astra\tools\devices.py --json
uv run python .\astra\tools\storage.py --contains synapse_
uv run python .\astra\tools\diagnostic_bundle.py --out .\astra\diagnostics\snapshot.json
powershell -NoProfile -ExecutionPolicy Bypass -File .\astra\tools\hook_status.ps1
```

The [tool documentation](astra/tools/README.md) covers targeted storage inspection and deeper investigation. The original [synapse_ctrl.py](synapse_ctrl.py) remains the known-good behavioral reference; the normal product interface is the installable `synapsectrl` package.

## Local security boundary

The Node inspector can execute code inside Synapse. Keep it bound to `127.0.0.1`, and enable it only on a machine where you trust local software and users. The SDK enforces a loopback endpoint and validates inspector targets. It does not provide an HTTP service, remote-control server, arbitrary JavaScript evaluation, or public raw WebSocket access. The diagnostic tools under `astra/tools` deliberately expose more power and should stay developer tools.

Diagnostic reports include device identifiers, profile names, and internal renderer/storage metadata. Review reports before sharing them. Full storage dumping is reserved for the supplied investigation tools.

## Development and validation

```powershell
uv sync
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src examples
uv run synapsectrl --help
powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_installer.ps1
uv build
```

The automated suite uses fixtures and simulated inspector responses to exercise discovery, ambiguity, protocol behavior, connection failures, verification, and CLI output without changing hardware. These tests do not prove compatibility with every Synapse release or device.

Run the opt-in live acceptance harness from the checkout:

```powershell
# Read-only discovery equivalence
uv run python tests/live_synapse.py
# Change to another existing profile, verify, and restore the starting profile
uv run python tests/live_synapse.py --switch-roundtrip
```

Use `--device DEVICE_ID` when more than one eligible device is connected. The harness reads state using the preserved reference controller, exercises SDK switching and CLI restoration, and restores the starting profile in `finally`. Live switching changes the device's Synapse configuration. Local reports go to the ignored `astra/diagnostics/` directory. [Acceptance findings](astra/PRODUCT_FINDINGS.md) record the live results and a stale profile-stack issue found during equivalence testing.
