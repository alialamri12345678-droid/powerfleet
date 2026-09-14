"""Deep Sea Electronics GenComm controller adapter."""

from .base import ControllerAdapter


class GenCommAdapter(ControllerAdapter):
    """Adapter for DSE controllers implementing the GenComm standard."""

    profile_id = "gencomm"
