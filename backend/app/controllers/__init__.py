"""Controller adapter registry.

The fleet and UI consume normalized state; only adapters understand a panel's
register contract. Additional manufacturers register here without changing
rules, reports or dashboard code.
"""

from .base import ControllerAdapter
from .gencomm import GenCommAdapter
from .profiles import (
    CONTROLLER_PROFILES,
    get_controller_profile,
    list_controller_profiles,
)

def create_adapter(profile: str, register_map):
    profile_def = get_controller_profile(profile)
    return GenCommAdapter(register_map.for_profile(profile_def.map_family), profile_def)


__all__ = [
    "ControllerAdapter", "GenCommAdapter",
    "CONTROLLER_PROFILES", "create_adapter", "get_controller_profile",
    "list_controller_profiles",
]
