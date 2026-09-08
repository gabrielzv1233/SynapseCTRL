"""Control Synapse software profiles through a local, verified interface."""
from .client import SynapseClient
from .errors import SynapseError
from .models import Device, Profile, Status, SwitchResult

__version__ = "0.2.0"
__all__ = ["SynapseClient", "SynapseError", "Device", "Profile", "Status", "SwitchResult"]
