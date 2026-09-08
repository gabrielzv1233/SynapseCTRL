# Astra Debug Tools

These are **developer/reverse-engineering tools**, not the final SynapseCTRL product. They intentionally expose low-level details so Astra can inspect a new Synapse version/device without recreating tooling.

Run them from this folder (or add it to `PYTHONPATH`). They require the same `websocket-client` dependency used by the working controller.

## Quick sequence

```powershell
uv run python .\astra\tools\probe.py
uv run python .\astra\tools\renderers.py
uv run python .\astra\tools\storage.py
uv run python .\astra\tools\devices.py --json
uv run python .\astra\tools\switch_profile.py "Naga" "Seige" --dry-run
uv run python .\astra\tools\switch_profile.py "Naga" "Seige"
```

## Tools

- `probe.py` — raw Node/Electron capability probe. Use first when an update breaks inspector integration.
- `renderers.py` — enumerate every Electron `webContents`, URL, and Razer `windowName`.
- `storage.py` — index or dump `connectedDeviceInfo` and `synapse_*` browser localStorage. `--shape` avoids dumping huge blobs.
- `devices.py` — normalized automatic device/profile discovery using the currently proven logic.
- `switch_profile.py` — exercise the exact internal software-profile switch path with optional `--dry-run` and verification.
- `eval.py` — arbitrary JavaScript in main or selected renderer. This is the escape hatch for new reverse engineering.
- `diagnostic_bundle.py` — emit one JSON snapshot containing inspector capabilities, renderer topology, normalized devices, and storage shapes. Add `--include-storage` only when full state is needed.
- `source_search.py` — literal/regex search across an extracted source directory or hunter ZIP.
- `hook_status.ps1` — machine-readable status of the IFEO inspector hook and port.
- `capture_stdio.ps1` — diagnostic relaunch of the versioned RazerAppEngine with inspector + stdout/stderr capture. It is intentionally not the normal launch path.

## Useful commands

```powershell
# Exact storage blob, decoded JSON
uv run python .\astra\tools\storage.py --key synapse_180

# Compact structure instead of 69 KB of JSON
uv run python .\astra\tools\storage.py --key synapse_180 --shape

# Inspect the profile stack
uv run python .\astra\tools\storage.py --key synapse_180_profiles_stack --shape

# Evaluate in the systray renderer
uv run python .\astra\tools\eval.py renderer "Object.keys(localStorage)" --name systray-left

# Evaluate in main process
uv run python .\astra\tools\eval.py main "process.versions"

# Search recovered source
uv run python .\astra\tools\source_search.py .\hunt-20260907-154320.zip switchProfileBySystray

# Create an LLM-friendly diagnostics file
uv run python .\astra\tools\diagnostic_bundle.py --out .\astra\diagnostics\snapshot.json

# Check automatic inspector hook
powershell -ExecutionPolicy Bypass -File .\astra\tools\hook_status.ps1

# Temporarily relaunch Synapse with stdio capture
powershell -ExecutionPolicy Bypass -File .\astra\tools\capture_stdio.ps1
```

`eval.py` and `switch_profile.py` can change live Synapse state. Do not expose these low-level diagnostics directly on a network API in the finished product.
