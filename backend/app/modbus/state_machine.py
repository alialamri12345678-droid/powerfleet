"""Generator state machine — SCADA-side state tracking and timeouts.

This layer sits above the raw Modbus telemetry to track the intent (Start/Stop)
and verify that the generator actually transitions to the expected state within
configured timeouts. It blocks duplicate commands and detects failures.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Callable, Literal

from app.config import settings
from app.modbus.panel_state import PanelState

logger = logging.getLogger(__name__)

ScadaState = Literal[
    "STOPPED",          # Intentionally stopped, engine is stopped
    "START_REQUESTED",  # Start command sent, waiting for engine to transition from stopped
    "STARTING",         # Engine is in preheat/cranking
    "RUNNING",          # Engine is running (normal operation)
    "STOP_REQUESTED",   # Stop command sent, waiting for engine to transition to cooldown/stopped
    "STOPPING",         # Engine is in cooldown
    "FAULTED",          # Engine has a critical alarm or failed to start/stop
    "UNAVAILABLE",      # Comms lost or data stale
    "MAINTENANCE"       # Manually marked out of service (future)
]

@dataclass
class StateMachineResult:
    allowed: bool
    reason: str = ""

class GeneratorStateMachine:
    """Tracks the intended vs actual state of a generator."""

    def __init__(self, panel_id: str):
        self.panel_id = panel_id
        self.scada_state: ScadaState = "STOPPED"
        self._state_enter_time: float = time.monotonic()
        
        self.start_timeout_seconds = 45.0  # Preheat + Crank max time
        self.stop_timeout_seconds = 90.0   # Cooldown max time
        
        # Event callbacks
        self.on_start_timeout: Callable[[str], None] | None = None
        self.on_stop_timeout: Callable[[str], None] | None = None

    def _transition(self, new_state: ScadaState) -> None:
        if self.scada_state != new_state:
            logger.info("Panel %s state transition: %s -> %s", self.panel_id, self.scada_state, new_state)
            self.scada_state = new_state
            self._state_enter_time = time.monotonic()

    def reconcile(self, state: PanelState) -> None:
        """Called on every poll to update SCADA state based on actual DSE state."""
        # 1. Handle unavailability (stale data or unreachable)
        if not state.is_reachable or not getattr(state, "is_data_fresh", True):
            if self.scada_state != "UNAVAILABLE":
                self._transition("UNAVAILABLE")
            return

        engine_status = state.engine_status
        now = time.monotonic()
        time_in_state = now - self._state_enter_time

        # 2. Handle Faults
        if engine_status == "fault":
            if self.scada_state != "FAULTED":
                self._transition("FAULTED")
            return

        # 3. State Machine Logic
        if self.scada_state == "START_REQUESTED":
            if engine_status in ("preheat", "cranking"):
                self._transition("STARTING")
            elif engine_status == "running":
                self._transition("RUNNING")
            elif time_in_state > self.start_timeout_seconds:
                logger.error("Panel %s failed to start within %ss", self.panel_id, self.start_timeout_seconds)
                self._transition("FAULTED")
                if self.on_start_timeout:
                    self.on_start_timeout(self.panel_id)
        
        elif self.scada_state == "STARTING":
            if engine_status == "running":
                self._transition("RUNNING")
            elif engine_status == "stopped":
                # Dropped back to stopped?
                self._transition("STOPPED")
            elif time_in_state > self.start_timeout_seconds:
                 logger.error("Panel %s failed to start within %ss", self.panel_id, self.start_timeout_seconds)
                 self._transition("FAULTED")
                 if self.on_start_timeout:
                     self.on_start_timeout(self.panel_id)

        elif self.scada_state == "STOP_REQUESTED":
            if engine_status == "cooldown":
                self._transition("STOPPING")
            elif engine_status == "stopped":
                self._transition("STOPPED")
            elif time_in_state > self.stop_timeout_seconds:
                logger.error("Panel %s failed to stop within %ss", self.panel_id, self.stop_timeout_seconds)
                self._transition("FAULTED")
                if self.on_stop_timeout:
                    self.on_stop_timeout(self.panel_id)

        elif self.scada_state == "STOPPING":
            if engine_status == "stopped":
                self._transition("STOPPED")
            elif engine_status == "running":
                self._transition("RUNNING")
            elif time_in_state > self.stop_timeout_seconds:
                logger.error("Panel %s failed to stop within %ss", self.panel_id, self.stop_timeout_seconds)
                self._transition("FAULTED")
                if self.on_stop_timeout:
                    self.on_stop_timeout(self.panel_id)

        elif self.scada_state == "UNAVAILABLE":
            # We re-established comms. Sync to actual state.
            self._sync_to_actual(engine_status)
            
        else:
            # For STOPPED, RUNNING, FAULTED - we just follow the engine status unless we just commanded it
            self._sync_to_actual(engine_status)

    def _sync_to_actual(self, engine_status: str) -> None:
        if engine_status == "running":
            self._transition("RUNNING")
        elif engine_status in ("preheat", "cranking"):
            self._transition("STARTING")
        elif engine_status == "cooldown":
            self._transition("STOPPING")
        elif engine_status == "stopped":
            self._transition("STOPPED")
        elif engine_status == "fault":
            self._transition("FAULTED")

    def request_start(self) -> StateMachineResult:
        """Attempt to transition to START_REQUESTED."""
        if self.scada_state in ("START_REQUESTED", "STARTING", "RUNNING"):
            return StateMachineResult(False, f"Cannot start: currently {self.scada_state}")
        if self.scada_state in ("FAULTED", "UNAVAILABLE", "MAINTENANCE"):
            return StateMachineResult(False, f"Cannot start: generator is {self.scada_state}")
        
        self._transition("START_REQUESTED")
        return StateMachineResult(True)

    def request_stop(self) -> StateMachineResult:
        """Attempt to transition to STOP_REQUESTED."""
        if self.scada_state in ("STOP_REQUESTED", "STOPPING", "STOPPED"):
             return StateMachineResult(False, f"Cannot stop: currently {self.scada_state}")
        
        self._transition("STOP_REQUESTED")
        return StateMachineResult(True)
