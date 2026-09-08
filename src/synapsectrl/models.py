"""Immutable public results. JSON uses a stable camelCase vocabulary."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal


@dataclass(frozen=True)
class Profile:
    id: str
    name: str
    active: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "active": self.active}


@dataclass(frozen=True)
class Device:
    id: str
    name: str
    vendor_id: int
    product_id: int
    container_id: str
    serial_number: str | None = None
    connected: bool = True
    profiles_supported: bool = True
    controllable: bool = True
    unavailable_reason: str | None = None
    active_profile_id: str | None = None
    profiles: tuple[Profile, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name,
            "vendorId": self.vendor_id, "productId": self.product_id,
            "containerId": self.container_id, "serialNumber": self.serial_number,
            "connected": self.connected, "profilesSupported": self.profiles_supported,
            "controllable": self.controllable, "unavailableReason": self.unavailable_reason,
            "activeProfileId": self.active_profile_id,
            "profiles": [profile.to_dict() for profile in self.profiles],
        }


@dataclass(frozen=True)
class SwitchResult:
    status: Literal["verified", "sent", "already_active", "timeout", "failed"]
    device_id: str
    profile_id: str
    previous_profile_id: str | None
    sent: bool
    verified: bool
    elapsed_ms: int
    error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status, "deviceId": self.device_id,
            "profileId": self.profile_id, "previousProfileId": self.previous_profile_id,
            "sent": self.sent, "verified": self.verified,
            "elapsedMs": self.elapsed_ms, "error": self.error,
        }


@dataclass(frozen=True)
class Status:
    state: Literal["ready", "degraded", "unavailable"]
    synapse_running: bool | None
    inspector_reachable: bool
    browser_process: bool
    electron_available: bool
    device_count: int
    controllable_device_count: int
    versions: dict[str, str] = field(default_factory=dict)
    issues: tuple[str, ...] = ()
    repair: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "state": self.state, "synapseRunning": self.synapse_running,
            "inspectorReachable": self.inspector_reachable,
            "browserProcess": self.browser_process, "electronAvailable": self.electron_available,
            "deviceCount": self.device_count, "controllableDeviceCount": self.controllable_device_count,
            "versions": dict(self.versions), "issues": list(self.issues), "repair": list(self.repair),
        }
