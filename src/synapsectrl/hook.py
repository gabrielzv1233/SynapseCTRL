"""Install, repair, inspect, or remove the packaged Synapse launch hook."""

from __future__ import annotations

from importlib.resources import as_file, files
import os
from pathlib import Path
import subprocess
import sys
from typing import Any

from .bootstrap import inspect_bootstrap
from .errors import SynapseError


def _powershell_executable() -> str:
    system_root = os.environ.get("SystemRoot")
    if system_root:
        candidate = (
            Path(system_root)
            / "System32"
            / "WindowsPowerShell"
            / "v1.0"
            / "powershell.exe"
        )
        if candidate.is_file():
            return str(candidate)
    return "powershell.exe"


def run_hook_installer(action: str) -> dict[str, Any]:
    """Run the packaged PowerShell hook installer and return structured results."""
    if action not in {"install", "repair", "uninstall"}:
        raise SynapseError("invalid_argument", f"Unknown hook action: {action}")
    if sys.platform != "win32":
        raise SynapseError(
            "unsupported_platform",
            "The Synapse launch hook can only be installed or removed on Windows.",
        )

    resource = files("synapsectrl").joinpath("Install-SynapseInspectHook.ps1")
    if not resource.is_file():
        raise SynapseError(
            "installer_missing",
            "The packaged Synapse hook installer is missing. Reinstall SynapseCTRL.",
        )

    with as_file(resource) as script:
        command = [
            _powershell_executable(),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(script),
            "-NoPause",
        ]
        if action == "uninstall":
            command.append("-Uninstall")
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
        except OSError as exc:
            raise SynapseError(
                "hook_operation_failed",
                f"Could not start the Synapse hook installer: {exc}",
            ) from exc

    stdout = completed.stdout.strip()
    stderr = completed.stderr.strip()
    details = {
        "action": action,
        "exitCode": completed.returncode,
        "stdout": stdout or None,
        "stderr": stderr or None,
    }
    if completed.returncode != 0:
        raise SynapseError(
            "hook_operation_failed",
            f"Synapse hook {action} failed with exit code {completed.returncode}.",
            details,
        )

    return {**details, "bootstrap": inspect_bootstrap()}
