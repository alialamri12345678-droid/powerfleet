"""Modbus Gateway — the central poll loop and command dispatcher.

Manages connections to all panels at a site, reads live telemetry,
and dispatches write commands (Remote Start/Stop, setpoints) with
cooldown enforcement and event logging.
"""

from __future__ import annotations

import asyncio
import logging
import struct
from datetime import datetime, timezone
from typing import Any, Callable

from app.config import settings
from app.modbus.cooldown import CooldownManager
from app.modbus.panel_state import PanelState
from app.modbus.register_map import RegisterDef, RegisterMap, load_register_map
from app.modbus.transport import ModbusTransport, TransportError, create_transport

logger = logging.getLogger(__name__)


class ModbusGateway:
    """Manages Modbus communication with all panels at a site.

    Responsibilities:
    - Maintain transport connections (auto-reconnect on failure)
    - Run an async poll loop reading status/telemetry
    - Dispatch write commands with cooldown enforcement
    - Notify listeners (WebSocket, rules engine) on state changes
    """

    def __init__(
        self,
        register_map_path: str | None = None,
        poll_interval_ms: int | None = None,
    ):
        self._register_map: RegisterMap = load_register_map(
            register_map_path or settings.register_map_path
        )
        self._poll_interval = (poll_interval_ms or settings.modbus_poll_interval_ms) / 1000.0

        # panel_id → transport instance
        self._transports: dict[str, ModbusTransport] = {}
        # panel_id → config dict
        self._panel_configs: dict[str, dict[str, Any]] = {}
        # panel_id → live state
        self._states: dict[str, PanelState] = {}

        self._cooldown = CooldownManager()
        self._running = False
        self._poll_task: asyncio.Task | None = None

        # Callbacks invoked on state updates
        self._state_listeners: list[Callable[[str, PanelState], Any]] = []
        # Callback for event logging
        self._event_logger: Callable[..., Any] | None = None

    @property
    def register_map(self) -> RegisterMap:
        return self._register_map

    @property
    def states(self) -> dict[str, PanelState]:
        return self._states

    @property
    def cooldown_manager(self) -> CooldownManager:
        return self._cooldown

    def on_state_update(self, callback: Callable[[str, PanelState], Any]) -> None:
        """Register a listener for panel state updates."""
        self._state_listeners.append(callback)

    def set_event_logger(self, logger_fn: Callable[..., Any]) -> None:
        """Set the function used to log events to the database."""
        self._event_logger = logger_fn

    def add_panel(
        self,
        panel_id: str,
        site_id: str,
        name: str,
        transport_type: str,
        address: str,
        unit_id: int,
        **kwargs,
    ) -> None:
        """Register a panel for polling."""
        self._panel_configs[panel_id] = {
            "site_id": site_id,
            "transport_type": transport_type,
            "address": address,
            "unit_id": unit_id,
            **kwargs,
        }
        self._states[panel_id] = PanelState(
            panel_id=panel_id,
            panel_name=name,
            site_id=site_id,
        )
        logger.info("Added panel %s (%s) via %s at %s", panel_id, name, transport_type, address)

    def remove_panel(self, panel_id: str) -> None:
        """Remove a panel from the poll loop."""
        self._panel_configs.pop(panel_id, None)
        self._states.pop(panel_id, None)
        transport = self._transports.pop(panel_id, None)
        if transport:
            asyncio.create_task(transport.disconnect())

    async def start(self) -> None:
        """Start the background poll loop."""
        if self._running:
            return
        self._running = True
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("Modbus gateway started (poll interval: %.1fs)", self._poll_interval)

    async def stop(self) -> None:
        """Stop the poll loop and disconnect all transports.

        Does NOT issue any commands — panels keep their last-received state.
        """
        self._running = False
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        for transport in self._transports.values():
            try:
                await transport.disconnect()
            except Exception:
                pass
        self._transports.clear()
        logger.info("Modbus gateway stopped")

    # ── Poll Loop ─────────────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        """Main polling loop — runs until stopped."""
        while self._running:
            panel_ids = list(self._panel_configs.keys())
            if not panel_ids:
                await asyncio.sleep(self._poll_interval)
                continue
                
            # Poll all panels concurrently
            tasks = [self._poll_panel(panel_id) for panel_id in panel_ids]
            await asyncio.gather(*tasks, return_exceptions=True)
                
            if self._running:
                await asyncio.sleep(self._poll_interval)

    async def _poll_panel(self, panel_id: str) -> None:
        """Poll a single panel: connect if needed, read registers, update state."""
        config = self._panel_configs.get(panel_id)
        if not config:
            return

        state = self._states[panel_id]
        unit_id = config["unit_id"]

        # Ensure transport exists and is connected
        transport = await self._ensure_connected(panel_id, config)
        if transport is None:
            state.mark_poll_failure("Failed to establish connection")
            self._notify_listeners(panel_id, state)
            return

        try:
            await self._read_status_registers(transport, state, unit_id)
            await self._read_alarm_registers(transport, state, unit_id)
            state.mark_poll_success()
        except TransportError as exc:
            state.mark_poll_failure(str(exc))
            logger.warning("Poll failed for panel %s: %s", panel_id, exc)
            # Try to reconnect on next cycle
            await self._disconnect_panel(panel_id)

        self._notify_listeners(panel_id, state)

    async def _ensure_connected(
        self, panel_id: str, config: dict
    ) -> ModbusTransport | None:
        """Ensure a transport connection exists, creating one if needed."""
        transport = self._transports.get(panel_id)
        if transport and transport.is_connected:
            return transport

        try:
            transport = create_transport(
                config["transport_type"], config["address"]
            )
            await transport.connect()
            self._transports[panel_id] = transport
            return transport
        except TransportError as exc:
            logger.warning("Connection failed for panel %s: %s", panel_id, exc)
            return None

    async def _disconnect_panel(self, panel_id: str) -> None:
        transport = self._transports.pop(panel_id, None)
        if transport:
            try:
                await transport.disconnect()
            except Exception:
                pass

    # ── Register Reads ────────────────────────────────────────────────

    async def _read_status_registers(
        self, transport: ModbusTransport, state: PanelState, unit_id: int
    ) -> None:
        """Read core status and telemetry registers into PanelState."""
        rmap = self._register_map

        # Engine status
        reg = rmap.get("engine_status")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.engine_status = reg.values.get(raw, "unknown")

        # Generator breaker
        reg = rmap.get("generator_breaker")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.generator_breaker = bool(raw)

        # Sync status
        reg = rmap.get("sync_status")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.sync_status = bool(raw)

        # Load kW
        reg = rmap.get("load_kw")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.load_kw = raw * reg.scale

        # Load kW %
        reg = rmap.get("load_kw_percent")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.load_kw_percent = float(raw)

        # Load kVAr
        reg = rmap.get("load_kvar")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.load_kvar = raw * reg.scale

        # Load kVAr %
        reg = rmap.get("load_kvar_percent")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.load_kvar_percent = float(raw)

        # Voltages
        for vname in ("voltage_l1_n", "voltage_l2_n", "voltage_l3_n"):
            reg = rmap.get(vname)
            if reg:
                raw = await self._read_register(transport, reg, unit_id)
                if raw is not None:
                    setattr(state, vname, raw * reg.scale)

        # Frequency
        reg = rmap.get("frequency")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.frequency = raw * reg.scale

        # Engine health
        for ename in ("coolant_temperature", "oil_pressure", "battery_voltage", "engine_speed"):
            reg = rmap.get(ename)
            if reg:
                raw = await self._read_register(transport, reg, unit_id)
                if raw is not None:
                    val = raw * reg.scale if reg.scale != 1.0 else raw
                    setattr(state, ename, val)

        # Run hours (32-bit)
        reg = rmap.get("run_hours")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.run_hours = raw * reg.scale

        # Total kWh (32-bit)
        reg = rmap.get("total_kwh")
        if reg:
            raw = await self._read_register(transport, reg, unit_id)
            if raw is not None:
                state.total_kwh = float(raw)

    async def _read_alarm_registers(
        self, transport: ModbusTransport, state: PanelState, unit_id: int
    ) -> None:
        """Read alarm word registers and decode active alarm flags."""
        rmap = self._register_map
        active_alarms: list[str] = []

        for alarm_name in ("alarm_word_1", "alarm_word_2", "alarm_word_3"):
            reg = rmap.get(alarm_name)
            if not reg or not reg.bits:
                continue
            raw = await self._read_register(transport, reg, unit_id)
            if raw is None:
                continue
            for bit_pos, alarm_label in reg.bits.items():
                if raw & (1 << bit_pos):
                    active_alarms.append(alarm_label)

        # Detect newly appeared / cleared alarms (for event logging)
        prev_alarms = set(state.active_alarms)
        new_alarms = set(active_alarms)
        state.active_alarms = active_alarms

        if self._event_logger:
            for alarm in new_alarms - prev_alarms:
                await self._log_event(
                    panel_id=state.panel_id,
                    event_type="alarm_active",
                    value=alarm,
                    triggered_by="system",
                    reason=f"Alarm activated: {alarm}",
                )
            for alarm in prev_alarms - new_alarms:
                await self._log_event(
                    panel_id=state.panel_id,
                    event_type="alarm_cleared",
                    value=alarm,
                    triggered_by="system",
                    reason=f"Alarm cleared: {alarm}",
                )

    async def _read_register(
        self, transport: ModbusTransport, reg: RegisterDef, unit_id: int
    ) -> int | None:
        """Read a single register (or register pair for 32-bit) and return raw value."""
        try:
            if reg.is_coil:
                values = await transport.read_coils(reg.address, 1, unit_id)
                return 1 if values[0] else 0

            values = await transport.read_holding_registers(
                reg.address, reg.register_count, unit_id
            )

            if reg.is_32bit:
                # High word first (big-endian pair)
                return (values[0] << 16) | values[1]

            raw = values[0]
            # Handle signed types
            if reg.data_type == "int16" and raw >= 0x8000:
                raw -= 0x10000
            return raw

        except TransportError:
            return None

    # ── Command Writes ────────────────────────────────────────────────

    async def _validate_safe_to_start(self, panel_id: str) -> tuple[bool, str]:
        """Check that starting this panel is safe (no faults)."""
        state = self._states.get(panel_id)
        if not state:
            return False, f"Panel {panel_id} state unknown"
            
        if not getattr(state, "is_data_fresh", True):
            return False, "Cannot verify safety: telemetry data is stale"

        # Check for active alarms
        if state.active_alarms:
            return False, f"Cannot start panel with active alarms: {', '.join(state.active_alarms)}"
            
        # Optional: check if already running? If it's already running, it's a no-op but safe.
        
        return True, "Safe to start"

    async def send_remote_start(
        self,
        panel_id: str,
        triggered_by: str = "manual",
        reason: str = "",
        user_id: str | None = None,
        load_kw_at_decision: float | None = None,
        capacity_pct_at_decision: float | None = None,
    ) -> tuple[bool, str]:
        """Send Remote Start to a panel, respecting cooldown.

        Returns (success, message).
        """
        # Safety check
        safe_to_start, safe_msg = await self._validate_safe_to_start(panel_id)
        if not safe_to_start:
            logger.warning("Start blocked for %s: %s", panel_id, safe_msg)
            return False, safe_msg

        # Check cooldown
        cd_result = self._cooldown.check_start(panel_id)
        if not cd_result.allowed:
            logger.info("Start blocked by cooldown for %s: %s", panel_id, cd_result.reason)
            return False, cd_result.reason

        reg = self._register_map.get("remote_start")
        if not reg:
            return False, "remote_start register not defined in register map"

        config = self._panel_configs.get(panel_id)
        if not config:
            return False, f"Panel {panel_id} not registered"

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            return False, f"Panel {panel_id} not connected"

        try:
            await transport.write_coil(reg.address, True, config["unit_id"])
            self._cooldown.record_start(panel_id)

            state = self._states.get(panel_id)
            previous_state = state.engine_status if state else "unknown"
            if state:
                state.last_command = "remote_start"
                state.last_command_time = datetime.now(timezone.utc)

            await self._log_event(
                panel_id=panel_id,
                event_type="command_sent",
                command="remote_start",
                value="ON",
                triggered_by=triggered_by,
                reason=reason,
                previous_state=previous_state,
                new_state="running",
                load_kw_at_decision=load_kw_at_decision,
                capacity_pct_at_decision=capacity_pct_at_decision,
                command_result="success",
                user_id=user_id,
            )

            logger.info("Remote START sent to panel %s (by: %s)", panel_id, triggered_by)
            return True, "Remote Start sent"

        except TransportError as exc:
            msg = f"Failed to send Remote Start to {panel_id}: {exc}"
            logger.error(msg)
            return False, msg

    async def _validate_safe_to_stop(self, panel_id: str) -> tuple[bool, str]:
        """Check that stopping this panel won't violate capacity/reserve."""
        state = self._states.get(panel_id)
        if not state or not state.is_running:
            return True, "Panel not running, safe to send stop"
        
        # Calculate remaining capacity if this panel stops
        remaining_capacity = sum(
            s.load_kw for pid, s in self._states.items()
            if pid != panel_id and s.is_running and s.is_reachable and getattr(s, "is_data_fresh", True)
        )
        
        # Calculate current site load
        current_site_load = sum(
            s.load_kw for s in self._states.values() if s.is_running
        )
        
        # We need at least enough capacity to handle the load, plus a 20% reserve margin.
        if remaining_capacity < current_site_load * 0.8:
            return False, f"Stopping {panel_id} would violate reserve margin. Load: {current_site_load:.1f}kW, Remaining capacity: {remaining_capacity:.1f}kW"
            
        return True, "Safe to stop"

    async def send_remote_stop(
        self,
        panel_id: str,
        triggered_by: str = "manual",
        reason: str = "",
        user_id: str | None = None,
        load_kw_at_decision: float | None = None,
        capacity_pct_at_decision: float | None = None,
    ) -> tuple[bool, str]:
        """Send Remote Stop to a panel, respecting cooldown and capacity guard."""
        # 1. Capacity guard check
        safe_to_stop, safe_msg = await self._validate_safe_to_stop(panel_id)
        if not safe_to_stop:
            logger.warning("Stop blocked for %s: %s", panel_id, safe_msg)
            return False, safe_msg

        # 2. Cooldown check
        cd_result = self._cooldown.check_stop(panel_id)
        if not cd_result.allowed:
            logger.info("Stop blocked by cooldown for %s: %s", panel_id, cd_result.reason)
            return False, cd_result.reason

        reg = self._register_map.get("remote_stop")
        if not reg:
            return False, "remote_stop register not defined in register map"

        config = self._panel_configs.get(panel_id)
        if not config:
            return False, f"Panel {panel_id} not registered"

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            return False, f"Panel {panel_id} not connected"

        try:
            await transport.write_coil(reg.address, True, config["unit_id"])
            self._cooldown.record_stop(panel_id)

            state = self._states.get(panel_id)
            previous_state = state.engine_status if state else "unknown"
            if state:
                state.last_command = "remote_stop"
                state.last_command_time = datetime.now(timezone.utc)

            await self._log_event(
                panel_id=panel_id,
                event_type="command_sent",
                command="remote_stop",
                value="ON",
                triggered_by=triggered_by,
                reason=reason,
                previous_state=previous_state,
                new_state="stopped",
                load_kw_at_decision=load_kw_at_decision,
                capacity_pct_at_decision=capacity_pct_at_decision,
                command_result="success",
                user_id=user_id,
            )

            logger.info("Remote STOP sent to panel %s (by: %s)", panel_id, triggered_by)
            return True, "Remote Stop sent"

        except TransportError as exc:
            msg = f"Failed to send Remote Stop to {panel_id}: {exc}"
            logger.error(msg)
            return False, msg

    async def write_power_setpoint(
        self,
        panel_id: str,
        kw_pct: int,
        triggered_by: str = "manual",
        reason: str = "",
        user_id: str | None = None,
    ) -> tuple[bool, str]:
        """Write a fixed-power kW setpoint to a panel."""
        reg = self._register_map.get("fixed_power_setpoint_kw")
        if not reg:
            return False, "fixed_power_setpoint_kw register not defined"

        config = self._panel_configs.get(panel_id)
        if not config:
            return False, f"Panel {panel_id} not registered"

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            return False, f"Panel {panel_id} not connected"

        try:
            await transport.write_register(reg.address, kw_pct, config["unit_id"])

            state = self._states.get(panel_id)
            previous_state = state.engine_status if state else "unknown"
            await self._log_event(
                panel_id=panel_id,
                event_type="command_sent",
                command="set_power",
                value=f"{kw_pct}%",
                triggered_by=triggered_by,
                reason=reason,
                previous_state=previous_state,
                command_result="success",
                user_id=user_id,
            )

            logger.info("Power setpoint %d%% sent to panel %s", kw_pct, panel_id)
            return True, f"Setpoint {kw_pct}% sent"

        except TransportError as exc:
            msg = f"Failed to write setpoint to {panel_id}: {exc}"
            logger.error(msg)
            return False, msg

    # ── Reconciliation (startup) ──────────────────────────────────────

    async def reconcile_panel_states(self) -> None:
        """On startup, read each panel's actual state before enabling rules.

        This prevents blind-replaying the last intended state after a
        gateway restart or power loss.
        """
        logger.info("Reconciling panel states after startup...")
        panel_ids = list(self._panel_configs.keys())
        if not panel_ids:
            return
            
        tasks = [self._poll_panel(panel_id) for panel_id in panel_ids]
        await asyncio.gather(*tasks, return_exceptions=True)
        
        for panel_id in panel_ids:
            state = self._states.get(panel_id)
            if state and state.is_reachable:
                # Set implied cooldowns based on actual state to prevent rapid cycling on restart
                if state.is_running:
                    # Assume it just started to prevent an immediate stop
                    self._cooldown.record_start(panel_id)
                elif state.engine_status == "stopped":
                    # Assume it just stopped to prevent an immediate start
                    self._cooldown.record_stop(panel_id)
                else:
                    self._cooldown.reset(panel_id)
                logger.info(
                    "Panel %s reconciled: status=%s, load=%.1f%%",
                    panel_id, state.engine_status, state.load_kw_percent,
                )
            else:
                logger.warning("Panel %s unreachable during reconciliation", panel_id)

    # ── Diagnostics ───────────────────────────────────────────────────

    async def read_all_registers(self, panel_id: str) -> dict[str, Any]:
        """Read all known registers for a panel (technician diagnostics).

        Returns a dict of register_name → {address, raw_value, scaled_value, unit}.
        """
        config = self._panel_configs.get(panel_id)
        if not config:
            return {}

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            return {}

        unit_id = config["unit_id"]
        results: dict[str, Any] = {}

        for name, reg in self._register_map.registers.items():
            if not reg.is_readable:
                continue
            raw = await self._read_register(transport, reg, unit_id)
            scaled = raw * reg.scale if raw is not None else None
            results[name] = {
                "address": f"0x{reg.address:04X}",
                "raw_value": raw,
                "scaled_value": scaled,
                "unit": reg.unit,
                "type": reg.data_type,
                "description": reg.description,
            }

        return results

    # ── Helpers ────────────────────────────────────────────────────────

    def _notify_listeners(self, panel_id: str, state: PanelState) -> None:
        for listener in self._state_listeners:
            try:
                result = listener(panel_id, state)
                if asyncio.iscoroutine(result):
                    asyncio.create_task(result)
            except Exception as exc:
                logger.error("State listener error: %s", exc)

    async def _log_event(self, **kwargs) -> None:
        if self._event_logger:
            try:
                result = self._event_logger(**kwargs)
                if asyncio.iscoroutine(result):
                    await result
            except Exception as exc:
                logger.error("Event logging error: %s", exc)
