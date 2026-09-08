# Getting Started

SynapseCTRL needs one Windows-side setup step before it can read or control Razer Synapse 4 profiles: **install the included Synapse inspector hook**.

## Uninstall / remove the hook

If you are here to remove SynapseCTRL's automatic Synapse hook:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-SynapseInspectHook.ps1 -Uninstall -NoPause
```

Then fully exit Synapse from the tray and reopen it normally. See [Setup & Advanced Options](Setup.md#uninstalling) for details.

---

## 1. Install project dependencies

From the SynapseCTRL checkout:

```powershell
uv sync
```

Or install with normal Python packaging:

```powershell
python -m pip install .
```

SynapseCTRL currently requires Windows and Python 3.13+.

## 2. REQUIRED: install the Synapse inspector hook

Run:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-SynapseInspectHook.ps1 -NoPause
```

Windows will request administrator elevation. The installer configures normal Razer Synapse launches so the Razer App Engine browser process starts with a localhost-only Node inspector.

After the installer completes:

1. Fully exit Razer Synapse from its tray menu.
2. Launch Razer Synapse normally.
3. Continue with the checks below.

> **After Razer Synapse updates, you may need to rerun this installer if `synapsectrl doctor` reports that the automatic hook is missing or unhealthy.** The current shim automatically locates the newest `app-*` Razer App Engine directory, so a version-folder change alone normally does not require reinstalling the hook.

For how the hook works and advanced options, see [Setup & Advanced Options](Setup.md).

## 3. Check that SynapseCTRL can connect

```powershell
uv run synapsectrl status
```

For the most useful setup check, run:

```powershell
uv run synapsectrl doctor
```

A healthy setup should report `ready` and show a reachable inspector plus discovered device information.

## 4. List your devices

```powershell
uv run synapsectrl devices
```

Example shape:

```text
Razer Naga V2 Hyperspeed
  id: razer:5426:180:...
  active profile: ...
```

Do not copy example IDs from documentation. Use the IDs reported by your own installation.

## 5. List profiles for a device

Human-readable names work when they are unambiguous:

```powershell
uv run synapsectrl profiles "Naga"
```

You will get the software profiles SynapseCTRL discovered for that device, including GUIDs and the active marker.

## 6. Switch a profile

Try a profile that actually exists on your device:

```powershell
uv run synapsectrl switch "Naga" "Siege"
```

For unattended automation, prefer the stable device ID and profile GUID returned by discovery:

```powershell
uv run synapsectrl switch "DEVICE_ID_FROM_DISCOVERY" "PROFILE_GUID"
```

By default, SynapseCTRL sends the switch through Synapse and then verifies that Synapse reports the requested profile as active.

## 7. Try JSON output

Anything that needs to consume SynapseCTRL programmatically should use `--json` instead of parsing human-readable terminal output:

```powershell
uv run synapsectrl devices --json
uv run synapsectrl profiles "Naga" --json
uv run synapsectrl switch "Naga" "Siege" --json
```

Successful output is a single JSON object with `apiVersion: "1"` and `data`. Errors use the same envelope with an `error` object.

## Where next?

- [CLI & JSON](CLI.md) for scripting and other languages
- [Python SDK](Python-SDK.md) for direct Python integration
- [API reference](API.md) for exact models and errors
- [Troubleshooting](Troubleshooting.md) if any command above fails
- [How it Works](Architecture.md) if you want the technical internals
