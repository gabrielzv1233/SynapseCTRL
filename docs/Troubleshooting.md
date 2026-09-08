# Troubleshooting

Start here whenever SynapseCTRL stops working after setup or a Razer Synapse update.

If SynapseCTRL was installed from PyPI or as an uv tool, run `SynapseCTRL` directly. From a source checkout, prefix the same commands with `uv run`.

## 1. Run the product diagnostic

```powershell
SynapseCTRL doctor
```

This is the preferred first check because it tests:

- whether Synapse appears to be running
- whether the inspector is reachable
- whether the target is the Electron browser process
- whether required Electron APIs are available
- renderer/storage discovery
- device controllability
- bootstrap/hook health

## 2. Save a report

```powershell
SynapseCTRL doctor --out .\report.json
```

Review the file before sharing it. Diagnostic reports can include device identifiers, profile names, renderer names, and private Synapse metadata.

## Inspector unreachable

Make sure Synapse is running and inspect the automatic hook first:

```powershell
SynapseCTRL hook status
```

Repair it with:

```powershell
SynapseCTRL hook repair
```

Then fully exit Synapse from the tray and reopen it.

> If this started immediately after a Razer Synapse update, `SynapseCTRL hook repair` is the normal repair step when `doctor` or `hook status` reports the hook as missing or unhealthy.

The raw `Install-SynapseInspectHook.ps1` script remains in the source repository for lower-level installer debugging, but normal users do not need to invoke it directly.

## Device appears but is not controllable

Use:

```powershell
SynapseCTRL devices --json
```

Inspect `controllable` and `unavailableReason` for that device.

SynapseCTRL intentionally refuses to guess when private Synapse state cannot be attributed safely to one physical device.

## Profile switch timed out

A verification timeout means the switch request was sent but the requested active profile was not confirmed before the deadline.

Refresh state before sending another request:

```powershell
SynapseCTRL profiles "DEVICE"
```

Then retry only if needed.

You can also increase verification time:

```powershell
SynapseCTRL switch "DEVICE" "PROFILE" --timeout 10
```

## Deep diagnostics after a Synapse update

The repository includes developer investigation tools under `codex-stuff/tools`.

Typical sequence from a source checkout:

```powershell
uv run python .\codex-stuff\tools\probe.py
uv run python .\codex-stuff\tools\renderers.py
uv run python .\codex-stuff\tools\devices.py --json
uv run python .\codex-stuff\tools\storage.py --contains synapse_
uv run python .\codex-stuff\tools\diagnostic_bundle.py --out .\codex-stuff\diagnostics\snapshot.json
powershell -NoProfile -ExecutionPolicy Bypass -File .\codex-stuff\tools\hook_status.ps1
```

These tools intentionally expose more private Synapse detail than the public SDK/CLI. Keep them as developer diagnostics rather than application interfaces.

## Uninstall the hook

```powershell
SynapseCTRL hook uninstall
```

Fully restart Synapse afterward.
