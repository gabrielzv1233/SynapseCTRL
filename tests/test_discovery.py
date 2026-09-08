import json
import unittest

from synapsectrl.discovery import normalize


A = "{AAAAAAAA-1111-2222-3333-444444444444}"
B = "{BBBBBBBB-1111-2222-3333-444444444444}"
C = "{CCCCCCCC-1111-2222-3333-444444444444}"


def profiles(*names):
    return [{"guid": name.casefold(), "name": name} for name in names]


def middleware(product=180, container=A, vendor=5426, **extra):
    return {
        "id": product,
        "windowName": f"usb_{vendor}_{product}_{container}_mw",
        "href": f"https://apps.razer.com/synapse/products/{product}/mw/index.html",
        **extra,
    }


def state(values=None, *devices):
    return {"renderers": [
        {"id": 1, "windowName": "systray-left", "values": values or {}},
        *(devices or [middleware()]),
    ]}


class DiscoveryTests(unittest.TestCase):
    def test_stale_stack_active_does_not_override_current_profile_document(self):
        # Live acceptance observed this ordering in localStorage: the profile
        # stack retained a previous GUID after the primary reducer changed.
        snapshot = state({
            "synapse_180_profiles_stack": {"account": {"runningGames": [], "activeProfile": "previous"}},
            "synapse_180": {"profiles": profiles("Previous", "Current"), "activeProfile": "current"},
        })
        device = normalize(snapshot).devices[0]
        self.assertTrue(device.controllable)
        self.assertEqual(device.active_profile_id, "current")

    def test_reference_shape_and_stale_serial_state(self):
        snapshot = state({
            "connectedDeviceInfo": json.dumps([{
                "productId": 180, "serialNumber": "CURRENT",
                "productName": {"en": "Razer Test Mouse"},
            }]),
            "synapse_180": json.dumps({
                "vendorId": 5426, "productId": 180,
                "profiles": profiles("Fortnite", "Seige"), "activeProfile": "seige",
                "deviceMetadatas": {
                    "OLD": {"activeProfileGuid": "fortnite", "name": "Old device"},
                    "CURRENT": {"activeProfileGuid": "seige", "name": "Current device"},
                },
                "calibration": {"profiles": [{"type": "default"}]},
            }),
        })
        result = normalize(snapshot)
        self.assertEqual(len(result.devices), 1)
        device = result.devices[0]
        self.assertEqual(device.id, "razer:5426:180:aaaaaaaa-1111-2222-3333-444444444444")
        self.assertEqual(device.name, "Razer Test Mouse")
        self.assertEqual(device.serial_number, "CURRENT")
        self.assertEqual(device.active_profile_id, "seige")
        self.assertTrue(device.controllable)
        self.assertEqual([profile.name for profile in device.profiles if profile.active], ["Seige"])
        self.assertEqual(result.details[device.id]["channel"], middleware()["windowName"])

    def test_multiple_products_dynamic_family_and_double_encoded_reducer(self):
        snapshot = state({
            "SYNAPSE_999_runtime": json.dumps(json.dumps({"reducer": json.dumps({
                "Profiles": [{"GUID": "ONE", "Name": "Work"}],
                "currentProfile": {"profileGUID": "one"},
            })})),
            "synapse_180": {"profiles": profiles("Game"), "activeProfile": "game"},
        }, middleware(), middleware(999, B, 9999))
        result = normalize(snapshot)
        self.assertEqual(len(result.devices), 2)
        alternate = next(device for device in result.devices if device.product_id == 999)
        self.assertEqual(alternate.vendor_id, 9999)
        self.assertEqual(alternate.active_profile_id, "ONE")
        self.assertTrue(alternate.controllable)
        self.assertEqual(result.details[alternate.id]["profileSource"], "SYNAPSE_999_runtime")

    def test_exact_channel_and_case_insensitive_win_prefix_deduplicate_identity(self):
        name = f"WIN-USB_5426_180_{A}_MW"
        snapshot = state({"synapse_180": {"profiles": profiles("One"), "activeProfile": "one"}},
                         middleware(windowName=name), middleware(container=A.lower()))
        result = normalize(snapshot)
        self.assertEqual(len(result.devices), 1)
        details = result.details[result.devices[0].id]
        self.assertEqual(details["channel"], name[4:])
        self.assertEqual(details["rawWindowName"], name)

    def test_shared_pid_cannot_claim_individual_active_state_or_metadata(self):
        snapshot = state({
            "connectedDeviceInfo": [{"productId": 180, "name": "Unattributed", "serialNumber": "WRONG"}],
            "synapse_180": {"profiles": profiles("One", "Two"), "activeProfile": "one"},
        }, middleware(), middleware(container=B))
        result = normalize(snapshot)
        self.assertEqual(len(result.devices), 2)
        for device in result.devices:
            self.assertTrue(device.profiles_supported)
            self.assertFalse(device.controllable)
            self.assertIsNone(device.active_profile_id)
            self.assertIsNone(device.serial_number)
            self.assertNotEqual(device.name, "Unattributed")
            self.assertIn("shared", device.unavailable_reason)

    def test_same_pid_container_scoped_state_and_metadata(self):
        snapshot = state({
            "connectedDeviceInfo": [
                {"productID": "180", "containerId": A.lower(), "productName": "Mouse A", "serialNo": "A"},
                {"productID": 180, "containerId": B, "productName": "Mouse B", "serialNo": "B"},
            ],
            "synapse_180": {"devices": {
                A: {"profiles": profiles("One", "Two"), "activeProfile": "one"},
                B: {"profiles": profiles("One", "Two"), "activeProfile": "two"},
            }},
        }, middleware(), middleware(container=B))
        result = normalize(snapshot)
        first, second = result.devices
        self.assertEqual((first.name, first.serial_number, first.active_profile_id), ("Mouse A", "A", "one"))
        self.assertEqual((second.name, second.serial_number, second.active_profile_id), ("Mouse B", "B", "two"))
        self.assertTrue(all(device.controllable for device in result.devices))

    def test_container_qualified_browser_keys_are_discovered_without_assuming_them(self):
        snapshot = state({
            f"synapse_180_{A}": {"profiles": profiles("One"), "activeProfile": "one"},
            f"synapse_180_{B}_state": {"profiles": profiles("Two"), "activeProfile": "two"},
        }, middleware(), middleware(container=B))
        result = normalize(snapshot)
        self.assertEqual([device.active_profile_id for device in result.devices], ["one", "two"])

    def test_same_pid_shared_profiles_with_container_scoped_active_values(self):
        snapshot = state({"synapse_180": {
            "profiles": profiles("One", "Two"),
            "devices": {A: {"activeProfile": "one"}, B: {"activeProfile": "two"}},
        }}, middleware(), middleware(container=B))
        result = normalize(snapshot)
        self.assertEqual([device.active_profile_id for device in result.devices], ["one", "two"])
        self.assertTrue(all(device.controllable for device in result.devices))

    def test_vendor_is_part_of_identity_and_scope(self):
        snapshot = state({"synapse_180": {
            "devices": [
                {"vendorId": 5426, "profiles": profiles("One"), "activeProfile": "one"},
                {"vendorId": 9999, "profiles": profiles("Two"), "activeProfile": "two"},
            ],
        }}, middleware(), middleware(vendor=9999))
        result = normalize(snapshot)
        self.assertEqual(len(result.devices), 2)
        self.assertEqual([device.active_profile_id for device in result.devices], ["one", "two"])

    def test_equal_candidate_states_fail_closed(self):
        snapshot = state({"synapse_180": {
            "first": {"profiles": profiles("One", "Two"), "activeProfile": "one"},
            "second": {"profiles": profiles("One", "Two"), "activeProfile": "two"},
        }})
        device = normalize(snapshot).devices[0]
        self.assertFalse(device.controllable)
        self.assertIsNone(device.active_profile_id)
        self.assertIn("disagree", device.unavailable_reason)

    def test_profile_and_active_candidates_do_not_cross_sibling_scopes(self):
        snapshot = state({"synapse_180": {
            "current": {"profiles": profiles("One", "Two")},
            "unrelated": {"profiles": profiles("Three"), "activeProfile": "one"},
        }})
        device = normalize(snapshot).devices[0]
        self.assertFalse(device.controllable)
        self.assertIsNone(device.active_profile_id)
        self.assertIn("paired", device.unavailable_reason)

    def test_current_state_beats_larger_history_stack(self):
        snapshot = state({
            "synapse_180_profiles_stack": {"profiles": profiles("Old", "One", "Two"), "activeProfile": "old"},
            "synapse_180": {"profiles": profiles("One", "Two"), "activeProfile": "two"},
        })
        device = normalize(snapshot).devices[0]
        self.assertEqual(device.active_profile_id, "two")
        self.assertEqual(len(device.profiles), 2)

    def test_conflicting_active_keys_or_missing_active_guid_are_unavailable(self):
        for active in ({"activeProfile": "one", "currentProfileGUID": "two"}, {"activeProfile": "missing"}):
            with self.subTest(active=active):
                device = normalize(state({"synapse_180": {"profiles": profiles("One", "Two"), **active}})).devices[0]
                self.assertFalse(device.controllable)
                self.assertIsNone(device.active_profile_id)

    def test_conflicting_renderer_storage_snapshots_fail_closed(self):
        first = {"profiles": profiles("One", "Two"), "activeProfile": "one"}
        second = {"profiles": profiles("One", "Two"), "activeProfile": "two"}
        snapshot = state({"synapse_180": first}, middleware(values={"synapse_180": second}))
        result = normalize(snapshot)
        self.assertFalse(result.devices[0].controllable)
        self.assertTrue(any("changed between" in warning for warning in result.warnings))

    def test_stale_storage_never_creates_a_live_device(self):
        result = normalize({"renderers": [{"values": {"synapse_999": {"profiles": profiles("Cached"), "activeProfile": "cached"}}}]})
        self.assertEqual(result.devices, [])
        self.assertTrue(any("no matching live" in warning for warning in result.warnings))

    def test_no_profile_device_remains_visible_and_malformed_storage_is_diagnostic(self):
        snapshot = state({"synapse_180": "{broken json", "synapse_180_metadata": {"profiles": [None, {"type": "default"}]}})
        snapshot["renderers"].extend([None, {"id": 9, "error": "destroyed"}])
        result = normalize(snapshot)
        self.assertEqual(len(result.devices), 1)
        self.assertTrue(result.devices[0].connected)
        self.assertFalse(result.devices[0].profiles_supported)
        self.assertFalse(result.devices[0].controllable)
        self.assertGreaterEqual(len(result.warnings), 3)

    def test_duplicate_profile_ids_with_conflicting_names_fail_closed(self):
        device = normalize(state({"synapse_180": {
            "profiles": [{"guid": "ONE", "name": "Work"}, {"guid": "one", "name": "Game"}],
            "activeProfile": "one",
        }})).devices[0]
        self.assertFalse(device.controllable)
        self.assertIn("Conflicting names", device.unavailable_reason)

    def test_invalid_identity_schema_cannot_supply_state(self):
        device = normalize(state({"synapse_180": {
            "vendorId": {"unexpected": 5426}, "profiles": profiles("One"), "activeProfile": "one",
        }})).devices[0]
        self.assertFalse(device.controllable)
        self.assertEqual(device.profiles, ())
        self.assertTrue(normalize({"renderers": {}}).warnings)

    def test_stale_metadata_never_wins_over_container_attributed_info(self):
        snapshot = state({
            "connectedDeviceInfo": [
                {"productId": 180, "name": "Stale", "serialNumber": "OLD"},
                {"productId": 180, "containerId": A, "name": "Current", "serialNumber": "CURRENT"},
            ],
            "synapse_180": {"profiles": profiles("One"), "activeProfile": "one"},
        })
        device = normalize(snapshot).devices[0]
        self.assertEqual((device.name, device.serial_number), ("Current", "CURRENT"))

    def test_ambiguous_metadata_remains_unknown(self):
        snapshot = state({
            "connectedDeviceInfo": [
                {"productId": 180, "name": "First", "serialNumber": "FIRST"},
                {"productId": 180, "name": "Second", "serialNumber": "SECOND"},
            ],
            "synapse_180": {"profiles": profiles("One"), "activeProfile": "one"},
        })
        device = normalize(snapshot).devices[0]
        self.assertIsNone(device.serial_number)
        self.assertEqual(device.name, "Razer device PID 180")

    def test_partial_conflicting_snapshot_does_not_claim_verification(self):
        first = {"profiles": profiles("One", "Two"), "activeProfile": "one"}
        second = {"profiles": profiles("One", "Two"), "activeProfile": "missing"}
        result = normalize(state({"synapse_180": first}, middleware(values={"synapse_180": second})))
        self.assertFalse(result.devices[0].controllable)

    def test_shared_pid_uses_serial_metadata_only_after_container_attribution(self):
        snapshot = state({
            "connectedDeviceInfo": [
                {"productId": 180, "containerId": A, "serialNumber": "SERIAL_A"},
                {"productId": 180, "containerId": B, "serialNumber": "SERIAL_B"},
            ],
            "synapse_180": {
                "profiles": profiles("One", "Two"), "activeProfile": "one",
                "deviceMetadatas": {
                    "SERIAL_A": {"activeProfileGuid": "one"},
                    "SERIAL_B": {"activeProfileGuid": "two"},
                    "OLD_SERIAL": {"activeProfileGuid": "retired"},
                },
            },
        }, middleware(), middleware(container=B))
        result = normalize(snapshot)
        self.assertEqual([device.active_profile_id for device in result.devices], ["one", "two"])
        self.assertTrue(all(device.controllable for device in result.devices))


if __name__ == "__main__":
    unittest.main()
