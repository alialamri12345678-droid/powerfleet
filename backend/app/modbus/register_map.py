"""Load and parse the configurable DSE register map from YAML."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


@dataclass
class RegisterDef:
    """A single register definition from the YAML map."""

    name: str
    address: int
    data_type: str  # uint16, int16, uint32, int32, float32, bool
    access: str     # read, write, readwrite
    scale: float = 1.0
    unit: str = ""
    description: str = ""
    values: dict[int, str] = field(default_factory=dict)
    bits: dict[int, str] = field(default_factory=dict)

    @property
    def is_coil(self) -> bool:
        return self.data_type == "bool"

    @property
    def is_32bit(self) -> bool:
        return self.data_type in ("uint32", "int32", "float32")

    @property
    def register_count(self) -> int:
        """Number of 16-bit registers this point occupies."""
        return 2 if self.is_32bit else 1

    @property
    def is_writable(self) -> bool:
        return self.access in ("write", "readwrite")

    @property
    def is_readable(self) -> bool:
        return self.access in ("read", "readwrite")


@dataclass
class PollGroup:
    """A group of registers polled together at a defined interval."""

    name: str
    description: str
    register_names: list[str]
    interval_ms: int


class RegisterMap:
    """Parsed register map providing lookup by name or address."""

    def __init__(self, registers: dict[str, RegisterDef], poll_groups: list[PollGroup]):
        self.registers = registers
        self.poll_groups = poll_groups
        self._by_address: dict[int, RegisterDef] = {
            r.address: r for r in registers.values()
        }

    def get(self, name: str) -> RegisterDef | None:
        return self.registers.get(name)

    def get_by_address(self, address: int) -> RegisterDef | None:
        return self._by_address.get(address)

    def readable_registers(self) -> list[RegisterDef]:
        return [r for r in self.registers.values() if r.is_readable]

    def writable_registers(self) -> list[RegisterDef]:
        return [r for r in self.registers.values() if r.is_writable]

    def coil_registers(self) -> list[RegisterDef]:
        return [r for r in self.registers.values() if r.is_coil]

    @property
    def version(self) -> str:
        return self._version

    @version.setter
    def version(self, v: str):
        self._version = v


def load_register_map(path: str | Path) -> RegisterMap:
    """Load and parse the register map YAML file.

    Args:
        path: Filesystem path to register_map.yaml

    Returns:
        A RegisterMap instance ready for use by the gateway.

    Raises:
        FileNotFoundError: if the YAML file doesn't exist.
        ValueError: if the YAML is malformed.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"Register map not found: {path}")

    with open(path, "r", encoding="utf-8") as f:
        raw: dict[str, Any] = yaml.safe_load(f)

    if not raw or "registers" not in raw:
        raise ValueError(f"Invalid register map: missing 'registers' key in {path}")

    # Parse registers
    registers: dict[str, RegisterDef] = {}
    for name, defn in raw["registers"].items():
        address = defn["address"]
        if isinstance(address, str) and address.startswith("0x"):
            address = int(address, 16)
        else:
            address = int(address)

        registers[name] = RegisterDef(
            name=name,
            address=address,
            data_type=defn.get("type", "uint16"),
            access=defn.get("access", "read"),
            scale=float(defn.get("scale", 1.0)),
            unit=defn.get("unit", ""),
            description=defn.get("description", ""),
            values=defn.get("values", {}),
            bits=defn.get("bits", {}),
        )

    # Parse poll groups
    poll_groups: list[PollGroup] = []
    for name, gdef in raw.get("poll_groups", {}).items():
        poll_groups.append(PollGroup(
            name=name,
            description=gdef.get("description", ""),
            register_names=gdef.get("registers", []),
            interval_ms=gdef.get("interval_ms", 1000),
        ))

    rmap = RegisterMap(registers, poll_groups)
    rmap.version = raw.get("version", "unknown")

    logger.info(
        "Loaded register map v%s: %d registers, %d poll groups",
        rmap.version, len(registers), len(poll_groups),
    )
    return rmap
