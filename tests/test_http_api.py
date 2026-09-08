"""HTTP API contract tests without opening a real TCP listener."""

from __future__ import annotations

import json
import unittest

from synapsectrl.errors import SynapseError
from synapsectrl.http_api import HttpApi, create_app
from synapsectrl.models import Device, Profile, Status, SwitchResult


PROFILE = Profile("profile-guid", "Siege", True)
DEVICE = Device(
    id="device-id",
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


class FakeRequest:
    def __init__(self, *, path_params=None, body=b""):
        self.path_params = path_params or {}
        self._body = body

    async def body(self):
        return self._body


class FakeService:
    def __init__(self):
        self.switch_calls = []
        self.error = None

    def start(self):
        pass

    def close(self):
        pass

    def state(self):
        return {
            "state": "ready",
            "synapseAvailable": True,
            "devices": [DEVICE.to_dict()],
            "error": None,
            "updatedAtMs": 123,
        }

    def status(self):
        if self.error:
            raise self.error
        return STATUS

    def refresh(self):
        if self.error:
            raise self.error
        return (DEVICE,)

    def list_devices(self, *, refresh=True):
        if self.error:
            raise self.error
        return (DEVICE,)

    def list_profiles(self, device):
        if self.error:
            raise self.error
        if device != DEVICE.id:
            raise SynapseError("device_not_found", "No device matches that ID.")
        return (PROFILE,)

    def switch_profile(self, device, profile, *, timeout=5.0, verify=True):
        if self.error:
            raise self.error
        self.switch_calls.append((device, profile, timeout, verify))
        return SwitchResult(
            "verified",
            device,
            profile,
            "old-profile",
            True,
            True,
            42,
            None,
        )


def payload(response):
    return json.loads(response.body.decode("utf-8"))


class HttpApiTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.service = FakeService()
        self.api = HttpApi(self.service)

    async def test_root_is_versioned_json(self):
        response = await self.api.root(FakeRequest())
        self.assertEqual(response.status_code, 200)
        data = payload(response)
        self.assertEqual(data["apiVersion"], "1")
        self.assertEqual(data["data"]["name"], "SynapseCTRL")
        self.assertEqual(data["data"]["transport"], "http")

    async def test_devices_and_profiles_use_public_service_methods(self):
        devices = await self.api.devices(FakeRequest())
        profiles = await self.api.profiles(FakeRequest(path_params={"device": DEVICE.id}))
        self.assertEqual(payload(devices)["data"][0]["id"], DEVICE.id)
        self.assertEqual(payload(profiles)["data"][0]["id"], PROFILE.id)

    async def test_active_profile_returns_profile_object(self):
        response = await self.api.active_profile(FakeRequest(path_params={"device": DEVICE.id}))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload(response)["data"], PROFILE.to_dict())

    async def test_activate_profile_accepts_timeout_and_verify(self):
        request = FakeRequest(
            path_params={"device": DEVICE.id, "profile": PROFILE.id},
            body=b'{"timeout":1.25,"verify":false}',
        )
        response = await self.api.activate_profile(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload(response)["data"]["status"], "verified")
        self.assertEqual(self.service.switch_calls, [(DEVICE.id, PROFILE.id, 1.25, False)])

    async def test_activate_profile_rejects_bad_json_and_bad_types(self):
        malformed = await self.api.activate_profile(
            FakeRequest(path_params={"device": DEVICE.id, "profile": PROFILE.id}, body=b"{")
        )
        self.assertEqual(malformed.status_code, 400)
        self.assertEqual(payload(malformed)["error"]["code"], "invalid_json")

        wrong_type = await self.api.activate_profile(
            FakeRequest(
                path_params={"device": DEVICE.id, "profile": PROFILE.id},
                body=b'{"verify":"yes"}',
            )
        )
        self.assertEqual(wrong_type.status_code, 400)
        self.assertEqual(payload(wrong_type)["error"]["code"], "invalid_argument")

    async def test_synapse_errors_map_to_http_statuses(self):
        cases = (
            ("device_not_found", 404),
            ("ambiguous_device", 409),
            ("inspector_unreachable", 503),
        )
        for code, expected in cases:
            with self.subTest(code=code):
                self.service.error = SynapseError(code, "failure")
                response = await self.api.devices(FakeRequest())
                self.assertEqual(response.status_code, expected)
                self.assertEqual(payload(response)["error"]["code"], code)
        self.service.error = None

    async def test_cached_state_does_not_force_refresh(self):
        response = await self.api.state(FakeRequest())
        self.assertEqual(response.status_code, 200)
        self.assertTrue(payload(response)["data"]["synapseAvailable"])

    def test_create_app_exposes_expected_routes_and_service(self):
        app = create_app(self.service)
        paths = {route.path for route in app.routes}
        self.assertIn("/v1/status", paths)
        self.assertIn("/v1/devices", paths)
        self.assertIn("/v1/devices/{device}/profiles/{profile}/activate", paths)
        self.assertIs(app.state.synapse_service, self.service)


if __name__ == "__main__":
    unittest.main()
