"""CLI contract tests; no live Synapse process or profile changes."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from synapsectrl.cli import main
from synapsectrl.errors import SynapseError


STATUS = {
    "state": "ready", "synapseRunning": True, "inspectorReachable": True,
    "browserProcess": True, "electronAvailable": True, "deviceCount": 1,
    "controllableDeviceCount": 1, "versions": {"electron": "30.2.0"},
    "issues": [], "repair": [],
}
PROFILE = {"id": "profile-guid", "name": "Création", "active": True}
DEVICE = {
    "id": "device-id", "name": "Razer Mouse", "vendorId": 123,
    "productId": 456, "containerId": "{container}", "serialNumber": "serial",
    "connected": True, "profilesSupported": True, "controllable": True,
    "unavailableReason": None, "activeProfileId": "profile-guid", "profiles": [PROFILE],
}


def model(value):
    result = Mock()
    result.to_dict.return_value = value
    return result


def switch_result(status="verified"):
    return {
        "status": status, "deviceId": "device-id", "profileId": "profile-guid",
        "previousProfileId": "previous-guid", "sent": status != "already_active",
        "verified": status in {"verified", "already_active"}, "elapsedMs": 100,
        "error": {"code": "verification_timeout", "message": "Deadline expired.", "details": None}
        if status == "timeout" else None,
    }


class CLITests(unittest.TestCase):
    def setUp(self):
        self.client_patch = patch("synapsectrl.cli.SynapseClient")
        self.factory = self.client_patch.start()
        self.addCleanup(self.client_patch.stop)
        self.client = self.factory.return_value.__enter__.return_value
        self.client.status.return_value = model(STATUS)
        self.client.list_devices.return_value = (model(DEVICE),)
        self.client.list_profiles.return_value = (model(PROFILE),)
        self.client.switch_profile.return_value = model(switch_result())
        self.client.diagnostics.return_value = {
            "status": STATUS, "bootstrap": {"installed": True}, "renderers": [],
        }

    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_json_before_or_after_command(self):
        for arguments in (("--json", "devices"), ("devices", "--json")):
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.run_cli(*arguments)
                self.assertEqual(code, 0)
                self.assertEqual(json.loads(stdout), {"apiVersion": "1", "data": [DEVICE]})
                self.assertEqual(stderr, "")

    def test_connection_options_and_switch_deadline_are_independent(self):
        code, _, _ = self.run_cli("--timeout", "9", "--port", "9333", "switch",
                                   "mouse", "profile-guid", "--timeout", "0.75", "--no-verify")
        self.assertEqual(code, 0)
        self.factory.assert_called_once_with(port=9333, timeout=9.0)
        self.client.switch_profile.assert_called_once_with("mouse", "profile-guid", timeout=0.75, verify=False)

    def test_connection_options_after_command(self):
        code, _, _ = self.run_cli("status", "--port", "9444", "--connect-timeout", "2")
        self.assertEqual(code, 0)
        self.factory.assert_called_once_with(port=9444, timeout=2.0)

    def test_status_readiness_controls_exit_code(self):
        for state in ("ready", "degraded", "unavailable"):
            with self.subTest(state=state):
                self.client.status.return_value = model({**STATUS, "state": state})
                code, stdout, stderr = self.run_cli("status", "--json")
                self.assertEqual(code, 0 if state == "ready" else 1)
                self.assertEqual(json.loads(stdout)["data"]["state"], state)
                self.assertEqual(stderr, "")

    def test_unavailable_status_displays_repairs(self):
        self.client.status.return_value = model({
            **STATUS, "state": "unavailable", "synapseRunning": None,
            "issues": ["Inspector unavailable."], "repair": ["Restart Synapse."],
        })
        code, stdout, _ = self.run_cli("status")
        self.assertEqual(code, 1)
        self.assertIn("Synapse running: unknown", stdout)
        self.assertIn("Inspector unavailable.", stdout)
        self.assertIn("Restart Synapse.", stdout)

    def test_devices_human_output_includes_stable_id_and_active_name(self):
        code, stdout, _ = self.run_cli("devices")
        self.assertEqual(code, 0)
        self.assertIn("ID: device-id", stdout)
        self.assertIn("Création [profile-guid]", stdout)
        self.assertNotIn("channel", stdout)

    def test_profiles_selects_device_and_preserves_unicode_json(self):
        code, stdout, _ = self.run_cli("profiles", "device-id", "--json")
        self.assertEqual(code, 0)
        self.client.list_profiles.assert_called_once_with("device-id")
        self.assertEqual(json.loads(stdout)["data"], [PROFILE])
        self.assertIn("Création", stdout)

    def test_empty_device_list_is_success_with_helpful_text(self):
        self.client.list_devices.return_value = ()
        code, stdout, _ = self.run_cli("devices")
        self.assertEqual(code, 0)
        self.assertIn("No Synapse devices", stdout)
        self.assertIn("doctor", stdout)

    def test_switch_results_have_distinct_exit_statuses(self):
        for status, expected in (("verified", 0), ("already_active", 0), ("sent", 0), ("timeout", 3), ("failed", 1)):
            with self.subTest(status=status):
                self.client.switch_profile.return_value = model(switch_result(status))
                code, stdout, stderr = self.run_cli("switch", "device-id", "profile-guid", "--json")
                self.assertEqual(code, expected)
                self.assertEqual(json.loads(stdout)["data"]["status"], status)
                self.assertEqual(stderr, "")

    def test_unverified_human_output_never_claims_success(self):
        self.client.switch_profile.return_value = model(switch_result("sent"))
        code, stdout, _ = self.run_cli("switch", "device-id", "profile-guid", "--no-verify")
        self.assertEqual(code, 0)
        self.assertIn("Active state was not verified", stdout)

    def test_error_envelope_and_ambiguity_exit_status(self):
        details = {"candidates": [{"id": "first", "name": "Mouse"}, {"id": "second", "name": "Mouse"}]}
        self.client.list_profiles.side_effect = SynapseError("ambiguous_device", "Choose a stable ID.", details)
        code, stdout, stderr = self.run_cli("profiles", "Mouse", "--json")
        self.assertEqual(code, 2)
        self.assertEqual(json.loads(stdout), {
            "apiVersion": "1", "error": {"code": "ambiguous_device", "message": "Choose a stable ID.", "details": details},
        })
        self.assertEqual(stderr, "")

    def test_human_error_uses_stderr(self):
        self.client.list_devices.side_effect = SynapseError("inspector_unreachable", "Start Synapse.")
        code, stdout, stderr = self.run_cli("devices")
        self.assertEqual(code, 1)
        self.assertEqual(stdout, "")
        self.assertIn("inspector_unreachable", stderr)

    def test_usage_errors_are_machine_readable_and_do_not_connect(self):
        for arguments in (
            ("--json",), ("--json", "unknown"), ("switch", "mouse", "--json"),
            ("--port", "0", "devices", "--json"), ("--port", "65536", "devices", "--json"),
            ("--timeout", "NaN", "status", "--json"), ("--timeout", "inf", "status", "--json"),
            ("switch", "mouse", "profile", "--timeout", "0", "--json"),
            ("switch", "mouse", "profile", "--timeout", "-1", "--json"),
        ):
            with self.subTest(arguments=arguments):
                code, stdout, stderr = self.run_cli(*arguments)
                self.assertEqual(code, 2)
                self.assertEqual(json.loads(stdout)["error"]["code"], "invalid_argument")
                self.assertEqual(stderr, "")
        self.factory.assert_not_called()

    def test_doctor_saves_same_versioned_report_as_stdout(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested" / "report.json"
            code, stdout, stderr = self.run_cli("doctor", "--out", str(path), "--json")
            self.assertEqual(code, 0)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), json.loads(stdout))
            self.assertEqual(stderr, "")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_doctor_preserves_existing_file_if_atomic_replace_fails(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            path.write_text("previous report", encoding="utf-8")
            with patch("synapsectrl.cli.os.replace", side_effect=PermissionError("File in use.")):
                code, stdout, stderr = self.run_cli("doctor", "--out", str(path), "--json")
            self.assertEqual(code, 1)
            self.assertEqual(json.loads(stdout)["error"]["code"], "io_error")
            self.assertEqual(path.read_text(encoding="utf-8"), "previous report")
            self.assertEqual(list(path.parent.glob("*.tmp")), [])
            self.assertEqual(stderr, "")

    def test_doctor_unavailable_is_a_report_with_failure_exit_status(self):
        self.client.diagnostics.return_value = {"status": {**STATUS, "state": "unavailable"}}
        code, stdout, _ = self.run_cli("doctor", "--json")
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(stdout)["data"]["status"]["state"], "unavailable")

    def test_doctor_displays_bootstrap_repairs_even_when_runtime_is_ready(self):
        self.client.diagnostics.return_value = {
            "status": STATUS,
            "bootstrap": {
                "supported": True, "hookInstalled": True, "hookHealthy": False,
                "issues": [{"code": "shim_missing", "message": "Launch shim is missing."}],
                "repair": ["Run the source installer."],
            },
        }
        code, stdout, _ = self.run_cli("doctor")
        self.assertEqual(code, 0)
        self.assertIn("Launch hook: needs repair", stdout)
        self.assertIn("Launch shim is missing.", stdout)
        self.assertIn("Run the source installer.", stdout)

    def test_interrupt_is_machine_readable_and_closes_client(self):
        self.client.list_devices.side_effect = KeyboardInterrupt
        code, stdout, stderr = self.run_cli("devices", "--json")
        self.assertEqual(code, 130)
        self.assertEqual(json.loads(stdout)["error"]["code"], "interrupted")
        self.assertEqual(stderr, "")
        self.factory.return_value.__exit__.assert_called_once()


if __name__ == "__main__":
    unittest.main()
