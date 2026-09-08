# Setup & Advanced Options

This page covers the Windows bootstrap that makes SynapseCTRL available whenever Razer Synapse starts.

For the shortest setup path, use [Getting Started](Getting-Started.md).

## Why the hook is required

SynapseCTRL controls Synapse through the Razer App Engine's Electron browser process. The product needs a localhost-only Node inspector exposed by that process so it can discover renderers, read current software-profile state, and dispatch the same internal switch messages Synapse uses.

Normal Synapse launches do not expose that inspector, so SynapseCTRL ships the `Install-SynapseInspectHook.ps1` installer inside the Python package and source repository.

## Installing

For normal installed use:

```powershell
synapsectrl hook install
```

From a source checkout:

```powershell
uv run synapsectrl hook install
```

The CLI runs the packaged PowerShell installer and requests administrator elevation because it installs a filtered Windows Image File Execution Options (IFEO) entry and a small launch shim under Program Files.

The original script can still be invoked directly when debugging installer behavior:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-SynapseInspectHook.ps1 -NoPause
```

The hook targets the stable launcher:

```text
C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe
```

The shim locates the newest versioned App Engine executable under an `app-*` directory and starts it with:

```text
--inspect=127.0.0.1:9229
```

The inspector is intentionally loopback-only.

## After installation

The installer does not need to run before each profile switch.

After installing or repairing the hook:

1. Fully exit Synapse from the tray.
2. Reopen Synapse normally.
3. Run:

```powershell
synapsectrl hook status
synapsectrl doctor
```

## Synapse updates

The current shim searches for the newest versioned `app-*` Razer App Engine directory, so ordinary version-folder changes should continue to work automatically.

> **Razer may change its launch path or private Electron behavior in an update. If `synapsectrl doctor` or `synapsectrl hook status` reports the hook as missing/unhealthy after an update, run `synapsectrl hook repair`, then fully restart Synapse.**

Do not assume that a successful hook install guarantees compatibility with every future Synapse release; `doctor` separately tests the live inspector and required capabilities.

## Repairing

The normal repair command is:

```powershell
synapsectrl hook repair
```

`repair` uses the same packaged installer as `install`; the separate command makes the intent clearer for troubleshooting and automation.

## Alternate inspector port

The Python client supports another local port through `--port` or the `SynapseClient(port=...)` constructor, but the shipped hook currently installs the normal inspector at port `9229`.

If you deliberately customize the hook, make sure the client and launcher agree on the same loopback port.

## Uninstalling

Remove the automatic launch hook with:

```powershell
synapsectrl hook uninstall
```

Manual source-script equivalent:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\Install-SynapseInspectHook.ps1 -Uninstall -NoPause
```

Then fully exit and reopen Synapse.

Removing the hook does not retroactively remove the inspector from an already-running Razer App Engine process. It changes future launches.

## Security boundary

The Node inspector is powerful: it can execute code inside the Synapse Electron browser process.

SynapseCTRL therefore requires loopback and does not expose a remote HTTP service or arbitrary evaluation through its normal SDK/CLI.

Do not change the inspector host to a LAN/public interface. If you build a remote-control service around SynapseCTRL, expose your own authenticated application-level API and keep the underlying inspector on `127.0.0.1`.

## Verifying the endpoint directly

For debugging only:

```powershell
Invoke-RestMethod http://127.0.0.1:9229/json/list
```

The normal product check is still:

```powershell
synapsectrl doctor
```

because it checks more than whether a TCP endpoint exists.
