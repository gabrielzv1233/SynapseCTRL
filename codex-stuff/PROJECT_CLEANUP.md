# Current repo cleanup recommendation

Based on the project tree shown before this handoff.

## Keep at repo root

- `.gitignore`
- `.python-version`
- `pyproject.toml`
- `uv.lock`
- `README.md`
- `synapse_ctrl.py` — **keep for now as the known-good working reference implementation** until Astra has regression tests against the product it builds.
- `Install-SynapseInspectHook.ps1` — keep until Astra replaces bootstrap/install behavior with something demonstrably better.

## Add

Copy this entire `astra/` directory into the repo. It is explicitly a developer handoff/debug workspace and should not be shipped as the normal public API unless Astra intentionally promotes pieces of it.

## Can remove after verifying the IFEO hook

- `Start-SynapseDebug.ps1` — obsolete manual launch route.
- `razer-inspector-logs/` — old ad-hoc captured logs. Delete unless you want them as historical evidence; new diagnostic capture is timestamped under `astra/diagnostics/stdio/`.
- `synapse_inspector_probe.py` — superseded by `astra/tools/probe.py`.
- `Test-SynapseInspectHook.ps1` — superseded by `astra/tools/hook_status.ps1`; keeping it is harmless.

## Move/archive rather than delete if useful

If you still have these older reverse-engineering scripts from prior iterations, put them under something like `astra/legacy/` rather than letting Astra confuse them with current product code:

- `synapse_inspector.py`
- `synapse_trace.py`
- `synapse_source_hunter.py`
- old controller variants (`synapse_ctrl_v2.py`, etc.)
- old `Start-SynapseInspect*.ps1` launchers

The **current known-good reference** is the controller version that successfully listed the Naga, detected Fortnite active, and switched to Seige.

## Unknown file

- `synapse.af` — its purpose is not established from the folder screenshot. Do **not** delete it solely based on this handoff. Let Astra inspect it or remove it only if you know what generated it.

## `.venv`

Keep locally; it should normally remain ignored by Git.
