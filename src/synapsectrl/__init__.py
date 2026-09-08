"""Control Synapse software profiles through a local, verified interface."""

from importlib.metadata import PackageNotFoundError, version

from .client import SynapseClient
from .errors import SynapseError
from .models import Device, Profile, Status, SwitchResult

try:
    __version__ = version("synapsectrl")
except PackageNotFoundError:  # Direct source-tree import without an installed project.
    __version__ = "0+unknown"

__all__ = ["SynapseClient", "SynapseError", "Device", "Profile", "Status", "SwitchResult"]
