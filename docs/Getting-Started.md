# Getting Started

SynapseCTRL needs one Windows-side setup step before it can read or control Razer Synapse 4 profiles: **install the Synapse inspector hook**.

## Uninstall / remove the hook

If you are here to remove SynapseCTRL's automatic Synapse hook:

```powershell
synapsectrl hook uninstall
```

Then fully exit Synapse from the tray and reopen it normally. See [Setup & Advanced Options](Setup.md#uninstalling) for details.

---

## 1. Install SynapseCTRL

SynapseCTRL is available as a package on **PyPI**. Installing the package also installs `synapsectrl` as a command you can call directly from your terminal, so you do not need to run the project through `python` or keep a source checkout around.

For normal CLI use, installing SynapseCTRL as an isolated [**uv**](https://docs.astral.sh/uv/) tool is recommended:

```powershell
uv tool install synapsectrl
```

If you do not already have uv, use the [official uv installation instructions](https://docs.astral.sh/uv/getting-started/installation/).

Standard pip installation also works:

```powershell
python -m pip install synapsectrl
```

After either install, this should work from a normal terminal:

```powershell
synapsectrl --version
```

SynapseCTRL currently requires Windows and Python 3.13+.

### Working from a source checkout

SynapseCTRL itself is an uv-first project. Contributors should use the included `pyproject.toml` and `uv.lock` rather than creating a separate legacy requirements/setup workflow:

```powershell
uv sync
```

When following the commands below from a checkout without installing the CLI globally, prefix them with `uv run`, for example:

```powershell
uv run synapsectrl devices
```

## 2. REQUIRED: install the Synapse inspector hook

Run:

```powershell
synapsectrl hook install
```

Windows will request administrator elevation. The CLI runs the hook installer bundled inside the SynapseCTRL package and configures normal Razer Synapse launches so the Razer App Engine browser process starts with a localhost-only Node inspector.

If you are working directly from a source checkout, use:

```powershell
uv run synapsectrl hook install
```

The raw PowerShell installer remains in the repository for development and manual fallback, but normal users should use the `synapsectrl hook ...` commands. See [Setup & Advanced Options](Setup.md) for those lower-level details.

After the installer completes:

1. Fully exit Razer Synapse from its tray menu.
2. Launch Razer Synapse normally.
3. Continue with the checks below.

> **After Razer Synapse updates, you may need to run `synapsectrl hook repair` if `synapsectrl doctor` or `synapsectrl hook status` reports that the automatic hook is missing or unhealthy.** The current shim automatically locates the newest `app-*` Razer App Engine directory, so a version-folder change alone normally does not require reinstalling the hook.

## 3. Check the hook and connection

Check the installed launch hook:

```powershell
synapsectrl hook status
```

Then check SynapseCTRL itself:

```powershell
synapsectrl status
```

For the most useful setup check, run:

```powershell
synapsectrl doctor
```

A healthy setup should report `ready` and show a reachable inspector plus discovered device information.

## 4. List your devices

```powershell
synapsectrl devices
```

Example shape:

```text
Razer Naga V2 Hyperspeed
  id: razer:5426:180:...
  active profile: ...
```

Do not copy example IDs from documentation. Use the IDs reported by your own installation.

## 5. List profiles for a device

Human-readable names work when they are unambiguous:

```powershell
synapsectrl profiles "Naga"
```

You will get the software profiles SynapseCTRL discovered for that device, including GUIDs and the active marker.

## 6. Switch a profile

Try a profile that actually exists on your device:

```powershell
synapsectrl switch "Naga" "Siege"
```

For unattended automation, prefer the stable device ID and profile GUID returned by discovery:

```powershell
synapsectrl switch "DEVICE_ID_FROM_DISCOVERY" "PROFILE_GUID"
```

By default, SynapseCTRL sends the switch through Synapse and then verifies that Synapse reports the requested profile as active.

## 7. Try JSON output

Anything that needs to consume SynapseCTRL programmatically should use `--json` instead of parsing human-readable terminal output:

```powershell
synapsectrl devices --json
synapsectrl profiles "Naga" --json
synapsectrl switch "Naga" "Siege" --json
```

Successful output is a single JSON object with `apiVersion: "1"` and `data`. Errors use the same envelope with an `error` object.

## Where next?

- [CLI & JSON](CLI.md) for scripting and other languages
- [Python SDK](Python-SDK.md) for direct Python integration
- [API reference](API.md) for exact models and errors
- [Troubleshooting](Troubleshooting.md) if any command above fails
- [How it Works](Architecture.md) if you want the technical internals
