"""stdio bridge protocol tests; no live Synapse process required."""

import io
import json
import unittest
from unittest.mock import Mock

from synapsectrl.bridge import BRIDGE_PROTOCOL_VERSION, StdioBridge
from synapsectrl.errors import SynapseError
from synapsectrl.models import Device, Profile, Status, SwitchResult


PROFILE = Profile("profile-1", "Siege", True)
DEVICE = Device(
    id="device-1",
    name="Razer Mouse",
    vendor_id=5426,
    product_id=180,
    container_id="{container}",
    active_profile_id=PROFILE.id,
    profiles=(PROFILE,),
)
STATUS = Status(
    state="ready",
    synapse_running=True,
    inspector_reachable=True,
    browser_process=True,
    electron_available=True,
    device_count=1,
    controllable_device_count=1,
)
SWITCH = SwitchResult(
    "verified", "device-1", "profile-1", "profile-old", True, True, 10, None
)


class FakeService:
    def __init__(self) -> None:
        self.callback = None
        self.started = False
        self.closed = False

    def subscribe(self, callback):
        self.callback = callback
        return lambda: None

    def start(self):
        self.started = True

    def close(self):
        self.closed = True

    def state(self):
        return {
            "state": "ready",
            "synapseAvailable": True,
            "devices": [DEVICE.to_dict()],
            "error": None,
            "updatedAtMs": 1,
        }

    def refresh(self):
        return (DEVICE,)

    def list_devices(self, *, refresh=True):
        return (DEVICE,)

    def list_profiles(self, device):
        if device != "device-1":
            raise SynapseError("device_not_found", "No device matches.")
        return (PROFILE,)

    def status(self):
        return STATUS

    def switch_profile(self, device, profile, *, timeout=5.0, verify=True):
        return SWITCH


class BridgeTests(unittest.TestCase):
    def bridge(self, *, stdin=None, stdout=None):
        return StdioBridge(
            FakeService(),
            stdin=stdin or io.StringIO(),
            stdout=stdout or io.StringIO(),
            stderr=io.StringIO(),
        )

    def test_hello_reports_protocol_and_service_state(self):
        bridge = self.bridge()
        response = bridge.handle_request({"id": 1, "method": "hello"})
        self.assertEqual(response["protocolVersion"], BRIDGE_PROTOCOL_VERSION)
        self.assertEqual(response["id"], 1)
        self.assertEqual(response["result"]["transport"], "stdio")
        self.assertEqual(response["result"]["service"]["state"], "ready")

    def test_devices_profiles_status_and_switch(self):
        bridge = self.bridge()
        devices = bridge.handle_request({"id": 1, "method": "devices.list"})
        profiles = bridge.handle_request({
            "id": 2,
            "method": "profiles.list",
            "params": {"deviceId": "device-1"},
        })
        status = bridge.handle_request({"id": 3, "method": "status.get"})
        switched = bridge.handle_request({
            "id": 4,
            "method": "profile.activate",
            "params": {"deviceId": "device-1", "profileId": "profile-1"},
        })
        self.assertEqual(devices["result"][0]["id"], "device-1")
        self.assertEqual(profiles["result"][0]["name"], "Siege")
        self.assertEqual(status["result"]["state"], "ready")
        self.assertEqual(switched["result"]["status"], "verified")

    def test_sdk_error_is_machine_readable(self):
        bridge = self.bridge()
        response = bridge.handle_request({
            "id": "bad-device",
            "method": "profiles.list",
            "params": {"deviceId": "missing"},
        })
        self.assertEqual(response["id"], "bad-device")
        self.assertEqual(response["error"]["code"], "device_not_found")

    def test_protocol_errors_are_responses_not_exceptions(self):
        bridge = self.bridge()
        self.assertEqual(bridge.handle_request([])["error"]["code"], "invalid_request")
        self.assertEqual(
            bridge.handle_request({"id": 1, "method": "profiles.list", "params": []})["error"]["code"],
            "invalid_params",
        )
        self.assertEqual(
            bridge.handle_request({"id": 2, "method": "does.not.exist"})["error"]["code"],
            "method_not_found",
        )

    def test_run_is_ndjson_and_shutdown_closes_service(self):
        stdin = io.StringIO(
            "not json\n"
            '{"id":1,"method":"hello"}\n'
            '{"id":2,"method":"shutdown"}\n'
        )
        stdout = io.StringIO()
        service = FakeService()
        bridge = StdioBridge(service, stdin=stdin, stdout=stdout, stderr=io.StringIO())
        code = bridge.run()
        messages = [json.loads(line) for line in stdout.getvalue().splitlines()]
        self.assertEqual(code, 0)
        self.assertEqual(messages[0]["error"]["code"], "invalid_json")
        self.assertEqual(messages[1]["id"], 1)
        self.assertEqual(messages[2]["result"], {"shuttingDown": True})
        self.assertTrue(service.started)
        self.assertTrue(service.closed)

    def test_service_events_are_written_as_event_messages(self):
        stdout = io.StringIO()
        service = FakeService()
        bridge = StdioBridge(service, stdout=stdout, stdin=io.StringIO(), stderr=io.StringIO())
        service.callback({"event": "profile.changed", "data": {"deviceId": "device-1", "profileId": "profile-1"}})
        message = json.loads(stdout.getvalue())
        self.assertEqual(message["protocolVersion"], BRIDGE_PROTOCOL_VERSION)
        self.assertEqual(message["event"], "profile.changed")
        self.assertNotIn("id", message)


if __name__ == "__main__":
    unittest.main()
