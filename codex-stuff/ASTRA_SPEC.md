# SynapseCTRL — Astra Engineering Handoff

## Purpose

Build the polished **product**, not another reverse-engineering prototype.

The product should give third-party developers a stable local interface for:

1. discovering supported Razer Synapse 4 devices,
2. returning durable machine identifiers plus readable names,
3. listing each device's **software** profiles and active profile,
4. switching software profiles through Synapse itself,
5. automatically discovering all required internal identifiers on startup,
6. recovering/re-diagnosing when Synapse changes after an update.

No normal user/developer workflow should require knowing Electron renderer names, localStorage keys, profile GUID lookup mechanics, container IDs, or BroadcastChannel message formats. Those are implementation details behind the public contract.

## Proven reverse-engineered path

The following path has been successfully exercised end-to-end:

```text
external controller
  -> Node/V8 inspector on RazerAppEngine browser process
  -> Electron API via process.mainModule.require("electron")
  -> enumerate electron.webContents
  -> apps.razer.com renderer localStorage for discovery/state
  -> systray-left renderer
  -> device middleware BroadcastChannel
  -> ON_SWITCH_PROFILE + switchProfileBySystray
  -> Synapse mapping engine
  -> physical device configuration changes
```

This is **not UI automation** and does not switch an onboard hardware profile slot. It invokes Synapse's own software-profile switching path.

## Inspector facts

Observed working application:

- RazerAppEngine: `4.0.699`
- Electron: `30.2.0`
- Chrome: `124.0.6367.243`
- Node: `20.15.0`
- Launch flag: `--inspect=127.0.0.1:9229`
- `/json/list` target type: `node`
- target title: `electron/js2c/browser_init`
- `process.type`: `browser`
- `typeof require`: `undefined`
- **working Electron import:** `process.mainModule.require("electron")`
- `process.getBuiltinModule`: unavailable on observed build

Do not regress to `require("electron")` without capability probing first.

Observed instance had 7 `BrowserWindow`s and 8 `webContents`, but **counts must never be hardcoded**.

## Renderer topology

Important observed renderer names/URLs include:

- `systray-left` -> `https://apps.razer.com/systray/systrayv2/`
- `synapse` -> `https://apps.razer.com/synapse/dashboard/`
- `gms-proxy`
- `lighting-engine`
- `notification-manager`
- `background-manager`
- per-device middleware renderer such as:
  `usb_5426_180_{D37A42A5-5C38-5315-B3F0-EA3604C652EF}_mw`
- device middleware URL:
  `https://apps.razer.com/synapse/products/180/mw/index.html?containerId=...`

Preload exposes `window.apiElectron`; its `windowName` is useful for identifying renderers. The switching path itself only needs a renderer on the correct origin plus `BroadcastChannel`.

## Device identity

Middleware renderer names expose device identity in this observed form:

```text
usb_<vendorId>_<productId>_<containerId>_mw
```

Example:

```text
usb_5426_180_{D37A42A5-5C38-5315-B3F0-EA3604C652EF}_mw
```

This is currently the most reliable source for:

- vendor ID,
- product ID,
- container ID,
- exact middleware BroadcastChannel name.

`connectedDeviceInfo` should be used to enrich the model with names/serial/device metadata where available, but do not make switching depend on it when the middleware renderer already provides the identifiers.

The final implementation must support multiple devices and must not hardcode product ID 180 or vendor ID 5426.

## Browser storage layout

All observed `apps.razer.com` renderers shared relevant localStorage state. Important keys included:

```text
connectedDeviceInfo
synapse_180
synapse_180_profiles_stack
synapse_wdl
```

The large `synapse_180` state blob was approximately 69 KB in the observed run and contained named software profiles and active-profile state.

### Critical distinction

Native mapping-engine logs showed writes to:

```text
synapse_180_{D37A42A5-5C38-5315-B3F0-EA3604C652EF}
```

That is **not the browser localStorage key**. Browser localStorage used `synapse_180`.

Do not conflate those two storage layers again.

## Profile schema

Observed profile records include at least:

```json
{
  "name": "Seige",
  "guid": "ec860d8c-8582-4606-b5ef-1bacff85481b"
}
```

Discovery code should tolerate minor schema movement by recursively locating candidate `profiles` arrays and selecting the strongest list of `{name, guid}` records. The current debug tools implement this fallback behavior.

Observed active-profile state can be found under a field equivalent to `activeProfile`; the debugging library searches several common variants.

The public API should expose both readable names and GUIDs. GUID is the preferred stable profile identifier.

## Exact proven switch protocol

The systray implementation sends **both** messages on the device middleware BroadcastChannel.

```js
const bc = new BroadcastChannel(device.MWWindowName);

bc.postMessage({
  type: "ON_SWITCH_PROFILE",
  payload: {
    newActiveProfileGUID: profileGuid,
    deviceContainerId
  }
});

bc.postMessage({
  msgName: "crossPageRequest",
  msgData: {
    action: "switchProfileBySystray",
    selectedProfileGuid: profileGuid,
    deviceContainerId
  }
});

bc.close();
```

Observed completion event from recovered Synapse code/logging:

```json
{
  "actionType": "taskMakerSwitchProfile",
  "status": "completed",
  "value": {
    "oldActiveProfile": "<old-guid>",
    "newActiveProfileGUID": "<new-guid>",
    "version": 8602
  }
}
```

The working prototype verifies success by rereading discovered state and waiting for the active-profile GUID to become the target.

## Recovered internal task behavior

Recovered `taskMakerSwitchProfile` logic indicates Synapse performs more than a simple UI state change. It updates active profile data, invokes mapping-engine current-profile logic, persists settings, applies differences to the device, then dispatches completion state.

This is why the product should continue to invoke the Synapse software path rather than writing arbitrary hardware profile slots.

## Automatic inspector launch

Current project includes `Install-SynapseInspectHook.ps1`, which installs a filtered Windows IFEO hook on the stable launcher:

```text
C:\Program Files\Razer\RazerAppEngine\RazerAppEngine.exe
```

The shim finds the newest versioned `app-*\RazerAppEngine.exe` and adds:

```text
--inspect=127.0.0.1:9229
```

The final product may redesign this bootstrap, but it must preserve these requirements:

- normal Synapse launch should automatically include a local inspector,
- no user should manually run a debug launcher after installation,
- handle Razer versioned `app-*` directories changing after updates,
- detect inspector failure and report a useful repair state,
- bind inspector to loopback only.

## Product contract Astra should build

The exact implementation is Astra's job. The minimum developer-facing behavior should include:

### Device discovery

Return every supported discovered Synapse device with at least:

```json
{
  "id": "stable normalized identifier",
  "name": "Razer Naga V2 Hyperspeed",
  "vendorId": 5426,
  "productId": 180,
  "containerId": "{...}",
  "serialNumber": "... if available",
  "connected": true,
  "profilesSupported": true
}
```

Do not expose `channel` as a required public input. It is internal diagnostic metadata.

### Profile listing

Return at least:

```json
{
  "id": "ec860d8c-8582-4606-b5ef-1bacff85481b",
  "name": "Seige",
  "active": true
}
```

### Switching

Allow selecting device/profile by stable IDs. Human names may be convenience aliases, but ambiguous fuzzy matches must not silently choose the wrong target.

A successful switch should distinguish:

- request accepted/sent,
- verified active state,
- timeout/failure,
- already active.

### Status/diagnostics

Expose enough diagnostic state to answer:

- Is Synapse running?
- Is inspector reachable?
- Is this the Electron browser process?
- Can Electron API be imported?
- How many renderers exist?
- Which device middleware renderers were discovered?
- Which storage keys were discovered?
- Why is a device/profile not currently controllable?

The finished product should keep arbitrary JS evaluation and full state dumping in a **developer/diagnostic interface**, not the normal public surface.

## Requirements for resilience

On every startup/reconnect:

1. capability-probe the inspector instead of trusting version numbers,
2. enumerate renderers dynamically,
3. enumerate device middleware renderers dynamically,
4. enumerate `synapse_<productId>*` storage families dynamically,
5. enrich with `connectedDeviceInfo` when possible,
6. build normalized device/profile models,
7. verify active-profile state,
8. never depend on observed renderer counts, product 180, or the observed container GUID,
9. keep exact raw identifiers available in diagnostics,
10. fail closed on ambiguous device/profile resolution.

## Security boundary

The Node inspector is effectively code execution inside Synapse. Keep it bound to `127.0.0.1` only.

The finished product should not expose raw inspector WebSocket access or arbitrary eval over an unauthenticated network endpoint. If a local HTTP interface is created, restrict it to loopback and design an authentication/authorization boundary before allowing mutation operations.

## Known-good observed values — examples only

Device:

- name: `Razer Naga V2 Hyperspeed`
- vendorId: `5426`
- productId: `180`
- containerId: `{D37A42A5-5C38-5315-B3F0-EA3604C652EF}`

Profiles:

- Fortnite -> `ed7bdfb2-8fd1-4ed5-862a-4999f3c2d31a`
- Wyatt -> `57915002-f5e2-4e47-bfb4-ea3cd2ee7a49`
- Seige -> `ec860d8c-8582-4606-b5ef-1bacff85481b`
- Satisfactory -> `11f5937c-f1af-4a0f-8a02-8d801c1319bc`
- GABRIELSNEWPC-Default -> `7ef5597f-bfda-476c-998c-bd9126450aa1`
- GABRIELSNEWPC-Default (1) -> `f577fd9f-8da3-4df0-b9b0-7bb58dcc45d3`

These values prove behavior. They are **test fixtures/examples, not implementation constants**.

## Known traps already encountered

Do not waste context repeating these mistakes:

1. **UI automation is the wrong layer.** It also previously falsely matched an unrelated VS Code title.
2. Naga onboard slot switching is not equivalent to Synapse software-profile switching.
3. Chromium renderer remote-debugging was not the reliable route used in the final proof.
4. Node main-process inspector works, but `require` is undefined in the inspector console context.
5. Use `process.mainModule.require("electron")` on the proven build.
6. `connectedDevices` is not required and was an unreliable assumption.
7. Browser storage uses `synapse_<productId>`; the native mapping-engine key may append the container ID.
8. Do not derive container/channel from `connectedDeviceInfo` when the middleware renderer name already supplies both.
9. Opening `https://apps.razer.com/synapse/dashboard/` in an ordinary browser is not equivalent to a functional Synapse page because the Electron preload/backend is missing.

## How Astra should use the supplied tools

Before changing the product after a Synapse update, run:

```powershell
uv run python .\astra\tools\probe.py
uv run python .\astra\tools\renderers.py
uv run python .\astra\tools\devices.py --json
uv run python .\astra\tools\diagnostic_bundle.py --out .\astra\diagnostics\snapshot.json
```

If discovery breaks:

```powershell
uv run python .\astra\tools\storage.py --contains synapse_
uv run python .\astra\tools\storage.py --key <interesting-key> --shape
```

If a new internal action must be investigated:

```powershell
uv run python .\astra\tools\eval.py main "..."
uv run python .\astra\tools\eval.py renderer "..." --name systray-left
uv run python .\astra\tools\source_search.py <source-tree-or-hunter.zip> <literal-or-regex>
```

If logs are needed:

```powershell
powershell -ExecutionPolicy Bypass -File .\astra\tools\capture_stdio.ps1
```

Then reproduce the behavior and inspect the generated timestamped stdout/stderr logs.
