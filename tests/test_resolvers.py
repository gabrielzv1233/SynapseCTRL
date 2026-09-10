"""Public resolver surface tests; no live Synapse process required."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import Mock, patch

from synapsectrl.bridge import StdioBridge
from synapsectrl.cli import main as cli_main
from synapsectrl.client import SynapseClient
from synapsectrl.discovery import Discovery
from synapsectrl.http_api import HttpApi, create_app
from synapsectrl.models import Device, Profile
from synapsectrl.service import SynapseService


PROFILE = Profile("profile-guid", "Siege", True)
DEVICE = Device(
    id="device-id",
    name="Razer Naga V2 Hyperspeed",
    vendor_id=5426,
    product_id=180,
    container_id="{container}",
    active_profile_id=PROFILE.id,
    profiles=(PROFILE,),
)


class FakeRequest:
    def __init__(self, **path_params):
        self.path_params = path_params


class FakeResolverService:
    def subscribe(self, callback):
        return lambda: None

    def state(self):
        return {"state": "ready", "synapseAvailable": True, "devices": [], "error": None, "updatedAtMs": 1}

    def resolve_device(self, device):
        if device in {DEVICE.id, DEVICE.name, "Naga"}:
            return DEVICE
        raise AssertionError(f"unexpected device selector: {device}")

    def resolve_profile(self, device, profile):
        if device in {DEVICE.id, DEVICE.name, "Naga"} and profile in {PROFILE.id, PROFILE.name}:
            return PROFILE
        raise AssertionError(f"unexpected selectors: {device}, {profile}")


class ResolverTests(unittest.IsolatedAsyncioTestCase):
    def test_client_resolves_ids_names_and_partial_names(self):
        discovery = Discovery(devices=[DEVICE], details={}, warnings=[])
        with SynapseClient() as client, patch.object(client, "_read", return_value=discovery):
            self.assertEqual(client.resolve_device(DEVICE.id), DEVICE)
            self.assertEqual(client.resolve_device(DEVICE.name), DEVICE)
            self.assertEqual(client.resolve_device("Naga"), DEVICE)
            self.assertEqual(client.resolve_profile(DEVICE.id, PROFILE.id), PROFILE)
            self.assertEqual(client.resolve_profile("Naga", PROFILE.name), PROFILE)

    def test_service_exposes_client_resolvers(self):
        client = Mock()
        client.resolve_device.return_value = DEVICE
        client.resolve_profile.return_value = PROFILE
        client.close.return_value = None
        service = SynapseService(client=client)

        self.assertEqual(service.resolve_device("Naga"), DEVICE)
        self.assertEqual(service.resolve_profile("Naga", "Siege"), PROFILE)
        client.resolve_device.assert_called_once_with("Naga")
        client.resolve_profile.assert_called_once_with("Naga", "Siege")

    def test_bridge_exposes_resolver_methods(self):
        bridge = StdioBridge(FakeResolverService(), stdin=io.StringIO(), stdout=io.StringIO(), stderr=io.StringIO())
        device = bridge.handle_request({"id": 1, "method": "device.resolve", "params": {"device": "Naga"}})
        profile = bridge.handle_request({
            "id": 2,
            "method": "profile.resolve",
            "params": {"deviceId": DEVICE.id, "profile": "Siege"},
        })

        self.assertEqual(device["result"], DEVICE.to_dict())
        self.assertEqual(profile["result"], PROFILE.to_dict())

    async def test_http_exposes_resolved_device_and_profile(self):
        api = HttpApi(FakeResolverService())
        device = await api.device(FakeRequest(device="Naga"))
        profile = await api.profile(FakeRequest(device=DEVICE.id, profile="Siege"))

        self.assertEqual(json.loads(device.body)["data"], DEVICE.to_dict())
        self.assertEqual(json.loads(profile.body)["data"], PROFILE.to_dict())

        app = create_app(FakeResolverService())
        paths = {route.path for route in app.routes}
        self.assertIn("/v1/devices/{device}", paths)
        self.assertIn("/v1/devices/{device}/profiles/{profile}", paths)

    def test_cli_resolve_returns_full_objects(self):
        client_factory = Mock()
        client = client_factory.return_value.__enter__.return_value
        device_model = Mock()
        device_model.to_dict.return_value = DEVICE.to_dict()
        profile_model = Mock()
        profile_model.to_dict.return_value = PROFILE.to_dict()
        client.resolve_device.return_value = device_model
        client.resolve_profile.return_value = profile_model

        with patch("synapsectrl.cli.SynapseClient", client_factory):
            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli_main(("resolve", "device", "Naga", "--json"))
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(json.loads(stdout.getvalue())["data"], DEVICE.to_dict())

            stdout, stderr = io.StringIO(), io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                code = cli_main(("resolve", "profile", "Naga", "Siege", "--json"))
            self.assertEqual(code, 0)
            self.assertEqual(stderr.getvalue(), "")
            self.assertEqual(json.loads(stdout.getvalue())["data"], PROFILE.to_dict())

        client.resolve_device.assert_called_once_with("Naga")
        client.resolve_profile.assert_called_once_with("Naga", "Siege")


if __name__ == "__main__":
    unittest.main()
