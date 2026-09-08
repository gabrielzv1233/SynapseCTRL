# Documentation

Use this page as the map for SynapseCTRL documentation.

SynapseCTRL is published on **PyPI**. Installing it with `uv tool install synapsectrl` or `pip install synapsectrl` installs the **SynapseCTRL CLI** as a terminal command, so normal users can run commands such as `SynapseCTRL devices` and `SynapseCTRL hook install` globally without keeping a source checkout open.

## Start here

- [Getting Started](Getting-Started.md) — install from PyPI/source, required hook setup, first checks, first device/profile listing, and first switch
- [Setup & Advanced Options](Setup.md) — how the hook works, update behavior, alternate inspector ports, and uninstall details
- [Troubleshooting](Troubleshooting.md) — health checks, repair guidance, and diagnostic tooling

## Using SynapseCTRL

- [CLI & JSON](CLI.md) — terminal use, machine-readable output, hook management, scripting, and exit codes
- [Persistent Bridge](Bridge.md) — long-lived NDJSON stdio protocol, state watching, events, and child-process ownership
- [HTTP / REST API](HTTP.md) — optional Starlette/Uvicorn REST server, live Server-Sent Events, installation, and security guidance
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
| Try SynapseCTRL manually | `SynapseCTRL ...` |
| Manage the Synapse hook | `SynapseCTRL hook install/status/repair/uninstall` |
| One-shot PowerShell / Node / C# automation | CLI with `--json` |
| Stream Deck or other owned high-frequency local process | `SynapseCTRL bridge --stdio` |
| Conventional REST integration | `SynapseCTRL serve` with `SynapseCTRL[http]` installed |
| Shared live HTTP state/events | `GET /v1/events` on `SynapseCTRL serve` |
| Python application | `SynapseClient` directly |
| Build a custom persistent Python service | `SynapseService` or `SynapseClient` directly |
| Diagnose a Synapse update | `SynapseCTRL doctor` first, then `codex-stuff/tools` |

Both long-lived transports reuse the same persistent service core. Bridge mode is private stdio intended to be owned by another local process; HTTP mode is an optional network listener for conventional REST clients and SSE subscribers.
