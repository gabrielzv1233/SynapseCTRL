# CLI & JSON

SynapseCTRL's CLI is designed for both people and other programs.

Human-readable output is the default. Add `--json` when another tool needs a stable machine-readable result.

## Core commands

```powershell
uv run synapsectrl status
uv run synapsectrl devices
uv run synapsectrl profiles "Naga"
uv run synapsectrl switch "Naga" "Siege"
uv run synapsectrl doctor
```

Use IDs reported by discovery for unattended automation.

## JSON mode

Every normal command accepts `--json`:

```powershell
uv run synapsectrl devices --json
uv run synapsectrl profiles "Naga" --json
uv run synapsectrl switch "Naga" "Siege" --json
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

A non-Python program can simply:

1. start `synapsectrl ... --json`
2. capture stdout
3. parse the JSON object
4. inspect the process exit code

This works well for:

- Stream Deck plugins
- PowerShell automation
- Node.js
- C#
- AutoHotkey
- launchers and macro tools

For very frequent operations, use the Python SDK in a persistent helper/service instead of repeatedly spawning the CLI.

## Device selectors

Selectors resolve in this order:

1. exact stable device ID
2. case-insensitive exact name
3. unique case-insensitive name substring

Example convenience selector:

```powershell
uv run synapsectrl profiles "Naga"
```

For unattended use:

```powershell
uv run synapsectrl profiles "razer:5426:180:DEVICE_CONTAINER_ID"
```

## Profile selectors

Profile selectors use the same idea: profile GUID first, then human-readable name matching within the selected device.

Convenience:

```powershell
uv run synapsectrl switch "Naga" "Siege"
```

Automation:

```powershell
uv run synapsectrl switch "DEVICE_ID" "PROFILE_GUID"
```

## Verification

A normal switch verifies the requested profile afterward:

```powershell
uv run synapsectrl switch "Naga" "Siege"
```

Control the verification deadline:

```powershell
uv run synapsectrl switch "Naga" "Siege" --timeout 5
```

Skip verification only when you explicitly want fire-and-forget behavior:

```powershell
uv run synapsectrl switch "Naga" "Siege" --no-verify
```

A timeout means SynapseCTRL sent the request but did not confirm the requested active profile before the deadline. Refresh current state before deciding to retry.

## Exit codes

| Code | Meaning |
| --- | --- |
| `0` | success |
| `1` | runtime failure, failed switch, or degraded/unavailable health |
| `2` | bad arguments, not found, or ambiguous selector |
| `3` | verification timeout |
| `130` | interrupted |

For automation, inspect both the exit code and JSON result.

## Diagnostics

```powershell
uv run synapsectrl doctor
```

Save the structured report:

```powershell
uv run synapsectrl doctor --out .\report.json
```

See [Troubleshooting](Troubleshooting.md) for repair flow and deeper diagnostic tools.
