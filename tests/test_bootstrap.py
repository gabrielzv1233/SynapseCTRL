"""Bootstrap checks use fixtures; no registry or live process mutation."""

from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import psutil

from synapsectrl import bootstrap
from synapsectrl.metadata import (
    BACKEND_VERSION,
    HOOK_PROTOCOL_VERSION,
    HOOK_VERSION,
    expected_hook_fingerprint,
    hook_build_id,
)


class BootstrapTests(unittest.TestCase):
    def setUp(self):
        self.temporary = TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.program_files = Path(self.temporary.name)
        self.razer = self.program_files / "Razer" / "RazerAppEngine"
        self.razer.mkdir(parents=True)
        (self.razer / "RazerAppEngine.exe").touch()
        self.make_version("4.0.999")
        self.make_version("4.0.1000")
        self.shim = self.program_files / "SynapseCTRL" / "RazerInspectShim.exe"
        self.shim.parent.mkdir()
        self.shim.touch()
        self.fingerprint = expected_hook_fingerprint()
        self.base = {"UseFilter": 1}
        self.filters = {"SynapseCTRL": {
            "FilterFullPath": str(self.razer / "RazerAppEngine.exe"),
            "Debugger": f'"{self.shim}"',
            "HookVersion": HOOK_VERSION,
            "HookProtocolVersion": HOOK_PROTOCOL_VERSION,
            "HookFingerprint": self.fingerprint,
            "InstalledByVersion": BACKEND_VERSION,
            "InstalledAtUtc": "2026-09-11T18:00:00.0000000Z",
        }}
        for item in [
            patch.object(bootstrap.sys, "platform", "win32"),
            patch.object(bootstrap, "winreg", object()),
            patch.dict(bootstrap.os.environ, {
                "ProgramW6432": str(self.program_files),
                "ProgramFiles": str(self.program_files),
            }),
            patch.object(bootstrap, "synapse_running", return_value=True),
            patch.object(bootstrap, "_registry_values", side_effect=lambda _: self.base),
            patch.object(bootstrap, "_registry_filters", side_effect=lambda: self.filters),
        ]:
            item.start()
            self.addCleanup(item.stop)

    def make_version(self, version, executable=True):
        directory = self.razer / f"app-{version}"
        directory.mkdir()
        if executable:
            (directory / "RazerAppEngine.exe").touch()

    def codes(self, result):
        return {issue["code"] for issue in result["issues"]}

    def test_healthy_hook_reports_current_backend_and_exact_build(self):
        self.make_version("9.0.0", executable=False)
        self.make_version("99.0-preview")
        result = bootstrap.inspect_bootstrap()
        self.assertTrue(result["hookHealthy"])
        self.assertTrue(result["hookInstalled"])
        self.assertTrue(result["hookCurrent"])
        self.assertEqual(result["backendVersion"], BACKEND_VERSION)
        self.assertEqual(result["hookVersion"], HOOK_VERSION)
        self.assertEqual(result["expectedHookVersion"], HOOK_VERSION)
        self.assertEqual(result["hookProtocolVersion"], HOOK_PROTOCOL_VERSION)
        self.assertEqual(result["expectedHookProtocolVersion"], HOOK_PROTOCOL_VERSION)
        self.assertEqual(result["hookFingerprint"], self.fingerprint)
        self.assertEqual(result["expectedHookFingerprint"], self.fingerprint)
        self.assertEqual(result["hookBuildId"], hook_build_id(HOOK_VERSION, self.fingerprint))
        self.assertEqual(result["hookBuildId"], result["expectedHookBuildId"])
        self.assertEqual(result["installedByVersion"], BACKEND_VERSION)
        self.assertIn("app-4.0.1000", result["versionedLauncher"])
        self.assertEqual(result["issues"], [])

    def test_legacy_hook_without_managed_metadata_requires_repair(self):
        own = self.filters["SynapseCTRL"]
        for name in (
            "HookProtocolVersion",
            "HookFingerprint",
            "InstalledByVersion",
            "InstalledAtUtc",
        ):
            own.pop(name)
        own["HookVersion"] = 2
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertFalse(result["hookCurrent"])
        self.assertIn("hook_outdated", self.codes(result))
        self.assertTrue(any("hook repair" in step for step in result["repair"]))

    def test_missing_revision_is_managed_as_stale_metadata(self):
        del self.filters["SynapseCTRL"]["HookVersion"]
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("hook_metadata_missing", self.codes(result))

    def test_older_hook_revision_is_outdated(self):
        self.filters["SynapseCTRL"]["HookVersion"] = HOOK_VERSION - 1
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("hook_outdated", self.codes(result))
        self.assertTrue(any("hook repair" in step for step in result["repair"]))

    def test_newer_hook_revision_requires_backend_upgrade_not_downgrade(self):
        self.filters["SynapseCTRL"]["HookVersion"] = HOOK_VERSION + 1
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("backend_outdated", self.codes(result))
        self.assertTrue(any("Upgrade SynapseCTRL" in step for step in result["repair"]))
        self.assertFalse(any("hook repair" in step for step in result["repair"]))

    def test_protocol_mismatch_is_reported_separately(self):
        self.filters["SynapseCTRL"]["HookProtocolVersion"] = HOOK_PROTOCOL_VERSION + 1
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("hook_protocol_mismatch", self.codes(result))
        self.assertTrue(any("Upgrade SynapseCTRL" in step for step in result["repair"]))

    def test_exact_build_fingerprint_detects_changed_hook_code(self):
        self.filters["SynapseCTRL"]["HookFingerprint"] = "0" * 64
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("hook_build_mismatch", self.codes(result))
        self.assertNotEqual(result["hookBuildId"], result["expectedHookBuildId"])

    def test_missing_installer_backend_version_is_stale_metadata(self):
        del self.filters["SynapseCTRL"]["InstalledByVersion"]
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("hook_metadata_missing", self.codes(result))

    def test_missing_hook_has_repair_command_without_needing_elevation_to_inspect(self):
        self.filters = {}
        result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["hookHealthy"])
        self.assertIn("hook_missing", self.codes(result))
        self.assertTrue(any("hook repair" in step for step in result["repair"]))

    def test_missing_shim_and_disabled_filter_are_independently_diagnosed(self):
        self.shim.unlink()
        self.base["UseFilter"] = 0
        result = bootstrap.inspect_bootstrap()
        self.assertEqual(self.codes(result), {"shim_missing", "hook_disabled"})
        self.assertEqual(len(result["repair"]), 1)

    def test_rejects_unquoted_or_augmented_debugger_commands(self):
        for command in [str(self.shim), f'"{self.shim}" --inspect=0.0.0.0:9229']:
            with self.subTest(command=command):
                self.filters["SynapseCTRL"]["Debugger"] = command
                result = bootstrap.inspect_bootstrap()
                self.assertIn("hook_debugger_mismatch", self.codes(result))
                self.assertFalse(result["hookHealthy"])

    def test_modified_filter_path_needs_inspection_before_repair(self):
        self.filters["SynapseCTRL"]["FilterFullPath"] = "C:\\unexpected.exe"
        result = bootstrap.inspect_bootstrap()
        self.assertIn("hook_path_mismatch", self.codes(result))
        self.assertIn("preserves unexpected values", result["repair"][0])

    def test_competing_filter_or_top_level_debugger_is_not_healthy(self):
        self.base["Debugger"] = "other-debugger.exe"
        self.filters["AnotherTool"] = dict(self.filters["SynapseCTRL"])
        result = bootstrap.inspect_bootstrap()
        self.assertEqual(self.codes(result), {"conflicting_debugger", "conflicting_filter"})

    def test_unrelated_filters_do_not_degrade_our_hook(self):
        self.filters["AnotherTool"] = {"FilterFullPath": "C:\\other\\RazerAppEngine.exe"}
        self.assertTrue(bootstrap.inspect_bootstrap()["hookHealthy"])

    def test_registry_denied_is_unknown_and_actionable_not_hook_missing(self):
        with patch.object(bootstrap, "_registry_values", side_effect=PermissionError("denied")):
            result = bootstrap.inspect_bootstrap()
        self.assertEqual(self.codes(result), {"hook_unreadable"})
        self.assertFalse(result["hookHealthy"])

    def test_missing_versioned_executable_requires_synapse_repair(self):
        for executable in self.razer.glob("app-*/*.exe"):
            executable.unlink()
        result = bootstrap.inspect_bootstrap()
        self.assertIn("synapse_not_installed", self.codes(result))
        self.assertIsNone(result["versionedLauncher"])

    def test_healthy_hook_with_stopped_synapse_explains_next_step(self):
        with patch.object(bootstrap, "synapse_running", return_value=False):
            result = bootstrap.inspect_bootstrap()
        self.assertTrue(result["hookHealthy"])
        self.assertIn("Open Razer Synapse normally", result["repair"][0])

    def test_non_windows_has_explicit_unsupported_state(self):
        with patch.object(bootstrap.sys, "platform", "linux"):
            result = bootstrap.inspect_bootstrap()
        self.assertFalse(result["supported"])
        self.assertEqual(self.codes(result), {"unsupported_platform"})


class ProcessTests(unittest.TestCase):
    def test_process_checks_never_confuse_unknown_with_stopped(self):
        with patch.object(bootstrap.sys, "platform", "win32"):
            with patch.object(psutil, "process_iter", return_value=[]):
                self.assertIs(bootstrap.synapse_running(), False)
            with patch.object(psutil, "process_iter", return_value=[SimpleNamespace(info={"name": None})]):
                self.assertIsNone(bootstrap.synapse_running())
            with patch.object(psutil, "process_iter", side_effect=psutil.AccessDenied()):
                self.assertIsNone(bootstrap.synapse_running())

    def test_process_name_match_is_exact_and_case_insensitive(self):
        names = ["RazerAppEngine.exe.bak", "RAZERAPPENGINE.EXE"]
        with patch.object(bootstrap.sys, "platform", "win32"), patch.object(
            psutil, "process_iter", return_value=[SimpleNamespace(info={"name": name}) for name in names]
        ):
            self.assertTrue(bootstrap.synapse_running())

    def test_non_windows_process_state_is_unknown(self):
        with patch.object(bootstrap.sys, "platform", "linux"):
            self.assertIsNone(bootstrap.synapse_running())


if __name__ == "__main__":
    unittest.main()
