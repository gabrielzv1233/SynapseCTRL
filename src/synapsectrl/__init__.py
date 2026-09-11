"""Control Synapse software profiles through a local, verified interface."""

from .metadata import BACKEND_VERSION, HOOK_PROTOCOL_VERSION, HOOK_VERSION
from .client import SynapseClient
from .errors import SynapseError
from .models import Device, Profile, Status, SwitchResult
from .service import SynapseService

__version__ = BACKEND_VERSION

__all__ = [
    "SynapseClient",
    "SynapseService",
    "SynapseError",
    "Device",
    "Profile",
    "Status",
    "SwitchResult",
    "HOOK_VERSION",
    "HOOK_PROTOCOL_VERSION",
]
