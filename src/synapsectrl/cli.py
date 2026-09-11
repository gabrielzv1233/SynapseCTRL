"""Noninteractive command line interface for the SynapseCTRL SDK."""

from __future__ import annotations

import argparse
import json
import math
import os
from pathlib import Path
import sys
import tempfile
from typing import Any, Sequence

from . import __version__
from .bootstrap import inspect_bootstrap
from .client import SynapseClient
from .errors import SynapseError
from .hook import run_hook_installer


API_VERSION = "1"
_USAGE_CODES = {
    "invalid_argument", "device_not_found", "profile_not_found",
    "ambiguous_device", "ambiguous_profile",
}


class _UsageError(Exception):
    pass


class _Parser(argparse.ArgumentParser):
    def error(self, message: str) -> None:
        raise _UsageError(message)


def _positive_seconds(value: str) -> float:
    try:
        result = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be a positive number of seconds") from exc
    if not math.isfinite(result) or result <= 0:
        raise argparse.ArgumentTypeError("must be a finite number greater than zero")
    return result


def _port(value: str) -> int:
    try:
        result = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer between 1 and 65535") from exc
    if not 1 <= result <= 65535:
        raise argparse.ArgumentTypeError("must be between 1 and 65535")
    return result


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="synapsectrl",
        description="Discover Razer Synapse 4 devices and switch software profiles locally.",
        epilog=("Use stable IDs in scripts. Names are accepted when unambiguous. "
                "Run 'synapsectrl doctor' if Synapse is unavailable."),
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    parser.add_argument("--json", action="store_true", help="emit one versioned JSON object")
    parser.add_argument("--port", type=_port, default=9229, help="loopback inspector port (default: 9229)")
    parser.add_argument(
        "--timeout", "--connect-timeout", dest="connect_timeout", type=_positive_seconds,
        default=8.0, metavar="SECONDS", help="inspector operation timeout (default: 8)",
    )
    commands = parser.add_subparsers(dest="command", required=True, metavar="COMMAND")

    def command(name: str, help_text: str) -> argparse.ArgumentParser:
        sub = commands.add_parser(name, help=help_text, description=help_text)
        sub.add_argument("--json", action="store_true", default=argparse.SUPPRESS,
                         help="emit one versioned JSON object")
        sub.add_argument("--port", type=_port, default=argparse.SUPPRESS,
                         help="loopback inspector port")
        sub.add_argument("--connect-timeout", dest="connect_timeout", type=_positive_seconds,
                         default=argparse.SUPPRESS, metavar="SECONDS",
                         help="inspector operation timeout")
        return sub

    command("status", "Check Synapse availability and profile-control readiness.")
    command("devices", "List devices, stable IDs, and active profiles.")
    profiles = command("profiles", "List software profiles for one device.")
    profiles.add_argument("device", metavar="DEVICE", help="stable device ID or unambiguous name")
    resolve = command("resolve", "Resolve a device or profile selector to its current object.")
    resolve.add_argument("kind", choices=("device", "profile"), metavar="KIND",
                         help="object kind: device or profile")
    resolve.add_argument("device", metavar="DEVICE", help="device ID or unambiguous name")
    resolve.add_argument("profile", nargs="?", metavar="PROFILE",
                         help="profile GUID or unambiguous name when KIND is profile")
    switch = command("switch", "Switch a device's software profile and verify active state.")
    switch.add_argument("device", metavar="DEVICE", help="stable device ID or unambiguous name")
    switch.add_argument("profile", metavar="PROFILE", help="profile GUID or unambiguous name")
    switch.add_argument("--timeout", dest="switch_timeout", type=_positive_seconds, default=5.0,
                        metavar="SECONDS", help="verification deadline (default: 5)")
    switch.add_argument("--no-verify", action="store_true",
                        help="return after sending; does not confirm the active profile")
    doctor = command("doctor", "Inspect connection, device discovery, and automatic launch setup.")
    doctor.add_argument("--out", type=Path, metavar="FILE",
                        help="also save the JSON diagnostic report to FILE")
    hook = command("hook", "Install, inspect, repair, or remove the automatic Synapse launch hook.")
    hook.add_argument(
        "action", choices=("install", "status", "repair", "uninstall"), metavar="ACTION",
        help="hook action: install, status, repair, or uninstall",
    )
    return parser


def _envelope(data: Any) -> dict[str, Any]:
    return {"apiVersion": API_VERSION, "data": data}


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False)


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    """Keep an existing report intact when serialization or writing fails."""
    content = _json(payload) + "\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=f".{path.name}.", suffix=".tmp", delete=False,
        ) as output:
            temporary = Path(output.name)
            output.write(content)
        os.replace(temporary, path)
        temporary = None
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


def _yes_no(value: Any) -> str:
    return "unknown" if value is None else "yes" if value else "no"


def _status_lines(status: dict[str, Any]) -> list[str]:
    lines = [
        f"SynapseCTRL: {status.get('state', 'unknown')}",
        f"  Synapse running: {_yes_no(status.get('synapseRunning'))}",
        f"  Inspector reachable: {_yes_no(status.get('inspectorReachable'))}",
        f"  Electron browser available: {_yes_no(status.get('browserProcess') and status.get('electronAvailable'))}",
        f"  Devices: {status.get('deviceCount', 0)} ({status.get('controllableDeviceCount', 0)} controllable)",
    ]
    versions = status.get("versions") or {}
    backend = versions.get("synapseCtrl")
    if backend:
        lines.append(f"  Backend: SynapseCTRL {backend}")
    hook_build = versions.get("hookBuild")
    hook_version = versions.get("hook")
    expected_build = versions.get("hookExpectedBuild")
    expected_version = versions.get("hookExpected")
    if hook_build or hook_version:
        installed = hook_build or f"v{hook_version}"
        expected = expected_build or (f"v{expected_version}" if expected_version else None)
        suffix = " (current)" if expected and installed == expected else f" (expected {expected})" if expected else ""
        lines.append(f"  Hook: {installed}{suffix}")
    elif expected_build or expected_version:
        expected = expected_build or f"v{expected_version}"
        lines.append(f"  Hook: not installed (expected {expected})")
    hook_protocol = versions.get("hookProtocol")
    expected_protocol = versions.get("hookProtocolExpected")
    if hook_protocol or expected_protocol:
        current = hook_protocol or "missing"
        suffix = f" (expected v{expected_protocol})" if expected_protocol and current != expected_protocol else ""
        lines.append(f"  Hook protocol: v{current}{suffix}" if current != "missing" else f"  Hook protocol: missing (expected v{expected_protocol})")
    runtime_versions = [(key, versions[key]) for key in ("appEngine", "electron", "chrome", "node") if key in versions]
    if runtime_versions:
        lines.append("  Runtime versions: " + ", ".join(f"{key} {value}" for key, value in runtime_versions))
    issues = status.get("issues") or []
    if issues:
        lines.extend(["", "Issues:", *(f"  - {issue}" for issue in issues)])
    repairs = status.get("repair") or []
    if repairs:
        lines.extend(["", "Next steps:", *(f"  - {step}" for step in repairs)])
    return lines


def _device_lines(devices: list[dict[str, Any]]) -> list[str]:
    if not devices:
        return ["No Synapse devices discovered. Run 'synapsectrl doctor' for details."]
    lines: list[str] = []
    for device in devices:
        if lines:
            lines.append("")
        profiles = device.get("profiles") or []
        active_id = device.get("activeProfileId")
        active = next((profile for profile in profiles if profile["id"] == active_id), None)
        active_text = f"{active['name']} [{active['id']}]" if active else active_id or "unknown"
        state = "ready" if device.get("controllable") else device.get("unavailableReason") or "unavailable"
        lines.extend([
            device["name"],
            f"  ID: {device['id']}",
            f"  Connected: {_yes_no(device.get('connected'))} | Control: {state}",
            f"  Profiles: {len(profiles)} | Active: {active_text}",
        ])
        if device.get("serialNumber"):
            lines.append(f"  Serial: {device['serialNumber']}")
    return lines


def _profile_lines(profiles: list[dict[str, Any]]) -> list[str]:
    if not profiles:
        return ["No software profiles are available for this device."]
    return [
        *(f"{'*' if profile.get('active') else ' '} {profile['name']} [{profile['id']}]" for profile in profiles),
        "", "* active profile",
    ]


def _resolved_lines(kind: str, item: dict[str, Any]) -> list[str]:
    lines = [f"{kind.title()}: {item['name']}", f"  ID: {item['id']}"]
    if kind == "profile":
        lines.append(f"  Active: {_yes_no(item.get('active'))}")
    return lines


def _switch_lines(result: dict[str, Any]) -> list[str]:
    messages = {
        "verified": "Profile switch verified.",
        "already_active": "Profile is already active.",
        "sent": "Switch request sent. Active state was not verified.",
        "timeout": "Switch request sent, but active state was not verified before the deadline.",
        "failed": "Profile switch failed.",
    }
    lines = [
        messages.get(result["status"], f"Switch result: {result['status']}"),
        f"  Device: {result['deviceId']}",
        f"  Profile: {result['profileId']}",
        f"  Elapsed: {result['elapsedMs']} ms",
    ]
    error = result.get("error")
    if error:
        lines.append(f"  {error.get('code', 'error')}: {error.get('message', '')}")
    return lines


def _hook_metadata_lines(bootstrap: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    backend = bootstrap.get("backendVersion")
    if backend:
        lines.append(f"  Backend: SynapseCTRL {backend}")
    build = bootstrap.get("hookBuildId")
    version = bootstrap.get("hookVersion")
    expected_build = bootstrap.get("expectedHookBuildId")
    expected_version = bootstrap.get("expectedHookVersion")
    if build or version is not None:
        installed = build or f"v{version}"
        expected = expected_build or (f"v{expected_version}" if expected_version is not None else None)
        suffix = " (current)" if bootstrap.get("hookCurrent") else f" (expected {expected})" if expected else ""
        lines.append(f"  Hook build: {installed}{suffix}")
    elif expected_build or expected_version is not None:
        expected = expected_build or f"v{expected_version}"
        lines.append(f"  Hook build: not installed (expected {expected})")
    protocol = bootstrap.get("hookProtocolVersion")
    expected_protocol = bootstrap.get("expectedHookProtocolVersion")
    if protocol is not None or expected_protocol is not None:
        value = f"v{protocol}" if protocol is not None else "missing"
        suffix = "" if protocol == expected_protocol else f" (expected v{expected_protocol})"
        lines.append(f"  Hook protocol: {value}{suffix}")
    if bootstrap.get("installedByVersion"):
        lines.append(f"  Installed by: SynapseCTRL {bootstrap['installedByVersion']}")
    if bootstrap.get("installedAtUtc"):
        lines.append(f"  Installed at: {bootstrap['installedAtUtc']}")
    return lines


def _doctor_lines(report: dict[str, Any], path: Path | None) -> list[str]:
    status = report.get("status") or {}
    lines = _status_lines(status)
    bootstrap = report.get("bootstrap")
    if isinstance(bootstrap, dict):
        lines.extend(["", "Automatic launch:"])
        if not bootstrap.get("supported", True):
            lines.append("  Requires Windows.")
        else:
            state = "healthy" if bootstrap.get("hookHealthy") else "needs repair" if bootstrap.get("hookInstalled") else "not installed"
            lines.append(f"  Launch hook: {state}")
            lines.extend(_hook_metadata_lines(bootstrap))
            if bootstrap.get("versionedLauncher"):
                lines.append(f"  App Engine: {bootstrap['versionedLauncher']}")
        for issue in bootstrap.get("issues") or []:
            lines.append(f"  - {issue.get('message', '')}" if isinstance(issue, dict) else f"  - {issue}")
        for step in bootstrap.get("repair") or []:
            lines.append(f"  Next step: {step}")
    renderers = report.get("renderers")
    if isinstance(renderers, list):
        lines.extend(["", f"Renderers discovered: {len(renderers)}"])
    if path is not None:
        lines.extend(["", f"Diagnostic report saved to {path}"])
    else:
        lines.extend(["", "Use 'synapsectrl doctor --json' for the full report or '--out FILE' to save it."])
    return lines


def _hook_lines(data: dict[str, Any]) -> list[str]:
    action = data.get("action", "status")
    bootstrap = data.get("bootstrap") or {}
    if action == "uninstall":
        lines = ["SynapseCTRL launch hook removed."]
    elif action in {"install", "repair"}:
        state = "healthy" if bootstrap.get("hookHealthy") else "installed but needs attention"
        lines = [f"SynapseCTRL launch hook {action} completed: {state}."]
    else:
        state = "healthy" if bootstrap.get("hookHealthy") else "needs repair" if bootstrap.get("hookInstalled") else "not installed"
        lines = [f"SynapseCTRL launch hook: {state}."]

    lines.extend(_hook_metadata_lines(bootstrap))
    if bootstrap.get("versionedLauncher"):
        lines.append(f"  App Engine: {bootstrap['versionedLauncher']}")
    for issue in bootstrap.get("issues") or []:
        message = issue.get("message", "") if isinstance(issue, dict) else str(issue)
        if message:
            lines.append(f"  - {message}")
    stdout = data.get("stdout")
    stderr = data.get("stderr")
    if stdout:
        lines.extend(["", "Installer output:", *stdout.splitlines()])
    if stderr:
        lines.extend(["", "Installer errors:", *stderr.splitlines()])
    if action in {"install", "repair", "uninstall"}:
        lines.extend(["", "Fully exit and reopen Razer Synapse to apply the launch change."])
    return lines


def _error(error: dict[str, Any], json_output: bool) -> None:
    if json_output:
        print(_json({"apiVersion": API_VERSION, "error": error}))
    else:
        print(f"Error [{error['code']}]: {error['message']}", file=sys.stderr)
        details = error.get("details")
        if details:
            print(_json(details), file=sys.stderr)


def main(argv: Sequence[str] | None = None) -> int:
    """Run one command and return its exit status (no interactive prompts)."""
    arguments = list(sys.argv[1:] if argv is None else argv)
    json_output = "--json" in arguments
    try:
        args = build_parser().parse_args(arguments)
        json_output = args.json
        if args.command == "hook":
            if args.action == "status":
                bootstrap = inspect_bootstrap()
                data = {"action": "status", "bootstrap": bootstrap}
                exit_code = 0 if bootstrap.get("hookHealthy") else 1
            else:
                data = run_hook_installer(args.action)
                bootstrap = data.get("bootstrap") or {}
                exit_code = 0 if args.action == "uninstall" or bootstrap.get("hookHealthy") else 1
            lines = _hook_lines(data)
            print(_json(_envelope(data)) if json_output else "\n".join(lines))
            return exit_code

        with SynapseClient(port=args.port, timeout=args.connect_timeout) as client:
            if args.command == "status":
                data = client.status().to_dict()
                lines = _status_lines(data)
                exit_code = 0 if data["state"] == "ready" else 1
            elif args.command == "devices":
                data = [device.to_dict() for device in client.list_devices()]
                lines = _device_lines(data)
                exit_code = 0
            elif args.command == "profiles":
                data = [profile.to_dict() for profile in client.list_profiles(args.device)]
                lines = _profile_lines(data)
                exit_code = 0
            elif args.command == "resolve":
                if args.kind == "device":
                    if args.profile is not None:
                        raise _UsageError("resolve device accepts exactly one DEVICE selector.")
                    data = client.resolve_device(args.device).to_dict()
                else:
                    if args.profile is None:
                        raise _UsageError("resolve profile requires DEVICE and PROFILE selectors.")
                    data = client.resolve_profile(args.device, args.profile).to_dict()
                lines = _resolved_lines(args.kind, data)
                exit_code = 0
            elif args.command == "switch":
                data = client.switch_profile(
                    args.device, args.profile, timeout=args.switch_timeout,
                    verify=not args.no_verify,
                ).to_dict()
                lines = _switch_lines(data)
                exit_code = 3 if data["status"] == "timeout" else 1 if data["status"] == "failed" else 0
            else:
                data = client.diagnostics()
                if args.out is not None:
                    _write_report(args.out, _envelope(data))
                lines = _doctor_lines(data, args.out)
                exit_code = 0 if data.get("status", {}).get("state") == "ready" else 1
        print(_json(_envelope(data)) if json_output else "\n".join(lines))
        return exit_code
    except _UsageError as exc:
        _error({"code": "invalid_argument", "message": str(exc), "details": None}, json_output)
        if not json_output:
            print("Run 'synapsectrl --help' for usage.", file=sys.stderr)
        return 2
    except SynapseError as exc:
        _error(exc.to_dict(), json_output)
        return 2 if exc.code in _USAGE_CODES else 3 if exc.code == "verification_timeout" else 1
    except KeyboardInterrupt:
        _error({"code": "interrupted", "message": "Command interrupted.", "details": None}, json_output)
        return 130
    except OSError as exc:
        _error({"code": "io_error", "message": str(exc), "details": None}, json_output)
        return 1


def entrypoint() -> None:
    """Use UTF-8 for real CLI streams, including redirected Windows output."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")
    raise SystemExit(main())
