"""CLI tests for packaged Synapse hook management."""

from contextlib import redirect_stderr, redirect_stdout
import io
import json
import unittest
from unittest.mock import patch

from synapsectrl.cli import main


class HookCLITests(unittest.TestCase):
    def run_cli(self, *args):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(args)
        return code, stdout.getvalue(), stderr.getvalue()

    def test_hook_status_is_read_only_and_does_not_connect(self):
        bootstrap = {
            "backendVersion": "0.3.1",
            "hookInstalled": True,
            "hookHealthy": True,
            "hookCurrent": True,
            "hookVersion": 3,
            "expectedHookVersion": 3,
            "hookProtocolVersion": 1,
            "expectedHookProtocolVersion": 1,
            "hookBuildId": "v3+123456789abc",
            "expectedHookBuildId": "v3+123456789abc",
            "installedByVersion": "0.3.1",
            "installedAtUtc": "2026-09-11T18:00:00Z",
            "versionedLauncher": r"C:\Program Files\Razer\RazerAppEngine\app-4.0.1\RazerAppEngine.exe",
            "issues": [],
        }
        with (
            patch("synapsectrl.cli.inspect_bootstrap", return_value=bootstrap),
            patch("synapsectrl.cli.SynapseClient") as client,
        ):
            code, stdout, stderr = self.run_cli("hook", "status", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["data"], {"action": "status", "bootstrap": bootstrap})
        self.assertEqual(stderr, "")
        client.assert_not_called()

    def test_hook_status_human_output_names_backend_build_protocol_and_installer(self):
        bootstrap = {
            "backendVersion": "0.3.1",
            "hookInstalled": True,
            "hookHealthy": True,
            "hookCurrent": True,
            "hookVersion": 3,
            "expectedHookVersion": 3,
            "hookProtocolVersion": 1,
            "expectedHookProtocolVersion": 1,
            "hookBuildId": "v3+123456789abc",
            "expectedHookBuildId": "v3+123456789abc",
            "installedByVersion": "0.3.1",
            "installedAtUtc": "2026-09-11T18:00:00Z",
            "issues": [],
        }
        with patch("synapsectrl.cli.inspect_bootstrap", return_value=bootstrap):
            code, stdout, stderr = self.run_cli("hook", "status")
        self.assertEqual(code, 0)
        self.assertIn("Backend: SynapseCTRL 0.3.1", stdout)
        self.assertIn("Hook build: v3+123456789abc (current)", stdout)
        self.assertIn("Hook protocol: v1", stdout)
        self.assertIn("Installed by: SynapseCTRL 0.3.1", stdout)
        self.assertEqual(stderr, "")

    def test_hook_install_uses_packaged_installer_without_connecting(self):
        result = {
            "action": "install",
            "exitCode": 0,
            "stdout": None,
            "stderr": None,
            "bootstrap": {"hookInstalled": True, "hookHealthy": True, "issues": []},
        }
        with (
            patch("synapsectrl.cli.run_hook_installer", return_value=result) as installer,
            patch("synapsectrl.cli.SynapseClient") as client,
        ):
            code, stdout, stderr = self.run_cli("hook", "install", "--json")
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout)["data"], result)
        self.assertEqual(stderr, "")
        installer.assert_called_once_with("install")
        client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
