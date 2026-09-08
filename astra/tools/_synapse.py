from __future__ import annotations

import json
import re
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from typing import Any, Iterable

import websocket

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 9229

DEVICE_FAMILY_RE = re.compile(r"^synapse_(\d+)(?:_|$)", re.I)
MIDDLEWARE_RE = re.compile(
    r"^(?:win-)?usb_(\d+)_(\d+)_(\{[0-9A-Fa-f-]+\})_mw$",
    re.I,
)
ACTIVE_KEYS = {
    "activeprofile",
    "activeprofileguid",
    "currentprofile",
    "currentprofileguid",
    "selectedprofileguid",
}


class SynapseError(RuntimeError):
    pass


@dataclass
class InspectorTarget:
    raw: dict[str, Any]

    @property
    def websocket_url(self) -> str:
        return str(self.raw["webSocketDebuggerUrl"])


class Inspector:
    def __init__(self, websocket_url: str, timeout: float = 8.0):
        self.ws = websocket.create_connection(
            websocket_url,
            timeout=timeout,
            suppress_origin=True,
        )
        self._next_id = 1

    def __enter__(self) -> "Inspector":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        try:
            self.ws.close()
        except Exception:
            pass

    def call(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        call_id = self._next_id
        self._next_id += 1
        self.ws.send(
            json.dumps(
                {
                    "id": call_id,
                    "method": method,
                    "params": params or {},
                }
            )
        )

        while True:
            msg = json.loads(self.ws.recv())
            if msg.get("id") != call_id:
                continue
            if "error" in msg:
                raise SynapseError(str(msg["error"]))
            return msg.get("result", {})

    def evaluate(self, expression: str, *, await_promise: bool = True) -> Any:
        result = self.call(
            "Runtime.evaluate",
            {
                "expression": expression,
                "awaitPromise": await_promise,
                "returnByValue": True,
            },
        )
        if "exceptionDetails" in result:
            details = result["exceptionDetails"]
            raise SynapseError(
                details.get("exception", {}).get("description")
                or details.get("text")
                or "JavaScript evaluation failed"
            )
        return result.get("result", {}).get("value")


def get_targets(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> list[dict[str, Any]]:
    with urllib.request.urlopen(f"http://{host}:{port}/json/list", timeout=3) as response:
        return json.loads(response.read().decode("utf-8"))


def get_target(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> InspectorTarget:
    targets = get_targets(host, port)
    for target in targets:
        if target.get("webSocketDebuggerUrl"):
            return InspectorTarget(target)
    raise SynapseError("Inspector is reachable but returned no WebSocket target")


def connect(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Inspector:
    target = get_target(host, port)
    inspector = Inspector(target.websocket_url)
    inspector.call("Runtime.enable")
    return inspector


def parse_json(value: Any) -> Any:
    current = value
    for _ in range(8):
        if not isinstance(current, str):
            break
        try:
            current = json.loads(current)
        except json.JSONDecodeError:
            break
    return current


def walk(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def recursive_value(obj: Any, names: Iterable[str]) -> Any:
    wanted = {name.casefold() for name in names}
    for item in walk(obj):
        for key, value in item.items():
            if key.casefold() in wanted and value not in (None, "", [], {}):
                return value
    return None


def electron_probe(inspector: Inspector) -> dict[str, Any]:
    expression = r'''
(() => {
    const result = {
        pid: typeof process !== "undefined" ? process.pid : null,
        processType: typeof process !== "undefined" ? process.type : null,
        versions: typeof process !== "undefined" ? process.versions : null,
        requireType: typeof require,
        mainModuleRequireType:
            process?.mainModule ? typeof process.mainModule.require : null,
        getBuiltinModuleType:
            typeof process?.getBuiltinModule,
        electron: null
    };

    try {
        const electron = process.mainModule.require("electron");
        result.electron = {
            ok: true,
            keys: Object.keys(electron),
            browserWindows: electron.BrowserWindow.getAllWindows().length,
            webContents: electron.webContents.getAllWebContents().length
        };
    } catch (e) {
        result.electron = {
            ok: false,
            error: String(e?.stack || e)
        };
    }

    return result;
})()
'''
    value = inspector.evaluate(expression)
    if not isinstance(value, dict):
        raise SynapseError(f"Unexpected probe result: {value!r}")
    return value


def renderer_state(inspector: Inspector, *, include_values: bool = True) -> dict[str, Any]:
    include_values_js = "true" if include_values else "false"
    expression = f'''
(async () => {{
    const electron = process.mainModule.require("electron");
    const contents = electron.webContents.getAllWebContents();
    const windows = electron.BrowserWindow.getAllWindows();
    const renderers = [];
    const includeValues = {include_values_js};

    for (const wc of contents) {{
        if (!wc || wc.isDestroyed()) continue;
        try {{
            const data = await wc.executeJavaScript(`
                (() => {{
                    const keys = Object.keys(localStorage);
                    const values = {{}};
                    if (includeValues) {{
                        for (const key of keys) {{
                            if (
                                key === "connectedDevices" ||
                                key === "connectedDeviceInfo" ||
                                key.startsWith("synapse_")
                            ) {{
                                values[key] = localStorage.getItem(key);
                            }}
                        }}
                    }}
                    return {{
                        href: location.href,
                        title: document.title,
                        windowName:
                            window.apiElectron?.windowName ||
                            window.name ||
                            "",
                        keys,
                        values
                    }};
                }})()
            `, true);
            renderers.push({{
                id: wc.id,
                type: wc.getType(),
                ...data
            }});
        }} catch (e) {{
            renderers.push({{
                id: wc.id,
                type: wc.getType(),
                error: String(e?.stack || e)
            }});
        }}
    }}

    return JSON.stringify({{
        pid: process.pid,
        processType: process.type,
        browserWindowCount: windows.length,
        webContentsCount: contents.length,
        renderers
    }});
}})()
'''
    raw = inspector.evaluate(expression)
    if not isinstance(raw, str):
        raise SynapseError(f"Unexpected renderer-state result: {raw!r}")
    return json.loads(raw)


def unique_storage(state: dict[str, Any]) -> dict[str, str]:
    storage: dict[str, str] = {}
    for renderer in state.get("renderers", []):
        values = renderer.get("values")
        if not isinstance(values, dict):
            continue
        for key, raw in values.items():
            if isinstance(raw, str) and key not in storage:
                storage[key] = raw
    return storage


def extract_profiles(obj: Any) -> list[dict[str, str]]:
    best: list[dict[str, str]] = []
    for item in walk(obj):
        profiles = item.get("profiles")
        if not isinstance(profiles, list):
            continue
        current: list[dict[str, str]] = []
        for profile in profiles:
            if not isinstance(profile, dict):
                continue
            name = profile.get("name")
            guid = (
                profile.get("guid")
                or profile.get("GUID")
                or profile.get("id")
                or profile.get("profileGuid")
                or profile.get("profileGUID")
            )
            if name and guid:
                current.append({"name": str(name), "guid": str(guid)})
        if len(current) > len(best):
            best = current
    return best


def extract_active_profile(obj: Any) -> str:
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


def middleware_identities(state: dict[str, Any]) -> list[dict[str, Any]]:
    identities: list[dict[str, Any]] = []
    seen: set[tuple[int, int, str]] = set()
    for renderer in state.get("renderers", []):
        name = str(renderer.get("windowName") or "")
        match = MIDDLEWARE_RE.match(name)
        if not match:
            continue
        vendor_id, product_id, container_id = match.groups()
        identity = (int(vendor_id), int(product_id), container_id.casefold())
        if identity in seen:
            continue
        seen.add(identity)
        identities.append(
            {
                "vendorId": int(vendor_id),
                "productId": int(product_id),
                "containerId": container_id,
                "channel": name.removeprefix("win-"),
                "rendererId": renderer.get("id"),
                "href": renderer.get("href"),
            }
        )
    return identities


def find_device_info(state: dict[str, Any], product_id: int) -> dict[str, Any]:
    for renderer in state.get("renderers", []):
        raw = renderer.get("values", {}).get("connectedDeviceInfo")
        if raw is None:
            continue
        obj = parse_json(raw)
        if not isinstance(obj, (dict, list)):
            continue
        for item in walk(obj):
            value = item.get("productId", item.get("productID"))
            try:
                if int(value) == int(product_id):
                    return item
            except (TypeError, ValueError):
                pass
    return {}


def _device_name(info: dict[str, Any], state_obj: Any, product_id: int) -> str:
    for source in (info, state_obj):
        if not isinstance(source, (dict, list)):
            continue
        for item in walk(source):
            for key in ("productName", "deviceName", "displayName", "editionName"):
                value = item.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
                if isinstance(value, dict):
                    for locale in ("en", "en-US", "en-us"):
                        text = value.get(locale)
                        if isinstance(text, str) and text.strip():
                            return text.strip()
    return f"Razer device PID {product_id}"


def build_devices(state: dict[str, Any]) -> list[dict[str, Any]]:
    storage = unique_storage(state)
    product_ids: set[int] = set()
    for key in storage:
        match = DEVICE_FAMILY_RE.match(key)
        if match:
            product_ids.add(int(match.group(1)))

    middleware_by_pid = {
        item["productId"]: item for item in middleware_identities(state)
    }
    devices: list[dict[str, Any]] = []

    for product_id in sorted(product_ids):
        prefix = f"synapse_{product_id}"
        family: list[tuple[str, Any]] = []
        for key, raw in storage.items():
            if key == prefix or key.startswith(prefix + "_"):
                obj = parse_json(raw)
                if isinstance(obj, (dict, list)):
                    family.append((key, obj))
        if not family:
            continue

        profiles: list[dict[str, str]] = []
        profile_source = ""
        active_profile = ""
        state_obj: Any = family[0][1]
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

        info = find_device_info(state, product_id)
        middleware = middleware_by_pid.get(product_id, {})
        container_id = str(
            middleware.get("containerId")
            or info.get("containerId")
            or info.get("deviceContainerId")
            or recursive_value(state_obj, ("containerId", "deviceContainerId"))
            or ""
        )
        channel = str(middleware.get("channel") or "")
        serial = str(
            info.get("serialNumber")
            or info.get("serialNo")
            or recursive_value(state_obj, ("serialNumber", "serialNo"))
            or ""
        )
        devices.append(
            {
                "id": f"razer:{product_id}:{container_id}" if container_id else f"razer:{product_id}",
                "name": _device_name(info, state_obj, product_id),
                "vendorId": middleware.get("vendorId"),
                "productId": product_id,
                "containerId": container_id,
                "serialNumber": serial,
                "channel": channel,
                "storageKey": prefix,
                "profileSource": profile_source,
                "activeProfile": active_profile,
                "profiles": profiles,
            }
        )
    return devices


def select_by_name_or_id(items: list[dict[str, Any]], query: str, *, id_keys: tuple[str, ...]) -> dict[str, Any] | None:
    q = query.casefold()
    for item in items:
        if any(str(item.get(key, "")).casefold() == q for key in id_keys):
            return item
        if str(item.get("name", "")).casefold() == q:
            return item
    matches = [item for item in items if q in str(item.get("name", "")).casefold()]
    return matches[0] if len(matches) == 1 else None


def switch_profile(
    inspector: Inspector,
    device: dict[str, Any],
    profile: dict[str, Any],
) -> dict[str, Any]:
    channel = str(device.get("channel") or "")
    container_id = str(device.get("containerId") or "")
    profile_guid = str(profile.get("guid") or "")
    if not channel or not container_id or not profile_guid:
        raise SynapseError("Switch requires channel, containerId, and profile GUID")

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

    if (!target) throw new Error("No Razer renderer was found");

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
        template.replace("__CHANNEL__", json.dumps(channel))
        .replace("__PROFILE_GUID__", json.dumps(profile_guid))
        .replace("__CONTAINER_ID__", json.dumps(container_id))
    )
    raw = inspector.evaluate(expression)
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


def wait_for_profile(
    inspector: Inspector,
    device: dict[str, Any],
    profile_guid: str,
    timeout: float = 4.0,
) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        devices = build_devices(renderer_state(inspector))
        current = next(
            (
                item
                for item in devices
                if item.get("productId") == device.get("productId")
                and (
                    not device.get("containerId")
                    or str(item.get("containerId", "")).casefold()
                    == str(device.get("containerId", "")).casefold()
                )
            ),
            None,
        )
        if current and current.get("activeProfile") == profile_guid:
            return True
        time.sleep(0.25)
    return False


def renderer_eval(
    inspector: Inspector,
    expression: str,
    *,
    window_name: str | None = None,
    renderer_id: int | None = None,
    url_contains: str | None = None,
) -> Any:
    selector = {
        "windowName": window_name,
        "rendererId": renderer_id,
        "urlContains": url_contains,
    }
    js_selector = json.dumps(selector)
    js_expression = json.dumps(expression)
    main_expr = f'''
(async () => {{
    const electron = process.mainModule.require("electron");
    const selector = {js_selector};
    for (const wc of electron.webContents.getAllWebContents()) {{
        if (!wc || wc.isDestroyed()) continue;
        if (selector.rendererId !== null && wc.id !== selector.rendererId) continue;
        try {{
            const info = await wc.executeJavaScript(`
                (() => ({{
                    href: location.href,
                    windowName:
                        window.apiElectron?.windowName ||
                        window.name ||
                        ""
                }}))()
            `, true);
            if (selector.windowName && info.windowName !== selector.windowName) continue;
            if (selector.urlContains && !String(info.href).includes(selector.urlContains)) continue;
            const value = await wc.executeJavaScript({js_expression}, true);
            return JSON.stringify({{
                rendererId: wc.id,
                windowName: info.windowName,
                href: info.href,
                value
            }});
        }} catch (e) {{
            if (selector.rendererId !== null) throw e;
        }}
    }}
    throw new Error("No matching renderer found");
}})()
'''
    raw = inspector.evaluate(main_expr)
    return json.loads(raw) if isinstance(raw, str) else raw


def shape(value: Any, *, max_depth: int = 4, max_items: int = 40) -> Any:
    value = parse_json(value)

    def _shape(v: Any, depth: int) -> Any:
        if depth >= max_depth:
            if isinstance(v, dict):
                return {"$type": "dict", "$len": len(v)}
            if isinstance(v, list):
                return {"$type": "list", "$len": len(v)}
            return v
        if isinstance(v, dict):
            out: dict[str, Any] = {}
            for i, (key, child) in enumerate(v.items()):
                if i >= max_items:
                    out["$truncated"] = len(v) - max_items
                    break
                out[str(key)] = _shape(child, depth + 1)
            return out
        if isinstance(v, list):
            return {
                "$type": "list",
                "$len": len(v),
                "$sample": [_shape(child, depth + 1) for child in v[: min(3, max_items)]],
            }
        if isinstance(v, str) and len(v) > 240:
            return v[:237] + "..."
        return v

    return _shape(value, 0)
