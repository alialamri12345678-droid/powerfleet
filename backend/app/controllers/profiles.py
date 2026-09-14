"""Controller profiles supported by the GenComm adapter.

Profiles describe model-family differences without leaking vendor-specific
details into the fleet, rules, reporting, or UI layers.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ControllerProfile:
    id: str
    name: str
    map_family: str
    status: str = "supported"
    capabilities: tuple[str, ...] = (
        "telemetry", "alarms", "remote_start", "remote_stop",
    )

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.id,
            "name": self.name,
            "map_family": self.map_family,
            "status": self.status,
            "capabilities": list(self.capabilities),
        }


# Families named by GenComm 2.236 MF.
_PROFILES = (
    ControllerProfile("dse_3xx", "Deep Sea DSE 3xx family", "dse_3xx"),
    ControllerProfile("dse_4xxx", "Deep Sea DSE 4xxx family", "dse_4xxx"),
    ControllerProfile("dse_60xx", "Deep Sea DSE 60xx family", "dse_60xx"),
    ControllerProfile("dse_61xx_mkii", "Deep Sea DSE 61xx MKII", "dse_61xx_mkii"),
    ControllerProfile("dse_61xx_mkiii", "Deep Sea DSE 61xx MKIII", "dse_61xx_mkiii"),
    ControllerProfile("dse_63xx_6420", "Deep Sea DSE 63xx / 6420", "dse_63xx_6420"),
    ControllerProfile("dse_71xx", "Deep Sea DSE 71xx family", "dse_71xx"),
    ControllerProfile("dse_72xx_73xx_mki", "Deep Sea DSE 72xx / 73xx MKI", "dse_72xx_73xx_mki"),
    ControllerProfile("dse_73xx_mkii", "Deep Sea DSE 73xx MKII", "dse_73xx_mkii"),
    ControllerProfile("dse_74xx_mki", "Deep Sea DSE 74xx MKI", "dse_74xx_mki"),
    ControllerProfile("dse_74xx_mkii", "Deep Sea DSE 74xx MKII", "dse_74xx_mkii"),
    ControllerProfile("dse_8xxx_mki", "Deep Sea DSE 8xxx MKI", "dse_8xxx_mki"),
    ControllerProfile("dse_86xx_mkii", "Deep Sea DSE 86xx MKII", "dse_86xx_mkii"),
    ControllerProfile("dse_87xx_88xx", "Deep Sea DSE 87xx / 88xx", "dse_87xx_88xx"),
    ControllerProfile("dse_exxx", "Deep Sea DSE Exxx family", "dse_exxx"),
    ControllerProfile("dse_p100", "Deep Sea DSE P100", "dse_p100"),
    ControllerProfile("dse_l40x", "Deep Sea DSE L40x family", "dse_l40x"),
)

CONTROLLER_PROFILES = {profile.id: profile for profile in _PROFILES}


def get_controller_profile(profile_id: str) -> ControllerProfile:
    try:
        return CONTROLLER_PROFILES[profile_id]
    except KeyError as exc:
        raise ValueError(f"Unsupported controller profile: {profile_id}") from exc


def list_controller_profiles() -> list[dict[str, object]]:
    return [profile.as_dict() for profile in _PROFILES]
