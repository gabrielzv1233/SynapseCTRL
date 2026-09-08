import io
import json
import shutil
import subprocess
import unittest
from unittest.mock import Mock, patch

from synapsectrl import SynapseClient, SynapseError
from synapsectrl._inspector import Inspector, _snapshot_script, _switch_script, _target


class TransportTests(unittest.TestCase):
    def test_loopback_only_configuration(self):
        for host in ("0.0.0.0", "::", "::1", "192.168.0.1", "example.test", "127.0.0.2"):
            with self.assertRaises(SynapseError):
                SynapseClient(host=host)
        self.assertEqual(SynapseClient(host="localhost").host, "127.0.0.1")

    def test_advertised_websocket_cannot_redirect_to_another_host_or_port(self):
        for url in ("ws://evil.test:9229/id", "ws://127.0.0.1:80/id", "wss://127.0.0.1:9229/id", "ws://user:pass@127.0.0.1:9229/id", "ws://127.0.0.1:9229/id#fragment"):
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps([{"type": "node", "webSocketDebuggerUrl": url}]).encode())
            with patch("synapsectrl._inspector.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(SynapseError) as error:
                    _target(9229, 1)
            self.assertEqual(error.exception.code, "inspector_protocol_error")

    def test_non_node_and_ambiguous_targets_rejected(self):
        for targets in ([{"type": "page", "webSocketDebuggerUrl": "ws://127.0.0.1:9229/id"}],
                        [{"type": "node", "webSocketDebuggerUrl": "ws://127.0.0.1:9229/id"}] * 2):
            opener = Mock()
            opener.open.return_value = io.BytesIO(json.dumps(targets).encode())
            with patch("synapsectrl._inspector.urllib.request.build_opener", return_value=opener):
                with self.assertRaises(SynapseError) as error:
                    _target(9229, 1)
            self.assertEqual(error.exception.code, "incompatible_synapse")

    def test_async_events_are_skipped_and_ids_match(self):
        inspector = Inspector(9229, 1)
        inspector.ws = Mock()
        inspector.ws.recv.side_effect = [json.dumps({"method": "Runtime.consoleAPICalled"}), json.dumps({"id": 7}), json.dumps({"id": 1, "result": {"answer": 42}})]
        self.assertEqual(inspector._call("Runtime.enable"), {"answer": 42})

    def test_event_flood_is_bounded_by_deadline(self):
        inspector = Inspector(9229, 1)
        inspector.ws = Mock()
        inspector.ws.recv.return_value = '{"method":"Runtime.consoleAPICalled"}'
        with patch("synapsectrl._inspector.time.monotonic", side_effect=[0, 0, 0.2, 1.1]):
            with self.assertRaises(SynapseError) as error:
                inspector._call("Runtime.enable")
        self.assertEqual(error.exception.code, "transport_lost")
        self.assertIsNone(inspector.ws)

    def test_js_exception_is_not_silently_treated_as_empty_success(self):
        inspector = Inspector(9229, 1)
        with patch.object(inspector, "_call", return_value={"exceptionDetails": {"text": "boom"}}):
            with self.assertRaises(SynapseError) as error:
                inspector._evaluate("1")
        self.assertEqual(error.exception.code, "incompatible_synapse")

    def test_probe_rejects_other_electron_application(self):
        inspector = Inspector(9229, 1)
        with patch("synapsectrl._inspector._target", return_value={"webSocketDebuggerUrl": "ws://127.0.0.1:9229/test"}), \
             patch("synapsectrl._inspector.websocket.create_connection", return_value=Mock()), \
             patch.object(inspector, "_call"), \
             patch.object(inspector, "_evaluate", return_value={"processType": "browser", "electronAvailable": True, "execPath": "C:/Other/App.exe"}):
            with self.assertRaises(SynapseError) as error:
                inspector.connect()
        self.assertEqual(error.exception.code, "incompatible_synapse")
        self.assertIsNone(inspector.ws)


@unittest.skipUnless(shutil.which("node"), "Node is needed only to execute the JavaScript protocol harness")
class JavaScriptProtocolTests(unittest.TestCase):
    def run_js(self, script):
        result = subprocess.run(["node", "-e", script], capture_output=True, text=True, encoding="utf-8", timeout=10, check=True)
        return json.loads(result.stdout)

    def test_real_generated_switch_script_sends_both_messages_without_interpolation(self):
        channel = 'usb_42_100_{abc}_mw'
        profile = '` ${globalThis.compromised = true} "\\\n'
        expression = _switch_script(channel, "{abc}", profile, 777)
        script = r'''
const vm = require("node:vm");
const messages = [];
let closed = false;
const renderer = {
    location: {origin: "https://apps.razer.com"}, setTimeout,
    BroadcastChannel: class {
        constructor(name) { messages.push({channel: name}); }
        postMessage(value) { messages.push(value); }
        close() { closed = true; }
    }
};
const wc = {isDestroyed: () => false, getURL: () => "https://apps.razer.com/",
    executeJavaScript: source => vm.runInNewContext(source, renderer)};
const process = {mainModule: {require: () => ({webContents: {fromId: id => id === 777 ? wc : null}})}};
vm.runInNewContext(EXPRESSION, {process, URL}).then(result => {
    console.log(JSON.stringify({result, messages, closed, compromised: renderer.compromised || false}));
}).catch(error => {console.error(error); globalThis.process.exitCode = 1;});
'''.replace("EXPRESSION", json.dumps(expression))
        output = self.run_js(script)
        self.assertEqual(output["result"], {"sent": True})
        self.assertEqual(output["messages"], [
            {"channel": channel},
            {"type": "ON_SWITCH_PROFILE", "payload": {"newActiveProfileGUID": profile, "deviceContainerId": "{abc}"}},
            {"msgName": "crossPageRequest", "msgData": {"action": "switchProfileBySystray", "selectedProfileGuid": profile, "deviceContainerId": "{abc}"}},
        ])
        self.assertTrue(output["closed"])
        self.assertFalse(output["compromised"])

    def test_snapshot_script_crosses_renderer_boundary_and_tolerates_hung_renderer(self):
        script = r'''
const vm = require("node:vm");
const localStorage = {synapse_900: '{"activeProfile":"a"}', unrelatedSecret: "do not return"};
Object.defineProperty(localStorage, "getItem", {value: key => localStorage[key]});
const good = {id: 123, isDestroyed: () => false, getType: () => "window",
    getURL: () => "https://apps.razer.com/", executeJavaScript: source => Promise.resolve(vm.runInNewContext(source,
        {localStorage, location: {href:"https://apps.razer.com/"}, window: {apiElectron:{windowName:"systray-left"}}, BroadcastChannel: class {}}))};
const hung = {...good, id: 999, executeJavaScript: () => new Promise(() => {})};
const foreign = {...good, id: 456, getURL: () => "https://unrelated.test/", executeJavaScript: () => {throw new Error("must not run");}};
const electron = {webContents: {getAllWebContents: () => [good, hung, foreign]}, BrowserWindow: {getAllWindows: () => []}};
const process = {pid:1234,type:"browser",mainModule:{require: () => electron}};
vm.runInNewContext(EXPRESSION, {process, URL, setTimeout, clearTimeout}).then(result => console.log(JSON.stringify(result)))
    .catch(error => {console.error(error); globalThis.process.exitCode = 1;});
'''.replace("EXPRESSION", json.dumps(_snapshot_script(0.1)))
        output = self.run_js(script)
        self.assertEqual(output["webContentsCount"], 3)
        self.assertEqual(output["renderers"][0]["values"], {"synapse_900": '{"activeProfile":"a"}'})
        self.assertIn("timed out", output["renderers"][1]["error"])
        self.assertTrue(output["renderers"][2]["skipped"])


if __name__ == "__main__":
    unittest.main()
