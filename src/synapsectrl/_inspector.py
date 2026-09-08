"""Private Node inspector adapter; no arbitrary evaluation in the public API."""
from __future__ import annotations

import json
import math
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

import websocket

from .errors import SynapseError


def positive_timeout(value: float, name: str = "timeout") -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        raise SynapseError("invalid_argument", f"{name} must be a finite positive number.")
    return float(value)


def validate_endpoint(host: str, port: int) -> tuple[str, int]:
    # No DNS lookup, redirects, proxies, or remote endpoint configuration.
    if host not in ("127.0.0.1", "localhost"):
        raise SynapseError("invalid_argument", "The Synapse inspector must use 127.0.0.1.")
    if isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535:
        raise SynapseError("invalid_argument", "port must be an integer between 1 and 65535.")
    return "127.0.0.1", port


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _target(port: int, timeout: float) -> dict[str, Any]:
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), _NoRedirect())
    try:
        with opener.open(f"http://127.0.0.1:{port}/json/list", timeout=timeout) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise ValueError("Target list too large")
        targets = json.loads(raw)
        if not isinstance(targets, list):
            raise ValueError("Invalid target list")
    except (OSError, urllib.error.URLError) as error:
        raise SynapseError("inspector_unreachable", "Synapse's local inspector is unavailable. Run synapsectrl doctor for repair guidance.") from error
    except (ValueError, UnicodeError) as error:
        raise SynapseError("inspector_protocol_error", "The local inspector returned an invalid target list.") from error
    candidates = [t for t in targets if isinstance(t, dict) and t.get("type") == "node" and t.get("webSocketDebuggerUrl")]
    if len(candidates) != 1:
        raise SynapseError("incompatible_synapse", "Expected one Node browser inspector target.", {"targetCount": len(candidates)})
    target = candidates[0]
    try:
        url = urllib.parse.urlsplit(target["webSocketDebuggerUrl"])
        if (url.scheme != "ws" or url.hostname != "127.0.0.1" or url.port != port
                or url.username is not None or url.password is not None or url.fragment):
            raise ValueError("Unsafe inspector URL")
    except (ValueError, TypeError, AttributeError) as error:
        raise SynapseError("inspector_protocol_error", "The inspector advertised a non-local or invalid WebSocket address.") from error
    return target


_IMPORT = r'''
const getElectron = () => {
    if (typeof process !== "undefined" && typeof process.mainModule?.require === "function") {
        try { return process.mainModule.require("electron"); } catch (_) {}
    }
    if (typeof require === "function") return require("electron");
    throw new Error("Electron import unavailable");
};
'''

_PROBE = r'''(() => {
__IMPORT__
const result = {
    processType: typeof process !== "undefined" ? process.type : null,
    pid: typeof process !== "undefined" ? process.pid : null,
    execPath: typeof process !== "undefined" ? process.execPath : null,
    versions: typeof process !== "undefined" ? process.versions : {},
    electronAvailable: false
};
try {
    const electron = getElectron();
    result.electronAvailable = typeof electron.webContents?.getAllWebContents === "function"
        && typeof electron.BrowserWindow?.getAllWindows === "function";
    if (result.electronAvailable) {
        result.webContentsCount = electron.webContents.getAllWebContents().length;
        result.browserWindowCount = electron.BrowserWindow.getAllWindows().length;
        result.versions = {...result.versions, appEngine: electron.app.getVersion()};
    }
} catch (_) {}
return result;
})()'''.replace("__IMPORT__", _IMPORT)

_RENDERER = r'''(() => {
    const values = {};
    const keys = Object.keys(localStorage);
    for (const key of keys) {
        if (key === "connectedDeviceInfo" || /^synapse_/i.test(key)) {
            values[key] = localStorage.getItem(key);
        }
    }
    return {
        href: location.href,
        windowName: window.apiElectron?.windowName || window.name || "",
        keys: keys.filter(key => key === "connectedDeviceInfo" || /^synapse_/i.test(key)),
        values,
        broadcastChannelAvailable: typeof BroadcastChannel === "function"
    };
})()'''


def _snapshot_script(timeout: float) -> str:
    return r'''(async () => {
__IMPORT__
const electron = getElectron();
const contents = electron.webContents.getAllWebContents();
const renderers = await Promise.all(contents.map(async wc => {
    if (!wc) return null;
    const item = {id: wc.id};
    try {
        if (wc.isDestroyed()) return null;
        item.type = wc.getType();
        item.href = wc.getURL();
        if (new URL(item.href).origin !== "https://apps.razer.com") return {...item, skipped: true};
        let timer;
        try {
            const data = await Promise.race([
                wc.executeJavaScript(__RENDERER__, true),
                new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("Renderer read timed out")), __TIMEOUT__); })
            ]);
            return {...item, ...data};
        } finally { clearTimeout(timer); }
    } catch (e) { return {...item, error: String(e.message || e)}; }
}));
return {pid: process.pid, processType: process.type,
    browserWindowCount: electron.BrowserWindow.getAllWindows().length,
    webContentsCount: contents.length, renderers: renderers.filter(Boolean)};
})()'''.replace("__IMPORT__", _IMPORT).replace("__RENDERER__", json.dumps(_RENDERER)).replace("__TIMEOUT__", str(max(1, int(timeout * 800))))


def _switch_script(channel: str, container_id: str, profile_id: str, renderer_id: int) -> str:
    # Serialize the entire renderer source into JS once, avoiding nested-template
    # interpolation of names, GUIDs, or any other externally obtained value.
    payload = json.dumps({"channel": channel, "containerId": container_id, "profileId": profile_id})
    renderer = r'''(async () => {
        const target = __PAYLOAD__;
        if (location.origin !== "https://apps.razer.com") throw new Error("Sender origin changed");
        const bc = new BroadcastChannel(target.channel);
        try {
            bc.postMessage({type: "ON_SWITCH_PROFILE", payload: {
                newActiveProfileGUID: target.profileId, deviceContainerId: target.containerId
            }});
            bc.postMessage({msgName: "crossPageRequest", msgData: {
                action: "switchProfileBySystray", selectedProfileGuid: target.profileId,
                deviceContainerId: target.containerId
            }});
            await new Promise(resolve => setTimeout(resolve, 250));
            return {sent: true};
        } finally { bc.close(); }
    })()'''.replace("__PAYLOAD__", payload)
    return r'''(async () => {
__IMPORT__
const electron = getElectron();
const target = electron.webContents.fromId(__RENDERER_ID__);
if (!target || target.isDestroyed() || new URL(target.getURL()).origin !== "https://apps.razer.com") {
    throw new Error("Sender renderer is no longer available");
}
return await target.executeJavaScript(__SCRIPT__, true);
})()'''.replace("__IMPORT__", _IMPORT).replace("__RENDERER_ID__", str(int(renderer_id))).replace("__SCRIPT__", json.dumps(renderer))


class Inspector:
    """One serialized connection, owned by SynapseClient's lock."""

    def __init__(self, port: int, timeout: float):
        self.port = port
        self.timeout = timeout
        self.ws = None
        self.probe: dict[str, Any] = {}
        self.reachable = False
        self._next_id = 0

    def connect(self) -> None:
        deadline = time.monotonic() + self.timeout
        target = _target(self.port, self.timeout)
        self.reachable = True
        try:
            self.ws = websocket.create_connection(
                target["webSocketDebuggerUrl"], timeout=max(0.001, deadline - time.monotonic()),
                suppress_origin=True, http_no_proxy=["127.0.0.1"], redirect_limit=0,
            )
            self._call("Runtime.enable", timeout=max(0.001, deadline - time.monotonic()))
            value = self._evaluate(_PROBE, timeout=max(0.001, deadline - time.monotonic()))
            if not isinstance(value, dict):
                raise SynapseError("inspector_protocol_error", "The inspector returned an invalid capability probe.")
            self.probe = value
            exe_name = str(value.get("execPath", "")).replace("\\", "/").rsplit("/", 1)[-1].casefold()
            if value.get("processType") != "browser" or not value.get("electronAvailable") or exe_name != "razerappengine.exe":
                raise SynapseError("incompatible_synapse", "The inspector is not a compatible RazerAppEngine Electron browser process.")
        except SynapseError:
            self.close()
            raise
        except (OSError, websocket.WebSocketException, ValueError) as error:
            self.close()
            raise SynapseError("transport_lost", "Could not connect to Synapse's local inspector.") from error

    def close(self) -> None:
        if self.ws is not None:
            try:
                self.ws.close(timeout=0)
            except Exception:
                pass
            self.ws = None

    def _call(self, method: str, params: dict[str, Any] | None = None, *, timeout: float | None = None) -> dict[str, Any]:
        if self.ws is None:
            raise SynapseError("transport_lost", "The inspector connection is closed.")
        deadline = time.monotonic() + (self.timeout if timeout is None else timeout)
        self._next_id += 1
        call_id = self._next_id
        try:
            self.ws.settimeout(max(0.001, deadline - time.monotonic()))
            self.ws.send(json.dumps({"id": call_id, "method": method, "params": params or {}}))
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("Inspector deadline exceeded")
                self.ws.settimeout(remaining)
                msg = json.loads(self.ws.recv())
                if time.monotonic() >= deadline:
                    raise TimeoutError("Inspector deadline exceeded")
                if not isinstance(msg, dict):
                    raise ValueError("Invalid inspector message")
                if msg.get("id") != call_id:
                    continue
                if "error" in msg:
                    raise SynapseError("inspector_protocol_error", "Synapse rejected an inspector operation.")
                result = msg.get("result", {})
                if not isinstance(result, dict):
                    raise ValueError("Invalid inspector result")
                return result
        except (OSError, websocket.WebSocketException, ValueError, TypeError) as error:
            self.close()
            raise SynapseError("transport_lost", "The inspector disconnected or did not respond in time.") from error

    def _evaluate(self, expression: str, *, timeout: float | None = None) -> Any:
        result = self._call("Runtime.evaluate", {"expression": expression, "awaitPromise": True, "returnByValue": True}, timeout=timeout)
        if "exceptionDetails" in result:
            raise SynapseError("incompatible_synapse", "Synapse could not execute its profile integration. Run synapsectrl doctor.")
        remote = result.get("result", {})
        if not isinstance(remote, dict):
            raise SynapseError("inspector_protocol_error", "Unexpected inspector evaluation result.")
        return remote.get("value")

    def snapshot(self, *, timeout: float | None = None) -> dict[str, Any]:
        limit = self.timeout if timeout is None else min(timeout, self.timeout)
        state = self._evaluate(_snapshot_script(limit), timeout=limit)
        if not isinstance(state, dict) or not isinstance(state.get("renderers"), list):
            raise SynapseError("inspector_protocol_error", "Unexpected renderer discovery result.")
        return state

    def send_switch(self, channel: str, container_id: str, profile_id: str, renderer_id: int) -> bool:
        result = self._evaluate(_switch_script(channel, container_id, profile_id, renderer_id))
        return isinstance(result, dict) and result.get("sent") is True
