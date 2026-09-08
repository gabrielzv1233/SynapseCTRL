"""Regressions from independent review of reconnect and delivery boundaries."""

import copy
import json
import shutil
import subprocess
import unittest
from unittest.mock import patch

from synapsectrl import SynapseClient, SynapseError
from synapsectrl._inspector import Inspector, _snapshot_script


CONTAINER = "{ABCDEF12-1234-1234-1234-123456789ABC}"
DEVICE_ID = "razer:42:100:abcdef12-1234-1234-1234-123456789abc"


def snapshot(active="one"):
    return {"renderers": [
        {"id": 12, "href": "https://apps.razer.com/", "windowName": "systray-left", "broadcastChannelAvailable": True,
         "values": {"synapse_100": {"profiles": [{"name": "Work", "guid": "one"}, {"name": "Play", "guid": "two"}], "activeProfile": active}}},
        {"id": 45, "href": "https://apps.razer.com/", "windowName": f"usb_42_100_{CONTAINER}_mw", "broadcastChannelAvailable": True},
    ]}


class FakeInspector:
    def __init__(self, state=None):
        self.state = state or snapshot()
        self.probe = {"processType": "browser", "electronAvailable": True, "versions": {}}
        self.reachable = True
        self.sends = 0

    def connect(self, **kwargs):
        pass

    def close(self):
        pass

    def snapshot(self, **kwargs):
        return copy.deepcopy(self.state)

    def send_switch(self, *args):
        self.sends += 1
        return False


class IntegrationReviewTests(unittest.TestCase):
    def client(self, inspector):
        patcher = patch("synapsectrl.client.Inspector", return_value=inspector)
        patcher.start()
        self.addCleanup(patcher.stop)
        client = SynapseClient()
        self.addCleanup(client.close)
        return client

    def test_unacknowledged_dispatch_reports_uncertain_delivery(self):
        inspector = FakeInspector()
        result = self.client(inspector).switch_profile(DEVICE_ID, "two")
        self.assertEqual(result.status, "failed")
        self.assertEqual(inspector.sends, 1)
        self.assertTrue(result.error["details"].get("deliveryUnknown"))

    def test_malformed_renderer_does_not_escape_status_contract(self):
        inspector = FakeInspector()
        inspector.state["renderers"].append(None)
        with patch("synapsectrl.client.inspect_bootstrap", return_value={"synapseRunning": True}):
            status = self.client(inspector).status()
        self.assertIn(status.state, ("degraded", "unavailable"))
        self.assertTrue(status.issues)

    def test_malformed_renderer_metadata_does_not_crash_diagnostics(self):
        inspector = FakeInspector()
        inspector.state["renderers"][0]["keys"] = None
        inspector.state["renderers"][1]["keys"] = ["synapse_100", 3, None]
        with patch("synapsectrl.client.inspect_bootstrap", return_value={"synapseRunning": True}):
            report = self.client(inspector).diagnostics()
        self.assertTrue(all(isinstance(key, str) for key in report["storageKeys"]))

    def test_response_after_verification_deadline_cannot_report_verified(self):
        clock = [0.0]
        inspector = FakeInspector()
        def dispatch(*args):
            inspector.sends += 1
            return True
        def read(**kwargs):
            if inspector.sends:
                clock[0] += 2.0
                return snapshot("two")
            return snapshot()
        inspector.send_switch = dispatch
        inspector.snapshot = read
        client = self.client(inspector)
        with patch("synapsectrl.client.time.monotonic", side_effect=lambda: clock[0]), \
             patch("synapsectrl.client.time.sleep", side_effect=lambda seconds: clock.__setitem__(0, clock[0] + seconds)):
            result = client.switch_profile(DEVICE_ID, "two", timeout=1.0)
        self.assertEqual(result.status, "timeout")
        self.assertFalse(result.verified)

    def test_verification_reconnect_does_not_shrink_future_io_budget(self):
        instances = []
        budgets = []
        class RecordingInspector(Inspector):
            def __init__(self, port, timeout):
                super().__init__(port, timeout)
                self.index = len(instances)
                self.sent = False
                instances.append(self)
            def connect(self, **kwargs):
                self.probe = {"processType": "browser", "electronAvailable": True}
                self.reachable = True
            def _evaluate(self, expression, *, timeout=None):
                if self.index == 0 and self.sent:
                    raise SynapseError("transport_lost", "Read disconnected after send")
                budgets.append(timeout)
                return snapshot("two" if self.index else "one")
            def send_switch(self, *args):
                self.sent = True
                return True
        with patch("synapsectrl.client.Inspector", RecordingInspector):
            with SynapseClient(timeout=8.0) as client:
                result = client.switch_profile(DEVICE_ID, "two", timeout=1.0)
                self.assertEqual(result.status, "verified")
                self.assertEqual(len(instances), 2)
                client.list_devices()
        self.assertEqual(budgets[-1], 8.0)

    @unittest.skipUnless(shutil.which("node"), "Node runs the isolated renderer harness")
    def test_renderer_destroyed_during_metadata_read_does_not_abort_other_renderers(self):
        script = r'''
const vm = require("node:vm");
const good = {id: 1, isDestroyed: () => false, getType: () => "window", getURL: () => "https://apps.razer.com/",
    executeJavaScript: () => Promise.resolve({href: "https://apps.razer.com/", windowName: "systray-left", values: {}, keys: [], broadcastChannelAvailable: true})};
const destroyed = {id: 2, isDestroyed: () => false, getType: () => { throw new Error("Object has been destroyed"); }};
const electron = {webContents: {getAllWebContents: () => [good, destroyed]}, BrowserWindow: {getAllWindows: () => []}};
const process = {pid: 123, type: "browser", mainModule: {require: () => electron}};
vm.runInNewContext(EXPRESSION, {process, URL, setTimeout, clearTimeout})
    .then(result => console.log(JSON.stringify({result})))
    .catch(error => console.log(JSON.stringify({error: error.message})));
'''.replace("EXPRESSION", json.dumps(_snapshot_script(0.1)))
        process = subprocess.run(["node", "-e", script], capture_output=True, encoding="utf-8", timeout=10, check=True)
        output = json.loads(process.stdout)
        self.assertIn("result", output)
        self.assertTrue(any(item["id"] == 1 for item in output["result"]["renderers"]))


if __name__ == "__main__":
    unittest.main()
