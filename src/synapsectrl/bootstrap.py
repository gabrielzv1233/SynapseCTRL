"""Read-only health checks for the Windows launch hook.

Inspector capability checks belong to the client. This module reports whether
the next ordinary Synapse launch can use the installed native bootstrap.
"""

from __future__ import annotations

import ntpath
import os
from pathlib import Path
import re
import sys
from typing import Any

import psutil

from .metadata import (
    BACKEND_VERSION,
    HOOK_PROTOCOL_VERSION,
    HOOK_VERSION,
    expected_hook_fingerprint,
    hook_build_id,
)

try:
    import winreg
except ImportError:  # Allows installation and offline tests on other platforms.
    winreg = None  # type: ignore[assignment]


_IFEO = r"SOFTWARE\Microsoft\Windows NT\CurrentVersion\Image File Execution Options\RazerAppEngine.exe"
_REPAIR = (
    "Run 'synapsectrl hook repair' (Windows requests administrator access), then fully exit "
    "and reopen Synapse. From a source checkout, use 'uv run synapsectrl hook repair'."
)


def synapse_running() -> bool | None:
    """Return whether RazerAppEngine is running; None means not observable."""
    if sys.platform != "win32":
        return None
    uncertain = False
    try:
        for process in psutil.process_iter(["name"], ad_value=None):
            try:
                name = process.info.get("name")
                if name is None:
                    uncertain = True
                elif name.casefold() == "razerappengine.exe":
                    return True
            except psutil.AccessDenied:
                uncertain = True
            except psutil.NoSuchProcess:
                continue
    except (psutil.Error, OSError):
        return None
    return None if uncertain else False


def _registry_values(path: str) -> dict[str, Any] | None:
    """Read the 64-bit IFEO view without requesting any write permissions."""
    assert winreg is not None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, path, 0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            return {
                name: value
                for name, value, _ in (
                    winreg.EnumValue(key, index)
                    for index in range(winreg.QueryInfoKey(key)[1])
                )
            }
    except FileNotFoundError:
        return None


def _registry_filters() -> dict[str, dict[str, Any]]:
    assert winreg is not None
    try:
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE, _IFEO, 0,
            winreg.KEY_READ | winreg.KEY_WOW64_64KEY,
        ) as key:
            names = [winreg.EnumKey(key, i) for i in range(winreg.QueryInfoKey(key)[0])]
        return {name: _registry_values(_IFEO + "\\" + name) or {} for name in names}
    except FileNotFoundError:
        return {}


def _same_path(left: Any, right: str | Path) -> bool:
    return isinstance(left, str) and ntpath.normcase(ntpath.normpath(left)) == ntpath.normcase(
        ntpath.normpath(str(right))
    )


def _newest_versioned_exe(root: Path) -> Path | None:
    candidates = []
    for directory in root.glob("app-*"):
        suffix = directory.name[4:]
        if not re.fullmatch(r"\d+\.\d+(?:\.\d+){0,2}", suffix):
            continue
        executable = directory / "RazerAppEngine.exe"
        if executable.is_file():
            # System.Version compares omitted build/revision components as -1.
            parts = tuple(int(part) for part in suffix.split("."))
            candidates.append((parts + (-1,) * (4 - len(parts)), executable))
    return max(candidates, key=lambda item: item[0])[1] if candidates else None


def inspect_bootstrap() -> dict[str, Any]:
    """Return JSON-compatible hook health and actionable local repair advice."""
    try:
        expected_fingerprint = expected_hook_fingerprint()
    except OSError:
        expected_fingerprint = None

    result: dict[str, Any] = {
        "supported": sys.platform == "win32" and winreg is not None,
        "backendVersion": BACKEND_VERSION,
        "synapseRunning": synapse_running(),
        "stableLauncherExists": False,
        "versionedLauncher": None,
        "hookInstalled": False,
        "hookHealthy": False,
        "hookCurrent": False,
        "hookVersion": None,
        "expectedHookVersion": HOOK_VERSION,
        "hookProtocolVersion": None,
        "expectedHookProtocolVersion": HOOK_PROTOCOL_VERSION,
        "hookFingerprint": None,
        "expectedHookFingerprint": expected_fingerprint,
        "hookBuildId": None,
        "expectedHookBuildId": hook_build_id(HOOK_VERSION, expected_fingerprint),
        "installedByVersion": None,
        "installedAtUtc": None,
        "useFilter": None,
        "filterFullPath": None,
        "debugger": None,
        "shimExists": False,
        "issues": [],
        "repair": [],
    }

    def issue(code: str, message: str, repair: str | None = None) -> None:
        result["issues"].append({"code": code, "message": message})
        if repair and repair not in result["repair"]:
            result["repair"].append(repair)

    if expected_fingerprint is None:
        issue(
            "hook_metadata_unavailable",
            "SynapseCTRL cannot read its packaged hook implementation to determine the expected build.",
            "Reinstall SynapseCTRL before repairing the launch hook.",
        )

    if not result["supported"]:
        issue("unsupported_platform", "Automatic Synapse launch requires Windows.")
        return result

    program_files = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles")
    if not program_files:
        issue("installation_path_unknown", "Windows Program Files location is unavailable.")
        return result

    root = Path(program_files) / "Razer" / "RazerAppEngine"
    stable = root / "RazerAppEngine.exe"
    shim = Path(program_files) / "SynapseCTRL" / "RazerInspectShim.exe"
    try:
        result["stableLauncherExists"] = stable.is_file()
        result["shimExists"] = shim.is_file()
        versioned = _newest_versioned_exe(root)
        result["versionedLauncher"] = str(versioned) if versioned else None
    except OSError as exc:
        issue("installation_unreadable", f"Cannot inspect the Synapse installation: {exc}")
        return result
    if not result["stableLauncherExists"] or not result["versionedLauncher"]:
        issue("synapse_not_installed", "The stable launcher or a numeric app-* installation is missing.",
              "Install or repair Razer Synapse 4, then install the SynapseCTRL launch hook.")

    try:
        base = _registry_values(_IFEO) or {}
        filters = _registry_filters()
    except OSError as exc:
        issue("hook_unreadable", f"Cannot read the Windows launch hook: {exc}",
              "Check read access to the RazerAppEngine.exe Image File Execution Options registry key.")
        return result
    own = next((value for name, value in filters.items() if name.casefold() == "synapsectrl"), None)
    result["useFilter"] = base.get("UseFilter")
    if base.get("Debugger"):
        issue("conflicting_debugger", "A non-filtered debugger is configured for RazerAppEngine.exe.",
              "Resolve the existing non-filtered debugger before installing the SynapseCTRL hook.")
    for name, values in filters.items():
        if name.casefold() != "synapsectrl" and _same_path(values.get("FilterFullPath"), stable):
            issue("conflicting_filter", f"Another launch filter targets Synapse: {name}.",
                  "Resolve the competing launch filter before repairing the SynapseCTRL hook.")
    if own is None:
        issue("hook_missing", "The automatic inspector launch hook is not installed.", _REPAIR)
    else:
        hook_version = own.get("HookVersion")
        hook_protocol = own.get("HookProtocolVersion")
        hook_fingerprint = own.get("HookFingerprint")
        installed_by = own.get("InstalledByVersion")
        installed_at = own.get("InstalledAtUtc")
        result.update({
            "hookInstalled": True,
            "hookVersion": hook_version,
            "hookProtocolVersion": hook_protocol,
            "hookFingerprint": hook_fingerprint,
            "hookBuildId": hook_build_id(
                hook_version if isinstance(hook_version, int) else None,
                hook_fingerprint if isinstance(hook_fingerprint, str) else None,
            ),
            "installedByVersion": installed_by,
            "installedAtUtc": installed_at,
            "filterFullPath": own.get("FilterFullPath"),
            "debugger": own.get("Debugger"),
        })
        if base.get("UseFilter") != 1:
            issue("hook_disabled", "Windows filtered launch hooks are disabled.", _REPAIR)
        if not _same_path(own.get("FilterFullPath"), stable):
            issue("hook_path_mismatch", "The hook does not target the stable Synapse launcher.",
                  "Inspect the modified SynapseCTRL IFEO filter before repairing it; the installer preserves unexpected values.")
        debugger = own.get("Debugger")
        # Exact executable-only command: no arguments, shell, or unquoted spaces.
        if not isinstance(debugger, str) or debugger.casefold() != f'"{shim}"'.casefold():
            issue("hook_debugger_mismatch", "The hook debugger is not the expected quoted native shim.",
                  "Inspect the modified SynapseCTRL IFEO filter before repairing it; the installer preserves unexpected values.")
        if not result["shimExists"]:
            issue("shim_missing", "The registered native launch shim is missing.", _REPAIR)

        if not isinstance(hook_version, int):
            issue(
                "hook_metadata_missing",
                "The installed hook predates managed version metadata.",
                _REPAIR,
            )
        elif hook_version < HOOK_VERSION:
            issue(
                "hook_outdated",
                f"Installed hook v{hook_version} is older than the v{HOOK_VERSION} build expected by SynapseCTRL {BACKEND_VERSION}.",
                _REPAIR,
            )
        elif hook_version > HOOK_VERSION:
            issue(
                "backend_outdated",
                f"Installed hook v{hook_version} is newer than the v{HOOK_VERSION} build expected by SynapseCTRL {BACKEND_VERSION}.",
                "Upgrade SynapseCTRL before changing the installed hook.",
            )
        elif not isinstance(hook_protocol, int):
            issue("hook_metadata_missing", "The installed hook is missing protocol-version metadata.", _REPAIR)
        elif hook_protocol != HOOK_PROTOCOL_VERSION:
            if hook_protocol > HOOK_PROTOCOL_VERSION:
                repair = "Upgrade SynapseCTRL before changing the installed hook."
            else:
                repair = _REPAIR
            issue(
                "hook_protocol_mismatch",
                f"Installed hook protocol v{hook_protocol} does not match backend protocol v{HOOK_PROTOCOL_VERSION}.",
                repair,
            )
        elif not isinstance(hook_fingerprint, str) or not re.fullmatch(r"[0-9a-fA-F]{64}", hook_fingerprint):
            issue("hook_metadata_missing", "The installed hook is missing its exact build fingerprint.", _REPAIR)
        elif expected_fingerprint is not None and hook_fingerprint.casefold() != expected_fingerprint.casefold():
            issue(
                "hook_build_mismatch",
                "The installed hook build does not match the hook code packaged with this SynapseCTRL backend.",
                _REPAIR,
            )
        elif not isinstance(installed_by, str) or not installed_by.strip():
            issue("hook_metadata_missing", "The installed hook is missing its installer/backend version metadata.", _REPAIR)
        else:
            result["hookCurrent"] = True

    result["hookHealthy"] = not result["issues"]
    if result["hookHealthy"] and result["synapseRunning"] is False:
        result["repair"].append("Open Razer Synapse normally; the installed hook enables the inspector automatically.")
    return result
