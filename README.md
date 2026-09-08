# SynapseCTRL

[![PyPI](https://img.shields.io/pypi/v/synapsectrl?label=PyPI)](https://pypi.org/project/synapsectrl/)
[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/Windows-11%20%2F%2010-0078D4?logo=windows&logoColor=white)](https://github.com/gabrielzv1233/SynapseCTRL)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20the%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/gabrielzv1233)

Programmatic control for **Razer Synapse 4 software profiles** on Windows.

SynapseCTRL discovers connected devices, lists their software profiles, reports the active profile, and switches profiles through Synapse itself — without UI automation or fake clicks.

The source project is developed, dependency-managed, and built with [**uv**](https://docs.astral.sh/uv/). It is intentionally uv-first while still publishing as a normal Python package and command-line tool.

> **Important:** SynapseCTRL requires its Synapse inspector hook before device/profile control will work. Start with the [Getting Started guide](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/Getting-Started.md).

## Install

SynapseCTRL is published on **PyPI**. Installing it exposes the **SynapseCTRL CLI** as a terminal command, so normal usage does not require cloning the repository or running the project through Python manually.

For the CLI, an isolated [uv tool](https://docs.astral.sh/uv/guides/tools/) install is recommended:

```powershell
uv tool install synapsectrl
SynapseCTRL hook install
```

Standard pip installation also works:

```powershell
python -m pip install synapsectrl
SynapseCTRL hook install
```

After either install, commands are available directly from the terminal:

```powershell
SynapseCTRL --version
SynapseCTRL devices
```

Windows will request administrator elevation for the hook installer. Fully exit and reopen Razer Synapse afterward.

Python projects can add the SDK with:

```powershell
uv add synapsectrl
```

## What it can do

```powershell
SynapseCTRL devices
SynapseCTRL profiles "Naga"
SynapseCTRL switch "Naga" "Siege"
```

For other programs, every one-shot command also supports machine-readable JSON:

```powershell
SynapseCTRL devices --json
```

Python applications can use `SynapseClient` directly instead of spawning the CLI.

For high-frequency local integrations, SynapseCTRL also includes a persistent NDJSON stdio bridge:

```powershell
SynapseCTRL bridge --stdio
```

The bridge keeps one Synapse connection/state watcher alive and can emit profile/device/Synapse availability events. It is intended for applications that own the bridge as a child process, such as Stream Deck plugins.

## Optional HTTP / REST API

A conventional REST API is available as an **optional dependency**, so bridge-only users do not need to install a web stack.

Install it with:

```powershell
uv tool install "SynapseCTRL[http]"
```

or:

```powershell
python -m pip install "SynapseCTRL[http]"
```

Then run:

```powershell
SynapseCTRL serve
```

The default API listens only on:

```text
http://127.0.0.1:8765
```

It uses Starlette + Uvicorn and reuses the same persistent `SynapseService` core as bridge mode. See the [HTTP / REST API guide](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/HTTP.md) for endpoints and security guidance.

## Documentation

- **[Getting Started](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/Getting-Started.md)** — install the package and required hook, verify SynapseCTRL works, and make your first switch
- **[Documentation home](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/README.md)** — find setup, CLI, SDK, bridge, HTTP, architecture, troubleshooting, and developer references
- **[CLI & JSON](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/CLI.md)** — terminal use and one-shot scripting
- **[Persistent Bridge](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/Bridge.md)** — long-lived stdio protocol and events
- **[HTTP / REST API](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/HTTP.md)** — optional Starlette/Uvicorn server and endpoints
- **[Python SDK](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/Python-SDK.md)** — use SynapseCTRL directly from Python
- **[API reference](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/API.md)** — models, errors, selectors, and exact behavior
- **[Troubleshooting](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/Troubleshooting.md)** — `doctor`, update repair, and diagnostics

## Quick Python example

```python
from synapsectrl import SynapseClient

with SynapseClient() as synapse:
    devices = synapse.list_devices()
    for device in devices:
        print(device.name, device.active_profile_id)

    synapse.switch_profile("Naga", "Siege")
```

Use stable device IDs and profile GUIDs for unattended automation. Human-readable names are convenience selectors.

## Attribution and license

SynapseCTRL is licensed under the **Apache License 2.0** and ships with a `NOTICE` file so downstream distributions preserve project attribution as required by the license.

When integrating SynapseCTRL, it is also appreciated if your source or documentation mentions that Razer Synapse device/profile discovery and control is handled by **SynapseCTRL**. See [Attribution](https://github.com/gabrielzv1233/SynapseCTRL/blob/main/docs/Attribution.md).

## Project status

SynapseCTRL targets Razer Synapse 4 on Windows and relies on private Synapse/Electron interfaces discovered at runtime. Synapse updates can change those interfaces, so compatibility is capability-checked rather than tied to one fixed Synapse version.

This is an independent community project and is not affiliated with or endorsed by Razer.
