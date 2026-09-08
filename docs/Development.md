# Development

This page is for contributors and maintainers working on SynapseCTRL itself.

## Install development dependencies

```powershell
uv sync
```

## Run tests

```powershell
uv run python -m unittest discover -s tests -v
uv run python -m compileall -q src examples
uv run synapsectrl --help
powershell -NoProfile -ExecutionPolicy Bypass -File tests/test_installer.ps1
```

## Build distributions

```powershell
uv build
```

## Live acceptance tests

Read-only discovery equivalence:

```powershell
uv run python tests/live_synapse.py
```

Switch to another existing profile, verify it, and restore the starting profile:

```powershell
uv run python tests/live_synapse.py --switch-roundtrip
```

When more than one eligible device is connected, specify the stable device ID with `--device`.

Live switching changes actual Synapse configuration. The harness restores the starting profile in `finally`, but treat it as an integration test rather than a unit test.

## Compatibility work

If a Synapse update breaks the integration:

1. Run `synapsectrl doctor`.
2. Verify/repair the automatic inspector hook.
3. Run the investigation tools under `codex-stuff/tools`.
4. Compare renderer topology and storage shape with known findings.
5. Update discovery/protocol code only after observing the new behavior.
6. Add a regression test for the changed behavior.
7. Run a live switch-and-restore acceptance test before calling the change compatible.

The preserved `synapse_ctrl.py` remains a useful known-good behavioral reference from the original reverse-engineering work.

## Contribution expectations

Please keep the public SDK/CLI generic:

- do not hardcode one Razer product ID
- do not hardcode one profile GUID/name
- do not depend on a fixed renderer count
- do not replace software-profile switching with UI automation or onboard slot switching
- keep the inspector loopback-only
- keep diagnostic-only capabilities out of the normal public API

## License and attribution

Contributions to the project are accepted under the Apache License 2.0 unless explicitly stated otherwise.

Preserve `LICENSE`, `NOTICE`, and applicable source attribution. See [Attribution](Attribution.md).
