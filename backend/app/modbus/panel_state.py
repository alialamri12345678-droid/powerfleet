"""In-memory state representation for a single panel.

PanelState holds the latest readings from a panel, connection status,
and is serializable to JSON for WebSocket broadcast.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class PanelState:
    """Live state snapshot for a single DSE panel."""

    panel_id: str
    panel_name: str
    site_id: str = ""

    # Connection health
    is_reachable: bool = False
    last_poll_time: float | None = None  # monotonic timestamp
    last_successful_poll: datetime | None = None
    consecutive_errors: int = 0
    last_error: str | None = None

    # Engine / generator status
    engine_status: str = "unknown"  # stopped, preheat, cranking, running, cooldown, fault
    generator_status: str = "unknown"
    generator_breaker: bool = False
    sync_status: bool = False

    # Load
    load_kw: float = 0.0
    load_kw_percent: float = 0.0
    load_kvar: float = 0.0
    load_kvar_percent: float = 0.0
    load_kva: float = 0.0

    # Electrical
    voltage_l1_n: float = 0.0
    voltage_l2_n: float = 0.0
    voltage_l3_n: float = 0.0
    frequency: float = 0.0

    # Engine health
    coolant_temperature: float = 0.0
    oil_pressure: float = 0.0
    battery_voltage: float = 0.0
    engine_speed: int = 0

    # Totals
    run_hours: float = 0.0
    total_kwh: float = 0.0
    number_of_starts: int = 0

    # Alarms — list of active alarm names
    active_alarms: list[str] = field(default_factory=list)

    # Last command issued by this gateway
    last_command: str | None = None
    last_command_time: datetime | None = None

    @property
    def display_status(self) -> str:
        """Human-friendly status for dashboard display."""
        if not self.is_reachable:
            return "Unreachable"
        if self.active_alarms:
            return "Alarm"
        status_map = {
            "stopped": "Idle",
            "preheat": "Starting",
            "cranking": "Starting",
            "running": "Running",
            "cooldown": "Stopping",
            "fault": "Alarm",
            "unknown": "Unknown",
        }
        return status_map.get(self.engine_status, "Unknown")

    @property
    def is_running(self) -> bool:
        return self.engine_status == "running"

    @property
    def data_age_seconds(self) -> float | None:
        """Seconds since last successful poll."""
        if self.last_poll_time is None:
            return None
        return time.monotonic() - self.last_poll_time

    @property
    def is_data_fresh(self) -> bool:
        """True if data is less than 30 seconds old."""
        age = self.data_age_seconds
        return age is not None and age < 30.0

    def mark_poll_success(self) -> None:
        """Update connection health after a successful poll."""
        self.is_reachable = True
        self.last_poll_time = time.monotonic()
        self.last_successful_poll = datetime.now(timezone.utc)
        self.consecutive_errors = 0
        self.last_error = None

    def mark_poll_failure(self, error: str) -> None:
        """Update connection health after a failed poll."""
        self.last_poll_time = time.monotonic()
        self.consecutive_errors += 1
        self.last_error = error
        # Mark unreachable after 3 consecutive failures
        if self.consecutive_errors >= 3:
            self.is_reachable = False

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a dict suitable for JSON / WebSocket broadcast."""
        return {
            "panel_id": self.panel_id,
            "panel_name": self.panel_name,
            "site_id": self.site_id,
            "is_reachable": self.is_reachable,
            "last_successful_poll": (
                self.last_successful_poll.isoformat()
                if self.last_successful_poll
                else None
            ),
            "consecutive_errors": self.consecutive_errors,
            "last_error": self.last_error,
            "engine_status": self.engine_status,
            "is_running": self.is_running,
            "generator_breaker": self.generator_breaker,
            "sync_status": self.sync_status,
            "display_status": self.display_status,
            "load_kw": self.load_kw,
            "load_kw_percent": self.load_kw_percent,
            "load_kvar": self.load_kvar,
            "load_kvar_percent": self.load_kvar_percent,
            "load_kva": self.load_kva,
            "voltage_l1_n": self.voltage_l1_n,
            "voltage_l2_n": self.voltage_l2_n,
            "voltage_l3_n": self.voltage_l3_n,
            "frequency": self.frequency,
            "coolant_temperature": self.coolant_temperature,
            "oil_pressure": self.oil_pressure,
            "battery_voltage": self.battery_voltage,
            "engine_speed": self.engine_speed,
            "run_hours": self.run_hours,
            "total_kwh": self.total_kwh,
            "number_of_starts": self.number_of_starts,
            "active_alarms": self.active_alarms,
            "last_command": self.last_command,
            "last_command_time": (
                self.last_command_time.isoformat()
                if self.last_command_time
                else None
            ),
        }
