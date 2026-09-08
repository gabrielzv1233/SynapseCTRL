# SynapseCTRL

[![License](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/Python-3.13%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Windows](https://img.shields.io/badge/Windows-11%20%2F%2010-0078D4?logo=windows&logoColor=white)](https://github.com/gabrielzv1233/SynapseCTRL)
[![Ko-fi](https://img.shields.io/badge/Ko--fi-Support%20the%20project-FF5E5B?logo=ko-fi&logoColor=white)](https://ko-fi.com/gabrielzv1233)

Programmatic control for **Razer Synapse 4 software profiles** on Windows.

SynapseCTRL discovers connected devices, lists their software profiles, reports the active profile, and switches profiles through Synapse itself — without UI automation or fake clicks.

The source project is developed, dependency-managed, and built with [**uv**](https://docs.astral.sh/uv/). It is intentionally uv-first rather than relying on a legacy `setup.py` or manually managed virtual-environment workflow, while still using standard Python packaging metadata so normal package installation remains possible.

> **Important:** SynapseCTRL requires the included Synapse inspector hook before device/profile control will work. Start with the [Getting Started guide](docs/Getting-Started.md).

## What it can do

```powershell
uv run synapsectrl devices
uv run synapsectrl profiles "Naga"
uv run synapsectrl switch "Naga" "Siege"
```

For other programs, every command also supports machine-readable JSON:

```powershell
uv run synapsectrl devices --json
```

Python applications can use `SynapseClient` directly instead of spawning the CLI.

## Documentation

- **[Getting Started](docs/Getting-Started.md)** — install the required hook, verify SynapseCTRL works, and make your first switch
- **[Documentation home](docs/README.md)** — find setup, CLI, SDK, architecture, troubleshooting, and developer references
- **[CLI & JSON](docs/CLI.md)** — scripting and cross-language integrations
- **[Python SDK](docs/Python-SDK.md)** — use SynapseCTRL directly from Python
- **[API reference](docs/API.md)** — models, errors, selectors, and exact behavior
- **[Troubleshooting](docs/Troubleshooting.md)** — `doctor`, update repair, and diagnostics

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

When integrating SynapseCTRL, it is also appreciated if your source or documentation mentions that Razer Synapse device/profile discovery and control is handled by **SynapseCTRL**. See [Attribution](docs/Attribution.md).

## Project status

SynapseCTRL targets Razer Synapse 4 on Windows and relies on private Synapse/Electron interfaces discovered at runtime. Synapse updates can change those interfaces, so compatibility is capability-checked rather than tied to one fixed Synapse version.

This is an independent community project and is not affiliated with or endorsed by Razer.
