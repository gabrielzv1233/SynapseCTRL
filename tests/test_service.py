"""Persistent service core tests; no live Synapse process required."""

import unittest
from unittest.mock import Mock

from synapsectrl.errors import SynapseError
from synapsectrl.models import Device, Profile, SwitchResult
from synapsectrl.service import SynapseService


PROFILE_A = Profile("profile-a", "Alpha", True)
PROFILE_B = Profile("profile-b", "Beta", False)


def device(active: str = "profile-a") -> Device:
    return Device(
        id="device-1",
        name="Razer Mouse",
        vendor_id=5426,
        product_id=180,
        container_id="{container}",
        active_profile_id=active,
        profiles=(
            Profile(PROFILE_A.id, PROFILE_A.name, active == PROFILE_A.id),
            Profile(PROFILE_B.id, PROFILE_B.name, active == PROFILE_B.id),
        ),
    )


class ServiceTests(unittest.TestCase):
    def client(self) -> Mock:
        result = Mock()
        result.list_devices.return_value = (device(),)
        result.close.return_value = None
        return result

    def test_refresh_caches_devices_and_marks_ready(self):
        client = self.client()
        service = SynapseService(client=client)
        devices = service.refresh()
        self.assertEqual(devices[0].id, "device-1")
        state = service.state()
        self.assertEqual(state["state"], "ready")
        self.assertTrue(state["synapseAvailable"])
        self.assertEqual(state["devices"][0]["activeProfileId"], "profile-a")

    def test_profile_change_emits_one_profile_event(self):
        client = self.client()
        client.list_devices.side_effect = ((device("profile-a"),), (device("profile-b"),))
        service = SynapseService(client=client)
        events = []
        service.subscribe(events.append)
        service.refresh()
        service.refresh()
        changed = [event for event in events if event["event"] == "profile.changed"]
        self.assertEqual(len(changed), 1)
        self.assertEqual(changed[0]["data"], {
            "deviceId": "device-1",
            "previousProfileId": "profile-a",
            "profileId": "profile-b",
        })

    def test_unavailable_state_recovers(self):
        client = self.client()
        client.list_devices.side_effect = (
            SynapseError("inspector_unreachable", "Start Synapse."),
            (device(),),
        )
        service = SynapseService(client=client)
        events = []
        service.subscribe(events.append)
        with self.assertRaises(SynapseError):
            service.refresh()
        self.assertEqual(service.state()["state"], "unavailable")
        service.refresh()
        self.assertEqual(service.state()["state"], "ready")
        self.assertEqual(
            [event["event"] for event in events if event["event"].startswith("synapse.")],
            ["synapse.unavailable", "synapse.available"],
        )

    def test_verified_switch_refreshes_immediately(self):
        client = self.client()
        client.switch_profile.return_value = SwitchResult(
            "verified", "device-1", "profile-b", "profile-a", True, True, 12, None
        )
        client.list_devices.return_value = (device("profile-b"),)
        service = SynapseService(client=client)
        result = service.switch_profile("device-1", "profile-b")
        self.assertEqual(result.status, "verified")
        client.switch_profile.assert_called_once_with("device-1", "profile-b", timeout=5.0, verify=True)
        client.list_devices.assert_called_once()
        self.assertEqual(service.state()["devices"][0]["activeProfileId"], "profile-b")

    def test_close_closes_persistent_client(self):
        client = self.client()
        service = SynapseService(client=client)
        service.close()
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
