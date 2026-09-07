"""Fleet Dispatcher — computes and reconciles the desired state of the generator fleet."""

from __future__ import annotations

import logging
from typing import Literal

from app.modbus.gateway import ModbusGateway

logger = logging.getLogger(__name__)

DesiredState = Literal["RUNNING", "STOPPED", "IGNORE"]

class FleetDispatcher:
    """Computes the desired state for all panels and dispatches commands."""
    
    def __init__(self, gateway: ModbusGateway):
        self._gateway = gateway
        
    def compute_desired_state(
        self,
        schedule_wants: dict[str, DesiredState],
        threshold_wants: dict[str, DesiredState],
        fault_wants: dict[str, DesiredState],
        overrides: dict[str, DesiredState]
    ) -> dict[str, DesiredState]:
        """Merge inputs with priority: Override > Threshold > Schedule.
        
        Returns a dictionary of panel_id -> DesiredState.
        """
        desired_fleet_state: dict[str, DesiredState] = {}
        
        # Start with all known panels as IGNORE
        for panel_id in self._gateway.states.keys():
            desired_fleet_state[panel_id] = "IGNORE"
            
        # 1. Apply Schedule
        for pid, state in schedule_wants.items():
            if pid in desired_fleet_state:
                desired_fleet_state[pid] = state
                
        # 2. Apply Threshold (overrides Schedule if threshold wants to start, 
        # or if threshold explicitly wants to stop it because of low load)
        for pid, state in threshold_wants.items():
            if pid in desired_fleet_state:
                if state == "RUNNING":
                    desired_fleet_state[pid] = "RUNNING"
                elif state == "STOPPED":
                    # Only stop if schedule doesn't want it running
                    if schedule_wants.get(pid) != "RUNNING":
                        desired_fleet_state[pid] = "STOPPED"
                
        # 3. Apply Fault Response (Overrides Threshold/Schedule)
        for pid, state in fault_wants.items():
            if pid in desired_fleet_state:
                if state == "RUNNING":
                    desired_fleet_state[pid] = "RUNNING"
                elif state == "STOPPED":
                    if schedule_wants.get(pid) != "RUNNING" and threshold_wants.get(pid) != "RUNNING":
                        desired_fleet_state[pid] = "STOPPED"
                
        # 4. Apply Overrides (Absolute highest priority)
        for pid, state in overrides.items():
            if pid in desired_fleet_state:
                desired_fleet_state[pid] = state
                
        return desired_fleet_state

    async def reconcile(
        self,
        desired_state: dict[str, DesiredState],
        reason_context: str = "Fleet dispatcher reconciliation"
    ) -> None:
        """Issue commands to transition the fleet from actual to desired state."""
        
        # Calculate current fleet load for audit trail
        current_fleet_load = sum(
            s.load_kw for s in self._gateway.states.values() if getattr(s, "is_data_fresh", True)
        )
        # TODO: To get exact capacity, we'd need site rated capacity, but we can just use the absolute kW load
        
        for panel_id, desired in desired_state.items():
            if desired == "IGNORE":
                continue
                
            actual_state = self._gateway.states.get(panel_id)
            if not actual_state:
                logger.warning("FleetDispatcher: No state for panel %s, skipping", panel_id)
                continue
                
            is_running = actual_state.is_running
            
            if desired == "RUNNING" and not is_running:
                # Need to start
                logger.info("FleetDispatcher: Starting %s (reachable=%s)", panel_id, actual_state.is_reachable)
                success, msg = await self._gateway.send_remote_start(
                    panel_id=panel_id,
                    triggered_by="dispatcher",
                    reason=f"{reason_context} - Desired: RUNNING",
                    load_kw_at_decision=current_fleet_load,
                )
                if not success:
                    logger.warning("FleetDispatcher: Start command FAILED for %s: %s", panel_id, msg)
            elif desired == "STOPPED" and is_running:
                # Need to stop
                logger.info("FleetDispatcher: Stopping %s (reachable=%s)", panel_id, actual_state.is_reachable)
                success, msg = await self._gateway.send_remote_stop(
                    panel_id=panel_id,
                    triggered_by="dispatcher",
                    reason=f"{reason_context} - Desired: STOPPED",
                    load_kw_at_decision=current_fleet_load,
                )
                if not success:
                    logger.warning("FleetDispatcher: Stop command FAILED for %s: %s", panel_id, msg)
