"""Modbus Gateway — the central poll loop and command dispatcher.

Manages connections to all panels at a site, reads live telemetry,
and dispatches write commands (Remote Start/Stop, setpoints) with
cooldown enforcement and event logging.
"""

from __future__ import annotations

import asyncio
import logging
import struct
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from app.config import settings
from app.controllers import create_adapter
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
        self._adapters: dict[str, Any] = {}
        self._panel_register_maps: dict[str, RegisterMap] = {}
        self._io_locks: dict[str, asyncio.Lock] = {}
        # panel_id → live state
        self._states: dict[str, PanelState] = {}
        self._last_group_poll: dict[tuple[str, str], float] = {}

        self._cooldown = CooldownManager()
        self._running = False
        self._poll_task: asyncio.Task | None = None

        # Callbacks invoked on state updates
        self._state_listeners: list[Callable[[str, PanelState], Any]] = []
        # Callback for event logging
        self._event_logger: Callable[..., Any] | None = None
        self._command_logger: Callable[..., Any] | None = None
        self._pending_commands: dict[str, dict[str, Any]] = {}

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

    def set_command_logger(self, logger_fn: Callable[..., Any]) -> None:
        self._command_logger = logger_fn

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
        # If updating an existing panel, disconnect old transport first
        if panel_id in self._transports:
            asyncio.create_task(self._disconnect_panel(panel_id))

        self._panel_configs[panel_id] = {
            "site_id": site_id,
            "transport_type": transport_type,
            "address": address,
            "unit_id": unit_id,
            **kwargs,
        }
        adapter = create_adapter(
            kwargs.get("controller_profile", "dse_86xx_mkii"), self._register_map
        )
        self._adapters[panel_id] = adapter
        self._panel_register_maps[panel_id] = adapter.register_map
        self._io_locks.setdefault(panel_id, asyncio.Lock())
        if panel_id not in self._states:
            self._states[panel_id] = PanelState(
                panel_id=panel_id,
                panel_name=name,
                site_id=site_id,
            )
        else:
            self._states[panel_id].panel_name = name
            self._states[panel_id].site_id = site_id

        logger.info("Added panel %s (%s) via %s at %s", panel_id, name, transport_type, address)

    def remove_panel(self, panel_id: str) -> None:
        """Remove a panel from the poll loop."""
        self._panel_configs.pop(panel_id, None)
        self._states.pop(panel_id, None)
        self._cooldown.reset(panel_id)
        self._adapters.pop(panel_id, None)
        self._panel_register_maps.pop(panel_id, None)
        self._io_locks.pop(panel_id, None)
        for key in [key for key in self._last_group_poll if key[0] == panel_id]:
            self._last_group_poll.pop(key, None)
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
            async with self._io_locks.setdefault(panel_id, asyncio.Lock()):
                await self._read_due_poll_groups(panel_id, transport, state, unit_id)
            state.mark_poll_success()
            await self._reconcile_command_outcome(panel_id, state)
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

    async def _read_due_poll_groups(
        self, panel_id: str, transport: ModbusTransport, state: PanelState, unit_id: int
    ) -> None:
        """Honor the map's sampling intervals instead of reading every point every second."""
        now = time.monotonic()
        telemetry_names: set[str] = set()
        alarm_names: set[str] = set()
        groups = self._panel_register_maps.get(panel_id, self._register_map).poll_groups
        if not groups:
            await self._read_status_registers(transport, state, unit_id)
            await self._read_alarm_registers(transport, state, unit_id)
            return
        for group in groups:
            key = (panel_id, group.name)
            interval = max(group.interval_ms / 1000.0, self._poll_interval)
            if now - self._last_group_poll.get(key, 0.0) < interval:
                continue
            for name in group.register_names:
                if name.startswith("alarm_condition_"):
                    alarm_names.add(name)
                else:
                    telemetry_names.add(name)
            self._last_group_poll[key] = now
        if telemetry_names:
            await self._read_status_registers(transport, state, unit_id, telemetry_names)
        if alarm_names:
            await self._read_alarm_registers(transport, state, unit_id, alarm_names)

    async def _read_status_registers(
        self, transport: ModbusTransport, state: PanelState, unit_id: int,
        register_names: set[str] | None = None,
    ) -> None:
        """Read every configured telemetry point into normalized panel state.

        Alarm bitfields are handled separately so they can produce transition
        events. Writable setpoints are intentionally not treated as telemetry.
        """
        rmap = self._panel_register_maps.get(state.panel_id, self._register_map)
        adapter = self._adapters.get(state.panel_id) or create_adapter("dse_86xx_mkii", rmap)
        attempted = 0
        successful = 0
        for reg in rmap.readable_registers():
            if reg.fields or reg.access == "readwrite":
                continue
            if register_names is not None and reg.name not in register_names:
                continue
            attempted += 1
            raw = await self._read_register(transport, reg, unit_id)
            if raw is None:
                state.reading_quality[reg.name] = "unavailable"
                continue
            successful += 1
            adapter.apply_reading(state, reg, raw)
        if attempted and successful == 0:
            raise TransportError("No telemetry registers responded")

    async def _read_alarm_registers(
        self, transport: ModbusTransport, state: PanelState, unit_id: int,
        register_names: set[str] | None = None,
    ) -> None:
        """Read packed four-bit GenComm alarm condition codes."""
        rmap = self._panel_register_maps.get(state.panel_id, self._register_map)
        active_alarms: list[str] = []

        for alarm_name, reg in rmap.registers.items():
            if not alarm_name.startswith("alarm_condition_"):
                continue
            if register_names is not None and alarm_name not in register_names:
                continue
            if not reg.fields:
                continue
            raw = await self._read_register(transport, reg, unit_id)
            if raw is None:
                continue
            for field in reg.fields:
                condition = (raw >> int(field["shift"])) & int(field.get("mask", 15))
                # GenComm conditions 2/3/4 are alarms. Code 10 is an active
                # indication, so it is intentionally not treated as a fault.
                if condition in {2, 3, 4}:
                    severity = {2: "warning", 3: "shutdown", 4: "electrical_trip"}[condition]
                    active_alarms.append(f"{field['name']}:{severity}")

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
                raw = (values[0] << 16) | values[1]
                if reg.data_type == "int32" and raw >= 0x80000000:
                    raw -= 0x100000000
                return raw

            raw = values[0]
            # Handle signed types
            if reg.data_type == "int16" and raw >= 0x8000:
                raw -= 0x10000
            return raw

        except TransportError:
            return None

    # ── Command Writes ────────────────────────────────────────────────

    async def _command_status(self, command_id: str, panel_id: str, command: str, status: str,
                              triggered_by: str, reason: str = "", user_id: str | None = None,
                              detail: str | None = None) -> None:
        if not self._command_logger:
            return
        result = self._command_logger(
            command_id=command_id, panel_id=panel_id, command=command, status=status,
            triggered_by=triggered_by, reason=reason, user_id=user_id, detail=detail,
        )
        if asyncio.iscoroutine(result):
            await result

    async def _reconcile_command_outcome(self, panel_id: str, state: PanelState) -> None:
        pending = self._pending_commands.get(panel_id)
        if not pending:
            return
        target = pending["target"]
        age = (datetime.now(timezone.utc) - pending["acknowledged_at"]).total_seconds()
        if state.engine_status == target:
            await self._command_status(**pending["log"], status="confirmed", detail=f"Observed engine state: {target}")
            self._pending_commands.pop(panel_id, None)
        elif age >= 45:
            await self._command_status(**pending["log"], status="unknown", detail=f"No physical {target} confirmation within 45 seconds")
            self._pending_commands.pop(panel_id, None)

    async def _validate_safe_to_start(self, panel_id: str) -> tuple[bool, str]:
        """Check that starting this panel is safe (no faults)."""
        state = self._states.get(panel_id)
        if not state:
            return False, f"Panel {panel_id} state unknown"

        # Check for active alarms
        if state.active_alarms:
            return False, f"Cannot start panel with active alarms: {', '.join(state.active_alarms)}"

        return True, "Safe to start"

    async def send_remote_start(
        self,
        panel_id: str,
        triggered_by: str = "manual",
        reason: str = "",
        user_id: str | None = None,
        load_kw_at_decision: float | None = None,
        capacity_pct_at_decision: float | None = None,
        command_id: str | None = None,
    ) -> tuple[bool, str]:
        """Send Remote Start to a panel, respecting cooldown.

        Returns (success, message).
        """
        command_id = command_id or str(uuid.uuid4())
        command_log = dict(command_id=command_id, panel_id=panel_id, command="remote_start",
                           triggered_by=triggered_by, reason=reason, user_id=user_id)
        await self._command_status(**command_log, status="requested")
        # Safety check
        safe_to_start, safe_msg = await self._validate_safe_to_start(panel_id)
        if not safe_to_start:
            logger.warning("Start blocked for %s: %s", panel_id, safe_msg)
            await self._command_status(**command_log, status="rejected", detail=safe_msg)
            return False, safe_msg

        # Check cooldown
        cd_result = self._cooldown.check_start(panel_id)
        if not cd_result.allowed:
            logger.info("Start blocked by cooldown for %s: %s", panel_id, cd_result.reason)
            await self._command_status(**command_log, status="rejected", detail=cd_result.reason)
            return False, cd_result.reason

        adapter = self._adapters.get(panel_id)
        command_write = adapter.command_write("remote_start") if adapter else None
        if not command_write:
            await self._command_status(**command_log, status="failed", detail="Command not supported")
            return False, "remote_start is not supported by this controller profile"

        config = self._panel_configs.get(panel_id)
        if not config:
            await self._command_status(**command_log, status="failed", detail="Panel not registered")
            return False, f"Panel {panel_id} not registered"

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            await self._command_status(**command_log, status="failed", detail="Panel not connected")
            return False, f"Panel {panel_id} not connected"

        try:
            async with self._io_locks.setdefault(panel_id, asyncio.Lock()):
                await transport.write_registers(
                    command_write.address, list(command_write.values), config["unit_id"]
                )
            self._cooldown.record_start(panel_id)

            state = self._states.get(panel_id)
            previous_state = state.engine_status if state else "unknown"
            if state:
                state.last_command = "remote_start"
                state.last_command_id = command_id
                state.last_command_time = datetime.now(timezone.utc)
            await self._command_status(**command_log, status="acknowledged", detail="Controller write acknowledged")
            self._pending_commands[panel_id] = {
                "target": "running", "acknowledged_at": datetime.now(timezone.utc), "log": command_log,
            }

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
            await self._command_status(**command_log, status="unknown", detail=str(exc))
            return False, msg

    async def _validate_safe_to_stop(self, panel_id: str, triggered_by: str = "manual",
                                     adaptive_safety: dict | None = None) -> tuple[bool, str]:
        """Check that stopping this panel won't violate capacity/reserve.
        
        Only an explicit customer override may bypass the capacity check.
        """
        if triggered_by == "override":
            return True, "Safe to stop"

        state = self._states.get(panel_id)
        if not state or not state.is_running:
            return True, "Panel not running, safe to send stop"

        if triggered_by == "adaptive_dispatch":
            context = adaptive_safety or {}
            checked_at = context.get("checked_at")
            if (not checked_at or (datetime.now(timezone.utc) - checked_at).total_seconds() > 5 or
                    context.get("site_id") != state.site_id or not context.get("source_fresh")):
                return False, "Adaptive stop requires a fresh verified site measurement"
            target_ids = set(context.get("target_ids") or []) - {panel_id}
            remaining_capacity = 0.0
            for other_id in target_ids:
                other = self._states.get(other_id)
                if (not other or other.site_id != state.site_id or not other.is_running or
                        not other.is_reachable or not other.is_data_fresh or
                        not other.generator_breaker or other.reading_quality.get("generator_breaker") != "good"):
                    return False, "Replacement generator is not confirmed connected"
                remaining_capacity += float(self._panel_configs.get(other_id, {}).get("rated_kw", 0)) * float(context.get("max_load_percent", 80)) / 100
            if remaining_capacity + 1e-6 < float(context.get("required_kw", 0)):
                return False, "Confirmed remaining generator capacity is below required reserve"
            return True, "Adaptive site capacity verified"

        config = self._panel_configs.get(panel_id, {})
        site_id = config.get("site_id")

        # Calculate remaining rated capacity of running panels at this site
        remaining_capacity = sum(
            self._panel_configs.get(pid, {}).get("rated_kw", 0.0)
            for pid, s in self._states.items()
            if pid != panel_id and s.site_id == site_id and s.is_running and s.is_reachable
        )

        # Calculate current site load
        current_site_load = sum(
            s.load_kw for s in self._states.values()
            if s.site_id == site_id and s.is_running
        )

        if remaining_capacity < current_site_load:
            return False, f"Stopping {panel_id} would exceed remaining capacity. Load: {current_site_load:.1f}kW, Remaining capacity: {remaining_capacity:.1f}kW"

        return True, "Safe to stop"

    async def send_remote_stop(
        self,
        panel_id: str,
        triggered_by: str = "manual",
        reason: str = "",
        user_id: str | None = None,
        load_kw_at_decision: float | None = None,
        capacity_pct_at_decision: float | None = None,
        command_id: str | None = None,
        adaptive_safety: dict | None = None,
    ) -> tuple[bool, str]:
        """Send Remote Stop to a panel, respecting cooldown and capacity guard."""
        command_id = command_id or str(uuid.uuid4())
        command_log = dict(command_id=command_id, panel_id=panel_id, command="remote_stop",
                           triggered_by=triggered_by, reason=reason, user_id=user_id)
        await self._command_status(**command_log, status="requested")
        # 1. Capacity guard check
        safe_to_stop, safe_msg = await self._validate_safe_to_stop(
            panel_id, triggered_by=triggered_by, adaptive_safety=adaptive_safety)
        if not safe_to_stop:
            logger.warning("Stop blocked for %s: %s", panel_id, safe_msg)
            await self._command_status(**command_log, status="rejected", detail=safe_msg)
            return False, safe_msg

        # 2. Cooldown check
        cd_result = self._cooldown.check_stop(panel_id)
        if not cd_result.allowed:
            logger.info("Stop blocked by cooldown for %s: %s", panel_id, cd_result.reason)
            await self._command_status(**command_log, status="rejected", detail=cd_result.reason)
            return False, cd_result.reason

        adapter = self._adapters.get(panel_id)
        command_write = adapter.command_write("remote_stop") if adapter else None
        if not command_write:
            await self._command_status(**command_log, status="failed", detail="Command not supported")
            return False, "remote_stop is not supported by this controller profile"

        config = self._panel_configs.get(panel_id)
        if not config:
            await self._command_status(**command_log, status="failed", detail="Panel not registered")
            return False, f"Panel {panel_id} not registered"

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            await self._command_status(**command_log, status="failed", detail="Panel not connected")
            return False, f"Panel {panel_id} not connected"

        try:
            async with self._io_locks.setdefault(panel_id, asyncio.Lock()):
                await transport.write_registers(
                    command_write.address, list(command_write.values), config["unit_id"]
                )
            self._cooldown.record_stop(panel_id)

            state = self._states.get(panel_id)
            previous_state = state.engine_status if state else "unknown"
            if state:
                state.last_command = "remote_stop"
                state.last_command_id = command_id
                state.last_command_time = datetime.now(timezone.utc)
            await self._command_status(**command_log, status="acknowledged", detail="Controller write acknowledged")
            self._pending_commands[panel_id] = {
                "target": "stopped", "acknowledged_at": datetime.now(timezone.utc), "log": command_log,
            }

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
            await self._command_status(**command_log, status="unknown", detail=str(exc))
            return False, msg

    async def write_power_setpoint(
        self,
        panel_id: str,
        kw_pct: int,
        triggered_by: str = "manual",
        reason: str = "",
        user_id: str | None = None,
        command_id: str | None = None,
    ) -> tuple[bool, str]:
        """Write a fixed-power kW setpoint to a panel."""
        command_id = command_id or str(uuid.uuid4())
        command_log = dict(command_id=command_id, panel_id=panel_id, command="set_power",
                           triggered_by=triggered_by, reason=reason, user_id=user_id)
        await self._command_status(**command_log, status="requested")
        rmap = self._panel_register_maps.get(panel_id, self._register_map)
        reg = rmap.get("fixed_power_setpoint_kw")
        if not reg:
            await self._command_status(**command_log, status="failed", detail="Setpoint not supported")
            return False, "fixed_power_setpoint_kw register not defined"

        config = self._panel_configs.get(panel_id)
        if not config:
            await self._command_status(**command_log, status="failed", detail="Panel not registered")
            return False, f"Panel {panel_id} not registered"

        transport = self._transports.get(panel_id)
        if not transport or not transport.is_connected:
            await self._command_status(**command_log, status="failed", detail="Panel not connected")
            return False, f"Panel {panel_id} not connected"

        try:
            async with self._io_locks.setdefault(panel_id, asyncio.Lock()):
                await transport.write_register(reg.address, kw_pct, config["unit_id"])
            await self._command_status(**command_log, status="confirmed", detail="Setpoint write acknowledged by controller")

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
            await self._command_status(**command_log, status="unknown", detail=str(exc))
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
                    # Engine is idle — ensure it is ready to start if needed
                    self._cooldown.reset(panel_id)
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
        """Read all known registers for a panel (customer diagnostics).

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

        async with self._io_locks.setdefault(panel_id, asyncio.Lock()):
            rmap = self._panel_register_maps.get(panel_id, self._register_map)
            adapter = self._adapters.get(panel_id)
            for name, reg in rmap.registers.items():
                if not reg.is_readable:
                    continue
                raw = await self._read_register(transport, reg, unit_id)
                scaled = adapter.decode_reading(reg, raw) if raw is not None and adapter else (
                    raw * reg.scale if raw is not None else None
                )
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
