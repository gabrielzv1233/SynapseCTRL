"""Version metadata for the SynapseCTRL backend and installed launch hook."""

from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
from importlib.metadata import PackageNotFoundError, version
from importlib.resources import files
from pathlib import Path
from typing import Any


try:
    BACKEND_VERSION = version("synapsectrl")
except PackageNotFoundError:  # Direct source-tree import without an installed project.
    BACKEND_VERSION = "0+unknown"

# Human-readable hook implementation revision. Bump this when the hook's
# compatibility contract or metadata schema changes. Exact hook builds are
# additionally identified by the SHA-256 fingerprint of the packaged installer,
# so any hook-code change is detected even if this integer is accidentally left
# unchanged.
HOOK_VERSION = 3
HOOK_PROTOCOL_VERSION = 1


def _hook_installer_bytes() -> bytes:
    resource = files("synapsectrl").joinpath("Install-SynapseInspectHook.ps1")
    try:
        return resource.read_bytes()
    except (FileNotFoundError, OSError):
        # Editable/source-tree execution does not necessarily expose hatch's
        # wheel force-include resource. Keep diagnostics deterministic there too.
        fallback = Path(__file__).resolve().parents[2] / "Install-SynapseInspectHook.ps1"
        return fallback.read_bytes()


@lru_cache(maxsize=1)
def expected_hook_fingerprint() -> str:
    """Return the exact SHA-256 build fingerprint for the packaged hook code."""
    return sha256(_hook_installer_bytes()).hexdigest()


def hook_build_id(version_number: int | None, fingerprint: str | None) -> str | None:
    """Return a short human-readable hook build ID such as ``v3+1a2b3c4d5e6f``."""
    if version_number is None or not isinstance(fingerprint, str) or not fingerprint:
        return None
    return f"v{version_number}+{fingerprint[:12].lower()}"


def expected_hook_metadata() -> dict[str, Any]:
    """Return backend expectations for the currently packaged hook build."""
    fingerprint = expected_hook_fingerprint()
    return {
        "backendVersion": BACKEND_VERSION,
        "hookVersion": HOOK_VERSION,
        "hookProtocolVersion": HOOK_PROTOCOL_VERSION,
        "hookFingerprint": fingerprint,
        "hookBuildId": hook_build_id(HOOK_VERSION, fingerprint),
    }
