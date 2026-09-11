"""Public, synchronous client. Reads reconnect; mutations are sent at most once."""
from __future__ import annotations

import threading
import time
from dataclasses import replace
from typing import Any, Sequence, TypeVar
from urllib.parse import urlsplit

from ._inspector import Inspector, positive_timeout, validate_endpoint
from .bootstrap import inspect_bootstrap
from .discovery import Discovery, normalize
from .errors import SynapseError
from .metadata import BACKEND_VERSION
from .models import Device, Profile, Status, SwitchResult

_Named = TypeVar("_Named", Device, Profile)


def _resolve(items: Sequence[_Named], query: str, kind: str) -> _Named:
    if not isinstance(query, str) or not query.strip():
        raise SynapseError("invalid_argument", f"Provide a nonempty {kind} ID or name.")
    q = query.strip().casefold()
    matches = [item for item in items if item.id.casefold() == q]
    if not matches:
        matches = [item for item in items if item.name.casefold() == q]
    if not matches:
        matches = [item for item in items if q in item.name.casefold()]
    if not matches:
        raise SynapseError(f"{kind}_not_found", f"No {kind} matches {query!r}.")
    if len(matches) != 1:
        raise SynapseError(f"ambiguous_{kind}", f"More than one {kind} matches {query!r}; use a stable ID.",
                           {"matches": [{"id": item.id, "name": item.name} for item in matches]})
    return matches[0]


def _sender(state: dict[str, Any]) -> int | None:
    candidates = []
    for item in state.get("renderers", []):
        try:
            url = urlsplit(str(item.get("href", "")))
            if url.scheme != "https" or url.netloc != "apps.razer.com" or item.get("error") or item.get("skipped"):
                continue
            if item.get("broadcastChannelAvailable") is not True or not isinstance(item.get("id"), int):
                continue
            candidates.append(item)
        except (ValueError, AttributeError):
            continue
    candidates.sort(key=lambda item: (item.get("windowName") != "systray-left", item["id"]))
    return candidates[0]["id"] if candidates else None


class SynapseClient:
    """Discover and control software profiles on the local Synapse installation.

    Connections are lazy. Use as a context manager or call close() when finished.
    Each operation refreshes state; IDs and renderer topology are never persisted.
    Calls on one client are serialized, including switch verification.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9229, timeout: float = 8.0):
        self.host, self.port = validate_endpoint(host, port)
        self.timeout = positive_timeout(timeout)
        self._inspector: Inspector | None = None
        self._lock = threading.RLock()
        self._state: dict[str, Any] = {}
        self._discovery = Discovery(devices=[], details={}, warnings=[])
        self._probe: dict[str, Any] = {}
        self._reachable = False

    def __enter__(self) -> SynapseClient:
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()

    def close(self) -> None:
        with self._lock:
            if self._inspector is not None:
                self._inspector.close()
                self._inspector = None

    def _read(self, *, deadline: float | None = None) -> Discovery:
        self._state = {}
        self._discovery = Discovery(devices=[], details={}, warnings=[])
        self._reachable = False
        for attempt in range(2):
            limit = self.timeout if deadline is None else min(self.timeout, deadline - time.monotonic())
            if limit <= 0:
                raise SynapseError("verification_timeout", "The profile verification deadline expired.")
            try:
                if self._inspector is None:
                    self._probe = {}
                    inspector = Inspector(self.port, limit)
                    try:
                        inspector.connect()
                    finally:
                        self._probe = inspector.probe
                        self._reachable = inspector.reachable
                    inspector.timeout = self.timeout
                    self._inspector = inspector
                if deadline is not None:
                    limit = min(self.timeout, deadline - time.monotonic())
                    if limit <= 0:
                        raise SynapseError("verification_timeout", "The profile verification deadline expired.")
                state = self._inspector.snapshot(timeout=limit)
                self._probe = self._inspector.probe
                self._reachable = True
                discovery = normalize(state)
                if _sender(state) is None:
                    reason = "No available Synapse renderer supports software-profile switching."
                    discovery.devices = [replace(device, controllable=False, unavailable_reason=reason) for device in discovery.devices]
                    discovery.warnings.append(reason)
                for item in state["renderers"]:
                    if isinstance(item, dict) and item.get("error"):
                        discovery.warnings.append(f"Renderer {item.get('id')} could not be read: {item['error']}")
                self._state = state
                self._discovery = discovery
                return discovery
            except SynapseError as error:
                self.close()
                if error.code in ("inspector_unreachable", "transport_lost"):
                    self._reachable = False
                if attempt == 0 and error.code == "transport_lost":
                    continue
                raise
        raise AssertionError("Unreachable retry state")

    def list_devices(self) -> tuple[Device, ...]:
        with self._lock:
            return tuple(self._read().devices)

    def resolve_device(self, device: str) -> Device:
        """Resolve a device ID or unambiguous name to its current Device snapshot."""
        with self._lock:
            return _resolve(self._read().devices, device, "device")

    def list_profiles(self, device: str) -> tuple[Profile, ...]:
        with self._lock:
            return _resolve(self._read().devices, device, "device").profiles

    def resolve_profile(self, device: str, profile: str) -> Profile:
        """Resolve a profile ID or unambiguous name within a selected device."""
        with self._lock:
            selected = _resolve(self._read().devices, device, "device")
            return _resolve(selected.profiles, profile, "profile")

    def switch_profile(self, device: str, profile: str, *, timeout: float = 5.0, verify: bool = True) -> SwitchResult:
        """Send once, optionally verify. A timeout never implies a successful switch.

        Selection/availability errors raise SynapseError before dispatch. Once
        dispatch starts, outcomes (including uncertain failures) are SwitchResult.
        timeout bounds verification after dispatch, separate from connection I/O.
        """
        timeout = positive_timeout(timeout, "verification timeout")
        if not isinstance(verify, bool):
            raise SynapseError("invalid_argument", "verify must be a boolean.")
        with self._lock:
            started = time.monotonic()
            discovery = self._read()
            selected = _resolve(discovery.devices, device, "device")
            target = _resolve(selected.profiles, profile, "profile")
            if not selected.controllable:
                raise SynapseError("device_unavailable", selected.unavailable_reason or "This device cannot currently be controlled.", {"deviceId": selected.id})
            previous = selected.active_profile_id

            def result(status: str, sent: bool, verified: bool, error: SynapseError | None = None) -> SwitchResult:
                return SwitchResult(status, selected.id, target.id, previous, sent, verified,
                                    round((time.monotonic() - started) * 1000), error.to_dict() if error else None)

            if previous and previous.casefold() == target.id.casefold():
                return result("already_active", False, True)
            details = discovery.details[selected.id]
            sender = _sender(self._state)
            if sender is None or self._inspector is None or not details.get("channel"):
                raise SynapseError("device_unavailable", "No available route to the selected Synapse device.")
            try:
                sent = self._inspector.send_switch(details["channel"], selected.container_id, target.id, sender)
            except SynapseError as error:
                self.close()
                return result("failed", False, False, SynapseError(error.code, error.message,
                              {**error.details, "deliveryUnknown": True, "retry": "Read the current profile before retrying; this request may have been delivered."}))
            if not sent:
                return result("failed", False, False, SynapseError("switch_failed", "Synapse did not acknowledge dispatching the profile messages.",
                              {"deliveryUnknown": True, "retry": "Read the current profile before retrying; this request may have been delivered."}))
            if not verify:
                return result("sent", True, False)
            deadline = time.monotonic() + timeout
            last_error = None
            while time.monotonic() < deadline:
                try:
                    refreshed = self._read(deadline=deadline)
                    if time.monotonic() >= deadline:
                        break
                    current = next((d for d in refreshed.devices if d.id == selected.id), None)
                    if current and current.controllable and current.active_profile_id and current.active_profile_id.casefold() == target.id.casefold():
                        return result("verified", True, True)
                    if current is None:
                        last_error = "The selected device is no longer discovered."
                    elif not current.controllable:
                        last_error = current.unavailable_reason
                except SynapseError as error:
                    last_error = error.message
                remaining = deadline - time.monotonic()
                if remaining > 0:
                    time.sleep(min(0.2, remaining))
            return result("timeout", True, False, SynapseError("verification_timeout", "The request was sent, but the active profile was not verified before the deadline.",
                          {"lastIssue": last_error} if last_error else None))

    def _status(self, bootstrap: dict[str, Any]) -> Status:
        issues: list[str] = []
        repair: list[str] = []
        available = True
        try:
            discovery = self._read()
            issues.extend(discovery.warnings)
            issues.extend(d.unavailable_reason for d in discovery.devices if d.unavailable_reason)
            if not discovery.devices:
                issues.append("No supported device middleware was discovered; connect a device and allow Synapse to finish loading.")
            if issues:
                repair.append("Run synapsectrl doctor and inspect the supplied astra/tools diagnostics if discovery changed after a Synapse update.")
        except SynapseError as error:
            available = False
            issues.append(error.message)
            if not bootstrap.get("synapseRunning"):
                repair.append("Start Razer Synapse using its normal shortcut.")
            elif error.code in ("transport_lost", "inspector_unreachable"):
                repair.append("Restart Synapse using its normal shortcut so the installed inspector hook takes effect.")
            else:
                repair.append("Run the supplied astra/tools/probe.py and diagnostic_bundle.py to diagnose a changed Synapse integration.")

        for item in bootstrap.get("issues", []):
            message = item.get("message") if isinstance(item, dict) else str(item)
            if message:
                issues.append(message)
        repair.extend(bootstrap.get("repair", []))
        if not bootstrap.get("hookHealthy"):
            repair.append("Run 'synapsectrl hook repair' to install the hook build expected by this SynapseCTRL backend.")

        devices = self._discovery.devices
        controllable = sum(d.controllable for d in devices)
        versions = dict(self._probe.get("versions") or {})
        versions["synapseCtrl"] = BACKEND_VERSION
        metadata_versions = {
            "hook": bootstrap.get("hookVersion"),
            "hookExpected": bootstrap.get("expectedHookVersion"),
            "hookProtocol": bootstrap.get("hookProtocolVersion"),
            "hookProtocolExpected": bootstrap.get("expectedHookProtocolVersion"),
            "hookBuild": bootstrap.get("hookBuildId"),
            "hookExpectedBuild": bootstrap.get("expectedHookBuildId"),
            "hookInstalledBy": bootstrap.get("installedByVersion"),
        }
        versions.update({key: str(value) for key, value in metadata_versions.items() if value is not None})
        return Status(
            state=("ready" if not issues else "degraded") if available else "unavailable",
            synapse_running=True if available else bootstrap.get("synapseRunning"),
            inspector_reachable=self._reachable,
            browser_process=self._probe.get("processType") == "browser",
            electron_available=bool(self._probe.get("electronAvailable")),
            device_count=len(devices), controllable_device_count=controllable,
            versions=versions, issues=tuple(dict.fromkeys(issues)), repair=tuple(dict.fromkeys(repair)),
        )

    def status(self) -> Status:
        with self._lock:
            return self._status(inspect_bootstrap())

    def diagnostics(self) -> dict[str, Any]:
        """Compact developer diagnostics, without full storage or an eval surface."""
        with self._lock:
            bootstrap = inspect_bootstrap()
            status = self._status(bootstrap)
            return {
                "status": status.to_dict(), "bootstrap": bootstrap,
                "capabilities": dict(self._probe),
                "renderers": [{key: value for key, value in item.items() if key != "values"}
                              for item in self._state.get("renderers", []) if isinstance(item, dict)],
                "rendererCount": self._state.get("webContentsCount", 0),
                "storageKeys": sorted({key for item in self._state.get("renderers", []) if isinstance(item, dict)
                                       and isinstance(item.get("keys"), list) for key in item["keys"] if isinstance(key, str)}),
                "devices": [device.to_dict() for device in self._discovery.devices],
                "deviceDetails": self._discovery.details,
                "warnings": self._discovery.warnings,
            }
