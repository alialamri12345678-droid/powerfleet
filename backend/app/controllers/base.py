"""Adapter contract between vendor panels and normalized fleet behavior."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass
from typing import Any

from .profiles import ControllerProfile


@dataclass(frozen=True)
class CommandWrite:
    address: int
    values: tuple[int, ...]


class ControllerAdapter(ABC):
    profile_id = "base"

    def __init__(self, register_map, profile: ControllerProfile):
        self.register_map = register_map
        self.profile = profile

    def decode_reading(self, register, raw: int) -> Any:
        if register.values:
            return register.values.get(raw, "unknown")
        if register.name in {"generator_breaker", "sync_status"}:
            return bool(raw)
        value = raw * register.scale
        return int(value) if register.data_type.startswith("uint") and register.scale == 1.0 else value

    def apply_reading(self, state, register, raw: int) -> None:
        value = self.decode_reading(register, raw)
        state.readings[register.name] = value
        state.reading_units[register.name] = register.unit
        state.reading_quality[register.name] = "good"
        if hasattr(state, register.name):
            setattr(state, register.name, value)

        # GenComm does not expose the placeholder engine-state enum previously
        # used by the app. RPM is the reliable, normalized running indication.
        if register.name == "engine_speed":
            state.engine_status = "running" if raw > 0 else "stopped"
            if state.reading_quality.get("generator_status") != "good":
                state.generator_status = state.engine_status
                state.readings["generator_status"] = state.generator_status
                state.reading_units["generator_status"] = ""
                state.reading_quality["generator_status"] = "good"
        elif register.name == "generator_state":
            simulator_states = {
                0: "stopped", 1: "prestart", 2: "cranking", 3: "starting",
                4: "warming_up", 5: "running_off_load", 6: "synchronizing",
                7: "breaker_closed", 8: "on_load", 9: "cooling_down",
                10: "stopping", 11: "failed_to_start", 12: "shutdown",
                13: "electrical_trip",
            }
            state.generator_status = simulator_states.get(raw, f"state_{raw}")
            state.readings["generator_status"] = state.generator_status
            state.reading_units["generator_status"] = ""
            state.reading_quality["generator_status"] = "good"
        elif register.name == "standard_digital_outputs":
            # Page 13 offset 0 stores two-bit relay states. Bits 9-10 are
            # the generator loading relay: 0=open, 1=closed, 3=unimplemented.
            generator_loading_relay = (raw >> 8) & 0x3
            if generator_loading_relay == 3:
                state.reading_quality["generator_breaker"] = "unavailable"
                state.reading_quality["sync_status"] = "unavailable"
                return
            state.generator_breaker = generator_loading_relay == 1
            state.sync_status = state.generator_breaker
            state.readings["generator_breaker"] = state.generator_breaker
            state.readings["sync_status"] = state.sync_status
            state.reading_units["generator_breaker"] = ""
            state.reading_units["sync_status"] = ""
            state.reading_quality["generator_breaker"] = "good"
            state.reading_quality["sync_status"] = "good"

    def command_register(self, command: str):
        return self.register_map.get(command)

    def command_write(self, command: str) -> CommandWrite | None:
        """Build GenComm's atomic control-key + one's-complement write."""
        keys = {"remote_start": 35732, "remote_stop": 35733}
        key = keys.get(command)
        control = self.register_map.get("system_control_key")
        if key is None or control is None:
            return None
        return CommandWrite(control.address, (key, (~key) & 0xFFFF))

    @property
    def capabilities(self) -> set[str]:
        return set(self.profile.capabilities)
