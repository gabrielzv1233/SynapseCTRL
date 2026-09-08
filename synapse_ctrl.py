import argparse
import json
import re
import time
import urllib.request

import websocket

HOST = "127.0.0.1"
PORT = 9229
DEVICE_KEY_RE = re.compile(r"^synapse_(\d+)$", re.I)
DEVICE_FAMILY_RE = re.compile(r"^synapse_(\d+)(?:_|$)", re.I)
ACTIVE_KEYS = {
    "activeprofile",
    "activeprofileguid",
    "currentprofile",
    "currentprofileguid",
    "selectedprofileguid",
}


class Inspector:
    def __init__(self, url):
        self.ws = websocket.create_connection(
            url,
            timeout=8,
            suppress_origin=True,
        )
        self.next_id = 1

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    def call(self, method, params=None):
        call_id = self.next_id
        self.next_id += 1

        self.ws.send(json.dumps({
            "id": call_id,
            "method": method,
            "params": params or {},
        }))

        while True:
            msg = json.loads(self.ws.recv())

            if msg.get("id") != call_id:
                continue

            if "error" in msg:
                raise RuntimeError(msg["error"])

            return msg.get("result", {})

    def eval(self, expression):
        result = self.call("Runtime.evaluate", {
            "expression": expression,
            "awaitPromise": True,
            "returnByValue": True,
        })

        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise RuntimeError(
                details.get("exception", {}).get("description")
                or details.get("text")
                or "JavaScript evaluation failed"
            )

        return result.get("result", {}).get("value")


def get_target(host, port):
    with urllib.request.urlopen(
        f"http://{host}:{port}/json/list",
        timeout=3,
    ) as response:
        targets = json.loads(response.read().decode("utf-8"))

    for target in targets:
        if target.get("webSocketDebuggerUrl"):
            return target

    raise RuntimeError("Inspector is listening but returned no target")


def get_renderer_state(inspector):
    expression = r'''
(async () => {
    const electron = process.mainModule.require("electron");
    const contents = electron.webContents.getAllWebContents();
    const windows = electron.BrowserWindow.getAllWindows();
    const renderers = [];

    for (const wc of contents) {
        if (!wc || wc.isDestroyed()) continue;

        try {
            const data = await wc.executeJavaScript(`
                (() => {
                    const keys = Object.keys(localStorage);
                    const values = {};

                    for (const key of keys) {
                        if (
                            key === "connectedDevices" ||
                            key === "connectedDeviceInfo" ||
                            key.startsWith("synapse_")
                        ) {
                            values[key] = localStorage.getItem(key);
                        }
                    }

                    return {
                        href: location.href,
                        title: document.title,
                        windowName:
                            window.apiElectron?.windowName ||
                            window.name ||
                            "",
                        keys,
                        values
                    };
                })()
            `, true);

            renderers.push({
                id: wc.id,
                type: wc.getType(),
                ...data
            });
        } catch (e) {
            renderers.push({
                id: wc.id,
                type: wc.getType(),
                error: String(e?.stack || e)
            });
        }
    }

    return JSON.stringify({
        pid: process.pid,
        processType: process.type,
        browserWindowCount: windows.length,
        webContentsCount: contents.length,
        renderers
    });
})()
'''

    raw = inspector.eval(expression)

    if not isinstance(raw, str):
        raise RuntimeError(f"Unexpected inspector result: {raw!r}")

    return json.loads(raw)


def parse_json(value):
    current = value

    for _ in range(6):
        if not isinstance(current, str):
            break

        try:
            current = json.loads(current)
        except json.JSONDecodeError:
            break

    return current


def walk(value):
    if isinstance(value, dict):
        yield value

        for child in value.values():
            yield from walk(child)

    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def recursive_value(obj, names):
    names = {name.casefold() for name in names}

    for item in walk(obj):
        for key, value in item.items():
            if key.casefold() in names and value not in (None, "", [], {}):
                return value

    return None


def extract_profiles(obj):
    best = []

    for item in walk(obj):
        profiles = item.get("profiles")

        if not isinstance(profiles, list):
            continue

        current = []

        for profile in profiles:
            if not isinstance(profile, dict):
                continue

            name = profile.get("name")
            guid = profile.get("guid") or profile.get("GUID") or profile.get("id")

            if name and guid:
                current.append({
                    "name": str(name),
                    "guid": str(guid),
                })

        if len(current) > len(best):
            best = current

    return best


def extract_active_profile(obj):
    for item in walk(obj):
        for key, value in item.items():
            if key.casefold() not in ACTIVE_KEYS:
                continue

            if isinstance(value, str):
                return value

            if isinstance(value, dict):
                guid = value.get("guid") or value.get("GUID") or value.get("id")

                if guid:
                    return str(guid)

    return ""


def get_device_name(obj, product_id):
    for item in walk(obj):
        for key in ("productName", "deviceName", "displayName", "editionName"):
            value = item.get(key)

            if isinstance(value, str) and value.strip():
                return value.strip()

            if isinstance(value, dict):
                for locale in ("en", "en-US", "en-us"):
                    text = value.get(locale)

                    if isinstance(text, str) and text.strip():
                        return text.strip()

    if str(product_id) == "180":
        return "Razer Naga V2 HyperSpeed"

    return f"Razer device PID {product_id}"



MIDDLEWARE_RE = re.compile(
    r"^(?:win-)?usb_(\d+)_(\d+)_(\{[0-9A-Fa-f-]+\})_mw$",
    re.I,
)


def find_middleware_identity(state, product_id):
    """Return the exact BroadcastChannel name + container ID from the MW renderer."""
    product_id = int(product_id)

    for renderer in state["renderers"]:
        name = str(renderer.get("windowName") or "")
        match = MIDDLEWARE_RE.match(name)

        if not match:
            continue

        _vendor_id, found_product_id, container_id = match.groups()

        try:
            if int(found_product_id) != product_id:
                continue
        except ValueError:
            continue

        return {
            "channel": name.removeprefix("win-"),
            "containerId": container_id,
        }

    for renderer in state["renderers"]:
        href = str(renderer.get("href") or "")
        match = re.search(
            rf"/products/{product_id}/mw/"
            r".*?[?&]containerId=%7B([0-9A-Fa-f-]+)%7D",
            href,
            re.I,
        )

        if match:
            container_id = "{" + match.group(1) + "}"
            return {
                "channel": (
                    f"usb_5426_{product_id}_{container_id}_mw"
                ),
                "containerId": container_id,
            }

    return {
        "channel": "",
        "containerId": "",
    }

def find_channel(state, product_id, container_id, obj):
    channel = recursive_value(obj, ("MWWindowName", "mwWindowName"))

    if isinstance(channel, str) and channel:
        return channel.removeprefix("win-")

    container_lower = container_id.casefold()

    for renderer in state["renderers"]:
        name = str(renderer.get("windowName") or "")
        href = str(renderer.get("href") or "")

        if container_lower in name.casefold() and name.casefold().endswith("_mw"):
            return name.removeprefix("win-")

        if (
            f"/products/{product_id}/mw/" in href.casefold()
            and container_id.strip("{}").casefold() in href.casefold()
        ):
            return f"usb_5426_{product_id}_{container_id}_mw"

    return f"usb_5426_{product_id}_{container_id}_mw"


def find_device_info(state, product_id):
    product_id = int(product_id)

    for renderer in state["renderers"]:
        raw = renderer.get("values", {}).get("connectedDeviceInfo")

        if raw is None:
            continue

        obj = parse_json(raw)

        if not isinstance(obj, (dict, list)):
            continue

        for item in walk(obj):
            value = item.get("productId")

            if value is None:
                value = item.get("productID")

            try:
                if int(value) == product_id:
                    return item
            except (TypeError, ValueError):
                pass

    return {}


def build_devices(state):
    storage = {}

    for renderer in state["renderers"]:
        values = renderer.get("values")

        if not isinstance(values, dict):
            continue

        for key, raw in values.items():
            if raw is not None and key not in storage:
                storage[key] = raw

    product_ids = set()

    for key in storage:
        match = DEVICE_FAMILY_RE.match(key)

        if match:
            product_ids.add(int(match.group(1)))

    devices = []

    for product_id in sorted(product_ids):
        prefix = f"synapse_{product_id}"
        family = []

        for key, raw in storage.items():
            if key == prefix or key.startswith(prefix + "_"):
                obj = parse_json(raw)

                if isinstance(obj, (dict, list)):
                    family.append((key, obj))

        if not family:
            continue

        profiles = []
        profile_source = ""
        active_profile = ""
        state_obj = None

        for key, obj in family:
            if key == prefix:
                state_obj = obj

            found = extract_profiles(obj)

            if len(found) > len(profiles):
                profiles = found
                profile_source = key

            if not active_profile:
                active_profile = extract_active_profile(obj)

        if not profiles:
            continue

        if state_obj is None:
            state_obj = family[0][1]

        info = find_device_info(state, product_id)
        middleware = find_middleware_identity(state, product_id)

        container_id = (
            middleware["containerId"]
            or str(
                info.get("containerId")
                or info.get("deviceContainerId")
                or recursive_value(
                    state_obj,
                    ("containerId", "deviceContainerId"),
                )
                or ""
            )
        )

        name_obj = info if info else state_obj
        name = get_device_name(name_obj, product_id)

        serial = str(
            info.get("serialNumber")
            or info.get("serialNo")
            or recursive_value(state_obj, ("serialNumber", "serialNo"))
            or ""
        )

        channel = (
            middleware["channel"]
            or (
                find_channel(
                    state,
                    product_id,
                    container_id,
                    state_obj,
                )
                if container_id
                else ""
            )
        )

        devices.append({
            "name": name,
            "productId": product_id,
            "containerId": container_id,
            "storageKey": prefix,
            "profileSource": profile_source,
            "profiles": profiles,
            "activeProfile": active_profile,
            "serialNumber": serial,
            "channel": channel,
        })

    return devices

def print_debug(state):
    print("\nInspector diagnostics:")
    print(f"  PID:             {state['pid']}")
    print(f"  process.type:    {state['processType']!r}")
    print(f"  BrowserWindows:  {state['browserWindowCount']}")
    print(f"  webContents:     {state['webContentsCount']}")

    print("\nRenderer/localStorage discovery:\n")

    for renderer in state["renderers"]:
        print(
            f"  wc={renderer['id']} "
            f"type={renderer.get('type')} "
            f"name={renderer.get('windowName')!r}"
        )

        if renderer.get("href"):
            print(f"      {renderer['href']}")

        if renderer.get("error"):
            print(f"      ERROR: {renderer['error']}")
            continue

        for key in renderer.get("keys", []):
            if (
                key in {"connectedDevices", "connectedDeviceInfo"}
                or key.startswith("synapse_")
            ):
                raw = renderer.get("values", {}).get(key)
                suffix = f" ({len(raw)} chars)" if isinstance(raw, str) else ""
                print(f"      {key}{suffix}")


def choose(items, title):
    print(f"\n{title}\n")

    for index, item in enumerate(items, 1):
        print(f"  {index}. {item}")

    while True:
        value = input("\nSelect: ").strip()

        if value.casefold() in {"q", "quit", "exit"}:
            raise KeyboardInterrupt

        try:
            index = int(value) - 1

            if 0 <= index < len(items):
                return index
        except ValueError:
            pass

        print("Invalid selection.")


def find_by_name(items, query):
    exact = [
        item
        for item in items
        if item["name"].casefold() == query.casefold()
    ]

    if exact:
        return exact[0]

    partial = [
        item
        for item in items
        if query.casefold() in item["name"].casefold()
    ]

    return partial[0] if partial else None


def switch_profile(inspector, device, profile):
    template = r'''
(async () => {
    const electron = process.mainModule.require("electron");
    const contents = electron.webContents.getAllWebContents();
    let target = null;

    for (const wc of contents) {
        if (!wc || wc.isDestroyed()) continue;

        try {
            const info = await wc.executeJavaScript(`
                (() => ({
                    href: location.href,
                    windowName:
                        window.apiElectron?.windowName ||
                        window.name ||
                        ""
                }))()
            `, true);

            if (
                info.windowName === "systray-left" ||
                String(info.href).includes("/systray/systrayv2/")
            ) {
                target = wc;
                break;
            }

            if (
                !target &&
                String(info.href).startsWith("https://apps.razer.com/")
            ) {
                target = wc;
            }
        } catch {}
    }

    if (!target) {
        throw new Error("No Razer renderer was found");
    }

    return await target.executeJavaScript(`
        (async () => {
            const bc = new BroadcastChannel(__CHANNEL__);

            bc.postMessage({
                type: "ON_SWITCH_PROFILE",
                payload: {
                    newActiveProfileGUID: __PROFILE_GUID__,
                    deviceContainerId: __CONTAINER_ID__
                }
            });

            bc.postMessage({
                msgName: "crossPageRequest",
                msgData: {
                    action: "switchProfileBySystray",
                    selectedProfileGuid: __PROFILE_GUID__,
                    deviceContainerId: __CONTAINER_ID__
                }
            });

            await new Promise(resolve => setTimeout(resolve, 250));
            bc.close();

            return JSON.stringify({
                sent: true,
                href: location.href,
                windowName:
                    window.apiElectron?.windowName ||
                    window.name ||
                    ""
            });
        })()
    `, true);
})()
'''

    expression = (
        template
        .replace("__CHANNEL__", json.dumps(device["channel"]))
        .replace("__PROFILE_GUID__", json.dumps(profile["guid"]))
        .replace("__CONTAINER_ID__", json.dumps(device["containerId"]))
    )

    raw = inspector.eval(expression)

    if isinstance(raw, str):
        return json.loads(raw)

    return raw or {}


def main():
    parser = argparse.ArgumentParser(
        description="Control Razer Synapse 4 software profiles."
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    parser.add_argument("--device")
    parser.add_argument("--profile")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--debug-storage", action="store_true")
    args = parser.parse_args()

    inspector = None

    try:
        print("Connecting to Razer Synapse 4 main process...")

        target = get_target(args.host, args.port)
        inspector = Inspector(target["webSocketDebuggerUrl"])
        inspector.call("Runtime.enable")

        state = get_renderer_state(inspector)

        if args.debug_storage:
            print_debug(state)

        devices = build_devices(state)

        if not devices:
            print("\nNo Synapse profile-capable devices were parsed.")
            return 1

        if args.list:
            for device in devices:
                print(f"\n{device['name']}")
                print(f"  channel:   {device['channel']}")
                print(f"  container: {device['containerId']}")
                print(f"  storage:   {device['storageKey']}")
                print(f"  profiles:  {device['profileSource']}")

                for profile in device["profiles"]:
                    active = (
                        " *"
                        if profile["guid"] == device["activeProfile"]
                        else ""
                    )

                    print(
                        f"  - {profile['name']} "
                        f"[{profile['guid']}]{active}"
                    )

            return 0

        if args.device:
            device = find_by_name(devices, args.device)

            if not device:
                print(f'No device matching "{args.device}".')
                return 1
        else:
            device = devices[
                choose(
                    [
                        device["name"]
                        + (
                            f" ({device['serialNumber']})"
                            if device["serialNumber"]
                            else ""
                        )
                        for device in devices
                    ],
                    "Razer devices",
                )
            ]

        profiles = sorted(
            device["profiles"],
            key=lambda profile: profile["name"].casefold(),
        )

        if args.profile:
            profile = find_by_name(profiles, args.profile)

            if not profile:
                print(
                    f'No profile matching "{args.profile}" '
                    f'on {device["name"]}.'
                )
                return 1
        else:
            profile = profiles[
                choose(
                    [
                        profile["name"]
                        + (
                            " [ACTIVE]"
                            if profile["guid"] == device["activeProfile"]
                            else ""
                        )
                        for profile in profiles
                    ],
                    f"{device['name']} profiles",
                )
            ]

        if (
            device["activeProfile"]
            and profile["guid"] == device["activeProfile"]
        ):
            print(f"\nAlready active: {profile['name']}")
            return 0

        print(f"\nSwitching to {profile['name']}...")
        result = switch_profile(inspector, device, profile)

        if not result.get("sent"):
            print("Synapse did not confirm sending the switch event.")
            return 1

        print(
            f"Switch event sent through {result.get('windowName')!r} "
            f"({result.get('href')})"
        )

        for _ in range(12):
            time.sleep(0.25)
            refreshed = build_devices(get_renderer_state(inspector))
            current = next(
                (
                    item
                    for item in refreshed
                    if (
                        item["containerId"].casefold()
                        == device["containerId"].casefold()
                    )
                ),
                None,
            )

            if (
                current
                and current["activeProfile"]
                and current["activeProfile"] == profile["guid"]
            ):
                print(f"Switched to profile: {profile['name']}")
                return 0

        print(
            f"Switch event sent for profile: {profile['name']}. "
            "Synapse did not expose a recognized active-profile field "
            "for verification."
        )
        return 0

    except KeyboardInterrupt:
        print("\nCancelled.")
        return 130
    except Exception as error:
        print(f"\nError: {error}")
        return 1
    finally:
        if inspector:
            inspector.close()


if __name__ == "__main__":
    raise SystemExit(main())
