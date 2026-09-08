# Read this first, Astra

You are being handed a **working reverse-engineered control path**, not a blank investigation.

1. Read `ASTRA_SPEC.md` before changing architecture.
2. Read `KNOWN_FINDINGS.json` for machine-readable known-good observations.
3. Use `tools/` when you need live evidence. Do not recreate equivalent one-off probes unless a supplied tool cannot answer the question.
4. Treat `synapse_ctrl.py` in the parent project as the known-good behavioral reference until your implementation passes equivalent discovery/switch tests.
5. Build the polished developer-facing product yourself. The tools in this folder are intentionally diagnostics, not the intended final API.

First live check:

```powershell
uv run python .\astra\tools\probe.py
uv run python .\astra\tools\devices.py --json
```

If those are healthy, you already have everything needed to start implementing the product surface.
