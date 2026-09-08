# How SynapseCTRL Works

SynapseCTRL controls **Synapse software profiles**, not onboard hardware profile slots.

## High-level flow

```text
SynapseCTRL SDK / CLI
        ↓
localhost Node inspector
        ↓
Razer App Engine Electron browser process
        ↓
Synapse renderer state + middleware renderer
        ↓
Synapse internal profile-switch messages
        ↓
Synapse mapping engine
        ↓
Razer device configuration
```

## Inspector bootstrap

The included Windows installer configures normal Razer App Engine launches to include:

```text
--inspect=127.0.0.1:9229
```

The inspector remains local-only. See [Setup & Advanced Options](Setup.md).

## Electron access

The inspector is attached to the Electron browser process. On the observed Razer build, the proven Electron import path is:

```javascript
process.mainModule.require("electron")
```

SynapseCTRL uses Electron's web contents to inspect current renderers and state.

## Device and profile discovery

Synapse exposes renderer-local state such as:

```text
connectedDeviceInfo
synapse_<PRODUCT_ID>
synapse_<PRODUCT_ID>_profiles_stack
```

SynapseCTRL normalizes this into public `Device` and `Profile` models.

Middleware renderer identities also expose routing information in forms like:

```text
usb_<VENDOR_ID>_<PRODUCT_ID>_<CONTAINER_ID>_mw
```

The public API intentionally hides these private implementation details behind stable device IDs and profile GUIDs.

## Switching

SynapseCTRL dispatches the same internal profile-switch path discovered in Synapse's own systray code. It does not automate the Synapse UI.

After dispatch, the normal switch path refreshes current state until the requested profile is observed as active or the verification deadline expires.

## Verification boundary

`verified` means Synapse's exposed active-profile state reports the target GUID.

It does **not** independently interrogate physical mouse/keyboard firmware to prove every setting has already reached hardware.

## Compatibility

These are private Synapse interfaces, so Razer can change them without notice.

SynapseCTRL therefore probes capabilities and exposes `status` / `doctor` diagnostics instead of assuming one exact Synapse version or renderer count forever.

The deeper reverse-engineering workbench under `codex-stuff/tools` exists for investigating future breakage without rebuilding one-off probes from scratch.
