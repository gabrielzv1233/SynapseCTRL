# CLI & JSON

SynapseCTRL's CLI is designed for both people and other programs.

Human-readable output is the default. Add `--json` when another tool needs a stable machine-readable result.

If installed from PyPI or as an uv tool, run `SynapseCTRL` directly. From a source checkout, prefix commands with `uv run`.

## Core commands

```powershell
SynapseCTRL status
SynapseCTRL devices
SynapseCTRL profiles "Naga"
SynapseCTRL resolve device "Naga"
SynapseCTRL resolve profile "Naga" "Siege"
SynapseCTRL switch "Naga" "Siege"
SynapseCTRL doctor
```

Use IDs reported by discovery for unattended automation.

## Resolve names and IDs

Resolve a device selector to the current full device object:

```powershell
SynapseCTRL resolve device "Naga"
```

Resolve a profile within a selected device:

```powershell
SynapseCTRL resolve profile "Naga" "Siege"
```

Both selectors may also be stable IDs. Human-readable output prints the resolved name and ID; `--json` returns the full `Device` or `Profile` representation:

```powershell
SynapseCTRL resolve device "DEVICE_ID" --json
SynapseCTRL resolve profile "DEVICE_ID" "PROFILE_GUID" --json
```

This provides explicit name ↔ ID lookup while preserving the same exact-ID, exact-name, and unambiguous-substring selection rules used by `profiles` and `switch`.

## Persistent bridge

For integrations that stay alive and need frequent state updates, use the built-in bridge instead of repeatedly spawning one-shot CLI commands:

```powershell
SynapseCTRL bridge
```

The current/default bridge transport is newline-delimited JSON over stdin/stdout. It can also be selected explicitly:

```powershell
SynapseCTRL bridge --stdio
```

A host process can pass its PID so the bridge automatically exits if the owner disappears:

```powershell
SynapseCTRL bridge --stdio --parent-pid 12345
```

The bridge keeps one persistent Synapse client and state watcher alive, emits profile/device/Synapse availability events, and reserves stdout exclusively for protocol JSON.

See [Persistent Bridge](Bridge.md) for the protocol, lifecycle, methods, events, and ownership model.

## HTTP / REST server

HTTP support is optional and uses Starlette + Uvicorn. Install the extra first:

```powershell
uv tool install "SynapseCTRL[http]"
```

or:

```powershell
python -m pip install "SynapseCTRL[http]"
```

Then start the local REST API:

```powershell
SynapseCTRL serve
```

The default listener is:

```text
http://127.0.0.1:8765
```

Useful options:

```powershell
SynapseCTRL serve --port 9000
SynapseCTRL serve --inspector-port 9333
SynapseCTRL serve --poll-interval 1 --unavailable-interval 3
SynapseCTRL serve --no-access-log
```

Binding to a non-loopback address such as `0.0.0.0` exposes an unauthenticated profile-control API to the reachable network, so SynapseCTRL prints a warning and the default remains loopback-only.

See [HTTP / REST API](HTTP.md) for endpoints, curl examples, error mappings, and security details.

## Hook management

The required Synapse launch hook can be managed without locating the PowerShell installer manually:

```powershell
SynapseCTRL hook install
SynapseCTRL hook status
SynapseCTRL hook repair
SynapseCTRL hook uninstall
```

`install` and `repair` run the packaged `Install-SynapseInspectHook.ps1` installer and may request Windows administrator elevation. Fully exit and reopen Razer Synapse after install, repair, or uninstall.

The hook commands also support JSON:

```powershell
SynapseCTRL hook status --json
```

## JSON mode

Every normal one-shot command accepts `--json`:

```powershell
SynapseCTRL devices --json
SynapseCTRL profiles "Naga" --json
SynapseCTRL resolve profile "Naga" "Siege" --json
SynapseCTRL switch "Naga" "Siege" --json
```

Successful output is exactly one JSON object on stdout:

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
    "code": "profile_not_found",
    "message": "No profile matches this selector.",
    "details": {}
  }
}
```

Do not parse human-readable output if you are building an integration.

## Why this is useful

A non-Python program doing occasional operations can simply:

1. start `SynapseCTRL ... --json`
2. capture stdout
3. parse the JSON object
4. inspect the process exit code

This works well for:

- PowerShell automation
- Node.js
- C#
- AutoHotkey
- launchers and macro tools

For Stream Deck plugins and other high-frequency/persistent integrations owned by one local process, prefer `SynapseCTRL bridge --stdio` so one process and connection remain alive.

For tools that want a conventional REST API instead of owning a child process, use `SynapseCTRL serve`.

## Device selectors

Selectors resolve in this order:

1. exact stable device ID
2. case-insensitive exact name
3. unique case-insensitive name substring

Example convenience selector:

```powershell
SynapseCTRL profiles "Naga"
```

For unattended use:

```powershell
SynapseCTRL profiles "razer:5426:180:DEVICE_CONTAINER_ID"
```

## Profile selectors

Profile selectors use the same idea: profile GUID first, then human-readable name matching within the selected device.

Convenience:

```powershell
SynapseCTRL switch "Naga" "Siege"
```

Automation:

```powershell
SynapseCTRL switch "DEVICE_ID" "PROFILE_GUID"
```

## Verification

A normal switch verifies the requested profile afterward:

```powershell
SynapseCTRL switch "Naga" "Siege"
```

Control the verification deadline:

```powershell
SynapseCTRL switch "Naga" "Siege" --timeout 5
```

Skip verification only when you explicitly want fire-and-forget behavior:

```powershell
SynapseCTRL switch "Naga" "Siege" --no-verify
```

A timeout means SynapseCTRL sent the request but did not confirm the requested active profile before the deadline. Refresh current state before deciding to retry.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | runtime failure, failed switch, degraded/unavailable health, or unhealthy hook status |
| `2` | bad arguments, missing optional HTTP dependencies, not found, or ambiguous selector |
| `3` | verification timeout |
| `130` | interrupted |

For one-shot automation, inspect both the exit code and JSON result. Bridge mode instead uses its persistent protocol responses and events until the bridge process exits. HTTP mode communicates through HTTP status codes plus the same versioned JSON envelope.

## Diagnostics

```powershell
SynapseCTRL doctor
```

Save the structured report:

```powershell
SynapseCTRL doctor --out .\report.json
```

See [Troubleshooting](Troubleshooting.md) for repair flow and deeper diagnostic tools.
