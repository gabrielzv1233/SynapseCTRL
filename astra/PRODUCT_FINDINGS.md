# Product acceptance findings — 2026-09-07

The original `synapse_ctrl.py` is preserved byte-for-byte. The production package
uses the same two-message Synapse software-profile path, with independent
normalization, scoped active-state verification, and a private inspector adapter.

## Supplied diagnostics repair

`tools/_synapse.py` generated renderer code containing `if (includeValues)`, but
that variable existed only in the Electron main-process script. All renderer
reads failed. Inlining the existing boolean into the generated renderer script
restored the supplied diagnostics. No replacement probe was needed.

## Active state and stale profile stacks

Live inspection found `synapse_<productId>_profiles_stack` could retain a previous
active GUID while `synapse_<productId>.activeProfile` and the connected device's
`deviceMetadatas[serial].activeProfileGuid` agreed on the current GUID. The
preserved prototype chooses the first active field in storage-family iteration
order, so its final device model can report that stale stack value.

Evidence came from the supplied `storage.py --key ... --shape`, `devices.py`,
and the reference controller's renderer reads. The product pairs the active
field with the current profile document; a separate stack does not override it.
Fixture tests cover this ordering and conflicting state variants.

The live harness compares names and GUIDs against the reference model and
verifies active state by applying the reference parser directly to its selected
profile source. It records both the legacy family result and the source result
so the distinction remains visible. It does not change the reference parser to
make equivalence appear exact.

## Live acceptance

On the observed Razer Naga V2 Hyperspeed with six software profiles, running
App Engine 4.0.699 / Electron 30.2.0 / Chrome 124.0.6367.243 / Node 20.15.0:

- Device identity and all profile names/GUIDs matched the preserved reference.
- The SDK switched to a different existing profile and verified fresh state.
- An independent reference storage read confirmed the target GUID.
- A repeated switch returned `already_active`, without dispatching.
- Closing and reconnecting rediscovered the same device and active profile.
- The CLI switched back to the profile active at the start of the test.
- The reference storage read independently confirmed restoration.

The existing automatic launch hook was inspected and is healthy. The revised
installer and embedded native shim passed offline PowerShell tests, including
compilation as a GUI executable, argument parsing, loopback enforcement, numeric
version discovery, conflict checks, and conservative uninstall. The revised
installer has not replaced the currently installed Program Files shim or changed
the live registry; its hardening applies when installed.

Multiple-device behavior, ambiguous identical products, transport failures, and
timeouts are fixture-tested. Only the connected Naga was available for physical
acceptance. Verification measures Synapse's exposed active state; it does not
independently measure device mappings or simulate a future Synapse update.

Machine-specific reports remain ignored under `astra/diagnostics/`; no full
storage snapshots or captured serial numbers are included in product releases.
