import copy
import json
import time
import unittest
from unittest.mock import patch

from synapsectrl import Profile, SynapseClient, SynapseError
from synapsectrl.client import _resolve
from synapsectrl.metadata import BACKEND_VERSION, HOOK_PROTOCOL_VERSION, HOOK_VERSION


CONTAINER = "{ABCDEF12-1234-1234-1234-123456789ABC}"
DEVICE_ID = "razer:42:100:abcdef12-1234-1234-1234-123456789abc"


def snapshot(active="one"):
    return {"webContentsCount": 2, "renderers": [
        {"id": 12, "href": "https://apps.razer.com/systray/systrayv2/", "windowName": "systray-left", "broadcastChannelAvailable": True,
         "values": {"synapse_100": json.dumps({"profiles": [{"name": "Work", "guid": "one"}, {"name": "Play", "guid": "two"}], "activeProfile": active})}},
        {"id": 45, "href": "https://apps.razer.com/synapse/products/100/mw/", "windowName": f"usb_42_100_{CONTAINER}_mw", "broadcastChannelAvailable": True},
    ]}


class FakeInspector:
    def __init__(self, state=None, *, apply=True, lost_read=False, lost_send=False):
        self.state = state or snapshot()
        self.apply = apply
        self.lost_read = lost_read
        self.lost_send = lost_send
        self.probe = {"processType": "browser", "electronAvailable": True, "versions": {"electron": "test"}}
        self.reachable = True
        self.sends = []
        self.connections = 0
        self.closed = False

    def connect(self):
        self.connections += 1

    def close(self):
        self.closed = True

    def snapshot(self, **kwargs):
        if self.lost_read:
            raise SynapseError("transport_lost", "Test disconnect")
        return copy.deepcopy(self.state)

    def send_switch(self, channel, container, profile, renderer):
        self.sends.append((channel, container, profile, renderer))
        if self.lost_send:
            raise SynapseError("transport_lost", "Disconnected after writing request")
        if self.apply:
            self.state = snapshot(profile)
        return True


class ClientTests(unittest.TestCase):
    def client(self, inspector):
        patcher = patch("synapsectrl.client.Inspector", return_value=inspector)
        patcher.start()
        self.addCleanup(patcher.stop)
        client = SynapseClient()
        self.addCleanup(client.close)
        return client

    def test_refreshes_active_state_and_hides_internal_route(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        before = client.list_devices()[0]
        inspector.state = snapshot("two")
        after = client.list_devices()[0]
        self.assertEqual(before.id, after.id)
        self.assertEqual(before.active_profile_id, "one")
        self.assertEqual(after.active_profile_id, "two")
        self.assertNotIn("channel", after.to_dict())
        self.assertEqual(inspector.connections, 1)

    def test_switch_verifies_and_uses_exact_discovered_route(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        result = client.switch_profile(DEVICE_ID, "Play")
        self.assertEqual(result.status, "verified")
        self.assertTrue(result.sent and result.verified)
        self.assertEqual(result.previous_profile_id, "one")
        self.assertEqual(inspector.sends, [(f"usb_42_100_{CONTAINER}_mw", CONTAINER, "two", 12)])

    def test_already_active_never_dispatches(self):
        inspector = FakeInspector()
        result = self.client(inspector).switch_profile(DEVICE_ID, "ONE")
        self.assertEqual(result.status, "already_active")
        self.assertTrue(result.verified)
        self.assertFalse(result.sent)
        self.assertFalse(inspector.sends)

    def test_sent_is_distinct_from_verified(self):
        result = self.client(FakeInspector(apply=False)).switch_profile(DEVICE_ID, "two", verify=False)
        self.assertEqual(result.status, "sent")
        self.assertTrue(result.sent)
        self.assertFalse(result.verified)

    def test_timeout_never_returns_success_or_repeats_dispatch(self):
        inspector = FakeInspector(apply=False)
        result = self.client(inspector).switch_profile(DEVICE_ID, "two", timeout=0.01)
        self.assertEqual(result.status, "timeout")
        self.assertEqual(result.error["code"], "verification_timeout")
        self.assertTrue(result.sent)
        self.assertFalse(result.verified)
        self.assertEqual(len(inspector.sends), 1)

    def test_dispatch_connection_loss_is_uncertain_and_never_retried(self):
        inspector = FakeInspector(lost_send=True)
        result = self.client(inspector).switch_profile(DEVICE_ID, "two")
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.error["details"]["deliveryUnknown"])
        self.assertEqual(len(inspector.sends), 1)
        self.assertTrue(inspector.closed)

    def test_missing_dispatch_acknowledgement_is_also_uncertain(self):
        inspector = FakeInspector()
        inspector.send_switch = lambda *args: False
        result = self.client(inspector).switch_profile(DEVICE_ID, "two")
        self.assertEqual(result.status, "failed")
        self.assertTrue(result.error["details"]["deliveryUnknown"])

    def test_late_verification_connection_keeps_normal_io_budget(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        client._read(deadline=time.monotonic() + 0.01)
        self.assertEqual(inspector.timeout, client.timeout)

    def test_malformed_renderer_entries_do_not_crash_status_or_diagnostics(self):
        inspector = FakeInspector()
        inspector.state["renderers"].extend([None, [], "unexpected"])
        inspector.state["renderers"][0]["keys"] = [None, 123, "synapse_100"]
        client = self.client(inspector)
        with patch("synapsectrl.client.inspect_bootstrap", return_value={"synapseRunning": True}):
            report = client.diagnostics()
        self.assertEqual(report["status"]["state"], "degraded")
        self.assertEqual(report["storageKeys"], ["synapse_100"])
        self.assertEqual(len(report["devices"]), 1)

    def test_read_reconnects_and_discovers_changed_renderer(self):
        stale, fresh = FakeInspector(lost_read=True), FakeInspector()
        fresh.state["renderers"][1]["id"] = 987
        with patch("synapsectrl.client.Inspector", side_effect=[stale, fresh]):
            with SynapseClient() as client:
                self.assertEqual(client.list_devices()[0].id, DEVICE_ID)
                self.assertEqual(client._discovery.details[DEVICE_ID]["rendererId"], 987)
        self.assertTrue(stale.closed)
        self.assertEqual(fresh.connections, 1)

    def test_verification_reconnects_without_resending(self):
        stale, fresh = FakeInspector(), FakeInspector(snapshot("two"))
        original = stale.send_switch

        def lose_after_dispatch(*args):
            sent = original(*args)
            stale.lost_read = True
            return sent

        stale.send_switch = lose_after_dispatch
        with patch("synapsectrl.client.Inspector", side_effect=[stale, fresh]):
            with SynapseClient() as client:
                result = client.switch_profile(DEVICE_ID, "two")
        self.assertEqual(result.status, "verified")
        self.assertEqual(len(stale.sends), 1)
        self.assertFalse(fresh.sends)

    def test_selection_and_invalid_deadline_fail_before_sending(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        for value in (0, -1, float("inf"), float("nan"), True):
            with self.assertRaises(SynapseError):
                client.switch_profile(DEVICE_ID, "two", timeout=value)
        with self.assertRaises(SynapseError) as error:
            client.switch_profile("missing", "two")
        self.assertEqual(error.exception.code, "device_not_found")
        self.assertFalse(inspector.sends)

    def test_ambiguous_exact_and_fuzzy_names_fail_closed(self):
        profiles = [Profile("a", "Play"), Profile("b", "Play"), Profile("c", "Player")]
        for query in ("Play", "pla"):
            with self.assertRaises(SynapseError) as error:
                _resolve(profiles, query, "profile")
            self.assertEqual(error.exception.code, "ambiguous_profile")
        self.assertEqual(_resolve(profiles, "B", "profile").id, "b")

    def test_status_reports_backend_and_hook_version_metadata(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        bootstrap = {
            "synapseRunning": True,
            "hookHealthy": True,
            "hookVersion": HOOK_VERSION,
            "expectedHookVersion": HOOK_VERSION,
            "hookProtocolVersion": HOOK_PROTOCOL_VERSION,
            "expectedHookProtocolVersion": HOOK_PROTOCOL_VERSION,
            "hookBuildId": "v3+123456789abc",
            "expectedHookBuildId": "v3+123456789abc",
            "installedByVersion": BACKEND_VERSION,
            "issues": [],
            "repair": [],
        }
        with patch("synapsectrl.client.inspect_bootstrap", return_value=bootstrap):
            status = client.status()
        self.assertEqual(status.state, "ready")
        self.assertEqual(status.versions["synapseCtrl"], BACKEND_VERSION)
        self.assertEqual(status.versions["hook"], str(HOOK_VERSION))
        self.assertEqual(status.versions["hookProtocol"], str(HOOK_PROTOCOL_VERSION))
        self.assertEqual(status.versions["hookBuild"], "v3+123456789abc")
        self.assertEqual(status.versions["hookInstalledBy"], BACKEND_VERSION)
        self.assertEqual(status.versions["electron"], "test")

    def test_newer_hook_preserves_backend_upgrade_guidance(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        bootstrap = {
            "synapseRunning": True,
            "hookHealthy": False,
            "hookVersion": HOOK_VERSION + 1,
            "expectedHookVersion": HOOK_VERSION,
            "issues": [{"code": "backend_outdated", "message": "Installed hook is newer."}],
            "repair": ["Upgrade SynapseCTRL before changing the installed hook."],
        }
        with patch("synapsectrl.client.inspect_bootstrap", return_value=bootstrap):
            status = client.status()
        self.assertEqual(status.state, "degraded")
        self.assertIn("Upgrade SynapseCTRL before changing the installed hook.", status.repair)
        self.assertFalse(any("hook repair" in item for item in status.repair))

    def test_status_after_failed_read_has_no_stale_devices(self):
        inspector = FakeInspector()
        client = self.client(inspector)
        client.list_devices()
        inspector.lost_read = True
        with patch("synapsectrl.client.inspect_bootstrap", return_value={"synapseRunning": True, "hookHealthy": True}):
            status = client.status()
        self.assertEqual(status.state, "unavailable")
        self.assertEqual(status.device_count, 0)
        self.assertFalse(status.inspector_reachable)
        self.assertTrue(status.repair)

    def test_diagnostics_exclude_full_storage(self):
        client = self.client(FakeInspector())
        with patch("synapsectrl.client.inspect_bootstrap", return_value={"synapseRunning": True}):
            report = client.diagnostics()
        self.assertEqual(report["status"]["state"], "ready")
        self.assertFalse(any("values" in item for item in report["renderers"]))
        self.assertIn("channel", report["deviceDetails"][DEVICE_ID])

    def test_wrong_origin_cannot_be_used_as_a_sender(self):
        inspector = FakeInspector()
        for renderer in inspector.state["renderers"]:
            renderer["href"] = "https://apps.razer.com.evil.test/"
        with self.assertRaises(SynapseError) as error:
            self.client(inspector).switch_profile(DEVICE_ID, "two")
        self.assertEqual(error.exception.code, "device_unavailable")
        self.assertFalse(inspector.sends)


if __name__ == "__main__":
    unittest.main()
