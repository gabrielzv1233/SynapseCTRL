# Documentation

Use this page as the map for SynapseCTRL documentation.

SynapseCTRL is published on **PyPI**. Installing it with `uv tool install synapsectrl` or `pip install synapsectrl` installs `synapsectrl` as a terminal command, so normal users can run commands such as `synapsectrl devices` and `synapsectrl hook install` globally without keeping a source checkout open.

## Start here

- [Getting Started](Getting-Started.md) — install from PyPI/source, required hook setup, first checks, first device/profile listing, and first switch
- [Setup & Advanced Options](Setup.md) — how the hook works, update behavior, alternate inspector ports, and uninstall details
- [Troubleshooting](Troubleshooting.md) — health checks, repair guidance, and diagnostic tooling

## Using SynapseCTRL

- [CLI & JSON](CLI.md) — terminal use, machine-readable output, hook management, scripting, and exit codes
- [Python SDK](Python-SDK.md) — `SynapseClient`, device/profile discovery, switching, and structured errors
- [API reference](API.md) — complete model and behavior reference

## Project internals

- [How it Works](Architecture.md) — Electron inspector, renderer discovery, profile state, switch path, and verification
- [Development](Development.md) — tests, live acceptance checks, packaging, and compatibility work
- [Publishing](Publishing.md) — manual PyPI release workflow and Trusted Publishing
- [Attribution](Attribution.md) — how downstream projects should credit SynapseCTRL

## What interface should I use?

| Goal | Recommended interface |
| --- | --- |
| Install the global CLI | `uv tool install synapsectrl` or `pip install synapsectrl` |
| Try SynapseCTRL manually | `synapsectrl ...` |
| Manage the Synapse hook | `synapsectrl hook install/status/repair/uninstall` |
| Stream Deck / PowerShell / Node / C# utility | CLI with `--json` |
| Python application | `SynapseClient` directly |
| High-frequency or persistent integration | Wrap `SynapseClient` in your own local service |
| Diagnose a Synapse update | `synapsectrl doctor` first, then `codex-stuff/tools` |

SynapseCTRL itself does not expose a network server. The public product interfaces are the Python SDK and CLI/JSON output.
