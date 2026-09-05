"""Mock Modbus server simulating DSE generator panels.

Provides a fully functional pymodbus TCP server with 2–4 simulated
generator panels. Each panel has realistic state transitions and
semi-random telemetry for development and testing without live hardware.

Run standalone:  python -m app.modbus.mock_server
"""

from __future__ import annotations

import asyncio
import logging
import math
import random
import time

from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

from app.config import settings
from app.modbus.register_map import load_register_map

logger = logging.getLogger(__name__)

# Engine status values (matches register_map.yaml)
STATUS_STOPPED = 0
STATUS_PREHEAT = 1
STATUS_CRANKING = 2
STATUS_RUNNING = 3
STATUS_COOLDOWN = 4
STATUS_FAULT = 5


class SimulatedPanel:
    """Simulates a single DSE generator panel's behavior."""

    def __init__(self, unit_id: int, name: str, rated_kw: float = 500.0):
        self.unit_id = unit_id
        self.name = name
        self.rated_kw = rated_kw

        # Engine state machine
        self.engine_status = STATUS_STOPPED
        self._state_enter_time = time.monotonic()

        # Telemetry
        self.load_kw = 0.0
        self.load_kw_percent = 0.0
        self.load_kvar = 0.0
        self.frequency = 0.0
        self.voltage = 0.0
        self.coolant_temp = 25.0
        self.oil_pressure = 0.0
        self.battery_voltage = 24.5
        self.engine_speed = 0
        self.run_hours = random.uniform(500, 5000)
        self.total_kwh = random.uniform(10000, 100000)
        self.start_count = random.randint(100, 2000)

        # Control inputs (latched — persist until explicitly changed)
        self.remote_start_input = False
        self.remote_stop_input = False

        # Alarm simulation
        self.alarm_words = [0, 0, 0]
        self._fault_timer: float | None = None

    def update(self, dt: float) -> None:
        """Advance the simulation by dt seconds."""
        now = time.monotonic()
        time_in_state = now - self._state_enter_time

        # Handle remote start/stop inputs
        if self.remote_start_input and self.engine_status == STATUS_STOPPED:
            self._transition(STATUS_PREHEAT)
            self.remote_start_input = False

        if self.remote_stop_input and self.engine_status == STATUS_RUNNING:
            self._transition(STATUS_COOLDOWN)
            self.remote_stop_input = False

        # State machine
        if self.engine_status == STATUS_PREHEAT:
            if time_in_state > 3.0:
                self._transition(STATUS_CRANKING)

        elif self.engine_status == STATUS_CRANKING:
            self.engine_speed = min(1800, int(600 + time_in_state * 400))
            if time_in_state > 3.0:
                # Small chance of fail-to-start
                if random.random() < 0.02:
                    self.alarm_words[2] |= (1 << 3)  # fail_to_start bit
                    self._transition(STATUS_FAULT)
                else:
                    self._transition(STATUS_RUNNING)
                    self.start_count += 1

        elif self.engine_status == STATUS_RUNNING:
            self.engine_speed = 1800 + random.randint(-5, 5)
            self.frequency = 60.0 + random.uniform(-0.2, 0.2)
            self.voltage = 480.0 + random.uniform(-3.0, 3.0)

            # Load varies with a slow sine wave + noise
            base_load = 50 + 30 * math.sin(now / 120)
            noise = random.uniform(-5, 5)
            self.load_kw_percent = max(0, min(100, base_load + noise))
            self.load_kw = self.rated_kw * self.load_kw_percent / 100
            self.load_kvar = self.load_kw * 0.3 + random.uniform(-5, 5)

            # Engine health
            self.coolant_temp = min(95, self.coolant_temp + dt * 0.5) + random.uniform(-0.5, 0.5)
            self.oil_pressure = 4.0 + random.uniform(-0.2, 0.2)
            self.battery_voltage = 27.5 + random.uniform(-0.3, 0.3)

            # Accumulate run hours
            self.run_hours += dt / 3600
            self.total_kwh += self.load_kw * dt / 3600

            # Random fault injection (rare)
            if random.random() < 0.001:
                self.alarm_words[0] |= (1 << 2)  # high_coolant_temp
                self._fault_timer = now + 30  # Clear after 30s

        elif self.engine_status == STATUS_COOLDOWN:
            self.engine_speed = max(0, 1800 - int(time_in_state * 300))
            self.load_kw = 0
            self.load_kw_percent = 0
            self.load_kvar = 0
            self.coolant_temp = max(25, self.coolant_temp - dt * 2)
            if time_in_state > 5.0:
                self._transition(STATUS_STOPPED)

        elif self.engine_status == STATUS_STOPPED:
            self.engine_speed = 0
            self.frequency = 0
            self.voltage = 0
            self.load_kw = 0
            self.load_kw_percent = 0
            self.load_kvar = 0
            self.oil_pressure = 0
            self.coolant_temp = max(25, self.coolant_temp - dt * 0.5)

        elif self.engine_status == STATUS_FAULT:
            self.engine_speed = 0
            self.load_kw = 0
            self.load_kw_percent = 0
            # Auto-clear fault after some time (simulates reset)
            if time_in_state > 60:
                self.alarm_words = [0, 0, 0]
                self._transition(STATUS_STOPPED)

        # Clear timed alarms
        if self._fault_timer and now > self._fault_timer:
            self.alarm_words = [0, 0, 0]
            self._fault_timer = None

    def _transition(self, new_status: int) -> None:
        logger.debug(
            "Panel %s: %d → %d", self.name, self.engine_status, new_status
        )
        self.engine_status = new_status
        self._state_enter_time = time.monotonic()


def _build_slave_context(panel: SimulatedPanel) -> ModbusSlaveContext:
    """Build a Modbus slave context with initial register values."""
    # Holding registers: 0x0000 – 0x0400 range
    hr_block = ModbusSequentialDataBlock(0x0000, [0] * 0x0400)
    # Coils: 0x0300 – 0x0320 range
    co_block = ModbusSequentialDataBlock(0x0000, [0] * 0x0400)

    return ModbusSlaveContext(
        di=ModbusSequentialDataBlock(0, [0] * 100),
        co=co_block,
        hr=hr_block,
        ir=ModbusSequentialDataBlock(0, [0] * 100),
    )


async def _update_registers(
    context: ModbusServerContext,
    panels: dict[int, SimulatedPanel],
    register_map,
) -> None:
    """Periodically update register values from simulated panel state."""
    while True:
        for unit_id, panel in panels.items():
            panel.update(0.5)

            slave = context[unit_id]

            def _set_hr(name: str, value: int):
                reg = register_map.get(name)
                if reg:
                    try:
                        slave.setValues(3, reg.address, [value & 0xFFFF])
                    except Exception:
                        pass

            def _set_hr_32(name: str, value: int):
                reg = register_map.get(name)
                if reg:
                    high = (value >> 16) & 0xFFFF
                    low = value & 0xFFFF
                    try:
                        slave.setValues(3, reg.address, [high, low])
                    except Exception:
                        pass

            # Write status
            _set_hr("engine_status", panel.engine_status)

            # Electrical — apply inverse scale
            load_kw_reg = register_map.get("load_kw")
            if load_kw_reg:
                raw_kw = int(panel.load_kw / load_kw_reg.scale) & 0xFFFF
                _set_hr("load_kw", raw_kw)

            _set_hr("load_kw_percent", int(panel.load_kw_percent))

            load_kvar_reg = register_map.get("load_kvar")
            if load_kvar_reg:
                raw_kvar = int(panel.load_kvar / load_kvar_reg.scale) & 0xFFFF
                _set_hr("load_kvar", raw_kvar)

            freq_reg = register_map.get("frequency")
            if freq_reg:
                _set_hr("frequency", int(panel.frequency / freq_reg.scale))

            volt_reg = register_map.get("voltage_l1_n")
            if volt_reg:
                raw_v = int(panel.voltage / volt_reg.scale)
                _set_hr("voltage_l1_n", raw_v)
                _set_hr("voltage_l2_n", raw_v)
                _set_hr("voltage_l3_n", raw_v)

            # Engine health
            _set_hr("coolant_temperature", int(panel.coolant_temp))
            oil_reg = register_map.get("oil_pressure")
            if oil_reg:
                _set_hr("oil_pressure", int(panel.oil_pressure / oil_reg.scale))
            batt_reg = register_map.get("battery_voltage")
            if batt_reg:
                _set_hr("battery_voltage", int(panel.battery_voltage / batt_reg.scale))
            _set_hr("engine_speed", panel.engine_speed)

            # Totals (32-bit)
            run_hours_reg = register_map.get("run_hours")
            if run_hours_reg:
                _set_hr_32("run_hours", int(panel.run_hours / run_hours_reg.scale))
            _set_hr_32("total_kwh", int(panel.total_kwh))
            _set_hr_32("number_of_starts", panel.start_count)

            # Alarm words
            _set_hr("alarm_word_1", panel.alarm_words[0])
            _set_hr("alarm_word_2", panel.alarm_words[1])
            _set_hr("alarm_word_3", panel.alarm_words[2])

            # Check coils for remote start/stop commands
            start_reg = register_map.get("remote_start")
            stop_reg = register_map.get("remote_stop")

            if start_reg:
                try:
                    coil_vals = slave.getValues(1, start_reg.address, 1)
                    if coil_vals and coil_vals[0]:
                        panel.remote_start_input = True
                        slave.setValues(1, start_reg.address, [False])  # Auto-clear
                except Exception:
                    pass

            if stop_reg:
                try:
                    coil_vals = slave.getValues(1, stop_reg.address, 1)
                    if coil_vals and coil_vals[0]:
                        panel.remote_stop_input = True
                        slave.setValues(1, stop_reg.address, [False])
                except Exception:
                    pass

        await asyncio.sleep(0.5)


async def run_mock_server(
    host: str | None = None,
    port: int | None = None,
    num_panels: int = 3,
) -> None:
    """Start the mock Modbus TCP server with simulated panels.

    Args:
        host: Listen address (default from settings)
        port: Listen port (default from settings)
        num_panels: Number of simulated generator panels (1-4)
    """
    host = host or settings.mock_modbus_host
    port = port or settings.mock_modbus_port

    register_map = load_register_map(settings.register_map_path)

    # Create simulated panels — pre-provision up to 16 units for dynamic panel additions
    panels: dict[int, SimulatedPanel] = {}
    default_kws = [500, 750, 500, 350, 600, 800, 450, 1000, 500, 750, 400, 650, 550, 900, 300, 1200]

    for i in range(16):
        unit_id = i + 1
        panels[unit_id] = SimulatedPanel(
            unit_id=unit_id,
            name=f"Generator {chr(65 + (i % 26))}",
            rated_kw=default_kws[i % len(default_kws)],
        )

    # Build server context
    slaves = {}
    for unit_id in panels:
        slaves[unit_id] = _build_slave_context(panels[unit_id])

    context = ModbusServerContext(slaves=slaves, single=False)

    # Start register update task
    update_task = asyncio.create_task(
        _update_registers(context, panels, register_map)
    )

    logger.info(
        "Mock Modbus server starting on %s:%d with %d panels",
        host, port, len(panels),
    )

    try:
        await StartAsyncTcpServer(
            context=context,
            address=(host, port),
        )
    finally:
        update_task.cancel()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_mock_server())
