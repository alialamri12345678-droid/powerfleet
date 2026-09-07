"""
DSE 8620/8610 MKII Generator Simulator
========================================
A standalone visual simulator that acts as a Modbus TCP server,
emulating real DSE generator controllers. Run this separately
from the Power Fleet backend to test real Modbus communication.

Usage:
    python dse_simulator.py                    # Default: 3 generators on port 5020
    python dse_simulator.py --port 5021        # Custom port
    python dse_simulator.py --units 5          # 5 generators
    python dse_simulator.py --port 5021 --units 4

Then point your Power Fleet generators to 127.0.0.1:<port>
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import math
import random
import sys
import threading
import time
import tkinter as tk
from tkinter import ttk, messagebox
from pathlib import Path

# ── Modbus imports ──────────────────────────────────────────────────
from pymodbus.datastore import (
    ModbusSequentialDataBlock,
    ModbusServerContext,
    ModbusSlaveContext,
)
from pymodbus.server import StartAsyncTcpServer

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("dse_simulator")

# ── DSE Register Map (matches Power Fleet register_map.yaml) ──────
REGISTERS = {
    "engine_status":        {"addr": 0x0100, "type": "uint16", "scale": 1},
    "load_kw":              {"addr": 0x0110, "type": "uint16", "scale": 0.1},
    "load_kw_percent":      {"addr": 0x0112, "type": "uint16", "scale": 1},
    "load_kvar":            {"addr": 0x0114, "type": "uint16", "scale": 0.1},
    "frequency":            {"addr": 0x0130, "type": "uint16", "scale": 0.1},
    "voltage_l1_n":         {"addr": 0x0120, "type": "uint16", "scale": 0.1},
    "voltage_l2_n":         {"addr": 0x0121, "type": "uint16", "scale": 0.1},
    "voltage_l3_n":         {"addr": 0x0122, "type": "uint16", "scale": 0.1},
    "coolant_temperature":  {"addr": 0x0140, "type": "uint16", "scale": 1},
    "oil_pressure":         {"addr": 0x0142, "type": "uint16", "scale": 0.1},
    "battery_voltage":      {"addr": 0x0144, "type": "uint16", "scale": 0.1},
    "engine_speed":         {"addr": 0x0146, "type": "uint16", "scale": 1},
    "run_hours":            {"addr": 0x0150, "type": "uint32", "scale": 0.1},
    "total_kwh":            {"addr": 0x0152, "type": "uint32", "scale": 1},
    "number_of_starts":     {"addr": 0x0154, "type": "uint32", "scale": 1},
    "alarm_word_1":         {"addr": 0x0200, "type": "uint16", "scale": 1},
    "alarm_word_2":         {"addr": 0x0201, "type": "uint16", "scale": 1},
    "alarm_word_3":         {"addr": 0x0202, "type": "uint16", "scale": 1},
    "remote_start":         {"addr": 0x0300, "type": "coil", "scale": 1},
    "remote_stop":          {"addr": 0x0301, "type": "coil", "scale": 1},
}

# ── Engine States ─────────────────────────────────────────────────
STATUS_STOPPED  = 0
STATUS_PREHEAT  = 1
STATUS_CRANKING = 2
STATUS_RUNNING  = 3
STATUS_COOLDOWN = 4
STATUS_FAULT    = 5

STATUS_NAMES = {
    STATUS_STOPPED:  "STOPPED",
    STATUS_PREHEAT:  "PREHEAT",
    STATUS_CRANKING: "CRANKING",
    STATUS_RUNNING:  "RUNNING",
    STATUS_COOLDOWN: "COOLDOWN",
    STATUS_FAULT:    "FAULT",
}

STATUS_COLORS = {
    STATUS_STOPPED:  "#6B7280",  # gray
    STATUS_PREHEAT:  "#F59E0B",  # amber
    STATUS_CRANKING: "#F97316",  # orange
    STATUS_RUNNING:  "#10B981",  # green
    STATUS_COOLDOWN: "#3B82F6",  # blue
    STATUS_FAULT:    "#EF4444",  # red
}


# ═══════════════════════════════════════════════════════════════════
# Simulated Generator Panel
# ═══════════════════════════════════════════════════════════════════
class SimulatedGenerator:
    """Full simulation of a DSE generator controller."""

    def __init__(self, unit_id: int, name: str, rated_kw: float = 500.0):
        self.unit_id = unit_id
        self.name = name
        self.rated_kw = rated_kw

        # State machine
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
        self.run_hours = round(random.uniform(500, 5000), 1)
        self.total_kwh = round(random.uniform(10000, 100000), 0)
        self.start_count = random.randint(100, 2000)

        # Control inputs from Modbus
        self.remote_start_input = False
        self.remote_stop_input = False

        # Alarms
        self.alarm_words = [0, 0, 0]
        self._fault_timer: float | None = None

        # Manual load override (-1 means auto)
        self.manual_load_percent = -1

        # Modbus command counter (for GUI display)
        self.start_commands_received = 0
        self.stop_commands_received = 0

    def update(self, dt: float) -> None:
        """Advance simulation by dt seconds."""
        now = time.monotonic()
        time_in_state = now - self._state_enter_time

        # Handle remote start/stop
        if self.remote_start_input and self.engine_status == STATUS_STOPPED:
            self._transition(STATUS_PREHEAT)
            self.remote_start_input = False
            self.start_commands_received += 1

        if self.remote_stop_input and self.engine_status == STATUS_RUNNING:
            self._transition(STATUS_COOLDOWN)
            self.remote_stop_input = False
            self.stop_commands_received += 1

        # State machine transitions
        if self.engine_status == STATUS_PREHEAT:
            self.coolant_temp = min(40, self.coolant_temp + dt * 2)
            if time_in_state > 3.0:
                self._transition(STATUS_CRANKING)

        elif self.engine_status == STATUS_CRANKING:
            self.engine_speed = min(1800, int(600 + time_in_state * 400))
            if time_in_state > 3.0:
                self._transition(STATUS_RUNNING)
                self.start_count += 1

        elif self.engine_status == STATUS_RUNNING:
            self.engine_speed = 1800 + random.randint(-5, 5)
            self.frequency = 60.0 + random.uniform(-0.2, 0.2)
            self.voltage = 480.0 + random.uniform(-3.0, 3.0)

            # Load calculation
            if self.manual_load_percent >= 0:
                self.load_kw_percent = self.manual_load_percent
            else:
                base_load = 50 + 30 * math.sin(now / 120)
                noise = random.uniform(-5, 5)
                self.load_kw_percent = max(0, min(100, base_load + noise))

            self.load_kw = self.rated_kw * self.load_kw_percent / 100
            self.load_kvar = self.load_kw * 0.3 + random.uniform(-5, 5)

            # Engine health
            self.coolant_temp = min(95, self.coolant_temp + dt * 0.5) + random.uniform(-0.5, 0.5)
            self.oil_pressure = 4.0 + random.uniform(-0.2, 0.2)
            self.battery_voltage = 27.5 + random.uniform(-0.3, 0.3)

            # Accumulate
            self.run_hours += dt / 3600
            self.total_kwh += self.load_kw * dt / 3600

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

        # Clear timed alarms
        if self._fault_timer and now > self._fault_timer:
            self.alarm_words = [0, 0, 0]
            self._fault_timer = None

    def manual_start(self):
        """Manually start from the GUI."""
        if self.engine_status == STATUS_STOPPED:
            self._transition(STATUS_PREHEAT)

    def manual_stop(self):
        """Manually stop from the GUI."""
        if self.engine_status == STATUS_RUNNING:
            self._transition(STATUS_COOLDOWN)

    def inject_fault(self, fault_type: str = "high_coolant"):
        """Inject a fault for testing."""
        if fault_type == "high_coolant":
            self.alarm_words[0] |= (1 << 2)
        elif fault_type == "low_oil":
            self.alarm_words[0] |= (1 << 3)
        elif fault_type == "overspeed":
            self.alarm_words[1] |= (1 << 0)
        elif fault_type == "fail_to_start":
            self.alarm_words[2] |= (1 << 3)
        self._transition(STATUS_FAULT)

    def clear_fault(self):
        """Clear all faults and return to stopped."""
        self.alarm_words = [0, 0, 0]
        self._transition(STATUS_STOPPED)

    def _transition(self, new_status: int) -> None:
        old_name = STATUS_NAMES.get(self.engine_status, "?")
        new_name = STATUS_NAMES.get(new_status, "?")
        logger.info("Generator %s (Unit %d): %s → %s", self.name, self.unit_id, old_name, new_name)
        self.engine_status = new_status
        self._state_enter_time = time.monotonic()


# ═══════════════════════════════════════════════════════════════════
# Modbus TCP Server (runs in asyncio thread)
# ═══════════════════════════════════════════════════════════════════
class ModbusServerThread:
    """Runs the pymodbus TCP server in a background thread."""

    def __init__(self, generators: dict[int, SimulatedGenerator], host: str, port: int):
        self.generators = generators
        self.host = host
        self.port = port
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self.is_running = False
        self.poll_count = 0

    def start(self):
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as e:
            logger.error("Modbus server error: %s", e)

    async def _serve(self):
        # Build slave contexts
        slaves = {}
        for unit_id in self.generators:
            hr_block = ModbusSequentialDataBlock(0x0000, [0] * 0x0400)
            co_block = ModbusSequentialDataBlock(0x0000, [0] * 0x0400)
            slaves[unit_id] = ModbusSlaveContext(
                di=ModbusSequentialDataBlock(0, [0] * 100),
                co=co_block,
                hr=hr_block,
                ir=ModbusSequentialDataBlock(0, [0] * 100),
            )

        context = ModbusServerContext(slaves=slaves, single=False)

        # Start the register update loop
        asyncio.create_task(self._update_loop(context))

        self.is_running = True
        logger.info("Modbus TCP server listening on %s:%d", self.host, self.port)

        await StartAsyncTcpServer(context=context, address=(self.host, self.port))

    async def _update_loop(self, context: ModbusServerContext):
        """Update registers from generator state + check coils for commands."""
        while True:
            for unit_id, gen in self.generators.items():
                gen.update(0.5)
                slave = context[unit_id]

                # ── Write telemetry to holding registers ──
                def set_hr(name: str, value: int):
                    reg = REGISTERS.get(name)
                    if reg and reg["type"] == "uint16":
                        try:
                            slave.setValues(3, reg["addr"], [value & 0xFFFF])
                        except Exception:
                            pass

                def set_hr32(name: str, value: int):
                    reg = REGISTERS.get(name)
                    if reg and reg["type"] == "uint32":
                        high = (value >> 16) & 0xFFFF
                        low = value & 0xFFFF
                        try:
                            slave.setValues(3, reg["addr"], [high, low])
                        except Exception:
                            pass

                set_hr("engine_status", gen.engine_status)
                set_hr("load_kw", int(gen.load_kw / REGISTERS["load_kw"]["scale"]))
                set_hr("load_kw_percent", int(gen.load_kw_percent))
                set_hr("load_kvar", int(gen.load_kvar / REGISTERS["load_kvar"]["scale"]))
                set_hr("frequency", int(gen.frequency / REGISTERS["frequency"]["scale"]))

                raw_v = int(gen.voltage / REGISTERS["voltage_l1_n"]["scale"])
                set_hr("voltage_l1_n", raw_v)
                set_hr("voltage_l2_n", raw_v)
                set_hr("voltage_l3_n", raw_v)

                set_hr("coolant_temperature", int(gen.coolant_temp))
                set_hr("oil_pressure", int(gen.oil_pressure / REGISTERS["oil_pressure"]["scale"]))
                set_hr("battery_voltage", int(gen.battery_voltage / REGISTERS["battery_voltage"]["scale"]))
                set_hr("engine_speed", gen.engine_speed)

                set_hr32("run_hours", int(gen.run_hours / REGISTERS["run_hours"]["scale"]))
                set_hr32("total_kwh", int(gen.total_kwh))
                set_hr32("number_of_starts", gen.start_count)

                set_hr("alarm_word_1", gen.alarm_words[0])
                set_hr("alarm_word_2", gen.alarm_words[1])
                set_hr("alarm_word_3", gen.alarm_words[2])

                # ── Check coils for remote commands from SCADA ──
                start_addr = REGISTERS["remote_start"]["addr"]
                stop_addr = REGISTERS["remote_stop"]["addr"]

                try:
                    start_val = slave.getValues(1, start_addr, 1)
                    if start_val and start_val[0]:
                        gen.remote_start_input = True
                        slave.setValues(1, start_addr, [False])
                        logger.info("⚡ MODBUS START command received for Unit %d (%s)", unit_id, gen.name)
                except Exception:
                    pass

                try:
                    stop_val = slave.getValues(1, stop_addr, 1)
                    if stop_val and stop_val[0]:
                        gen.remote_stop_input = True
                        slave.setValues(1, stop_addr, [False])
                        logger.info("🛑 MODBUS STOP command received for Unit %d (%s)", unit_id, gen.name)
                except Exception:
                    pass

            self.poll_count += 1
            await asyncio.sleep(0.5)


# ═══════════════════════════════════════════════════════════════════
# Tkinter GUI
# ═══════════════════════════════════════════════════════════════════
class SimulatorGUI:
    """Visual control panel for the DSE generator simulator."""

    def __init__(self, generators: dict[int, SimulatedGenerator], server: ModbusServerThread):
        self.generators = generators
        self.server = server

        self.root = tk.Tk()
        self.root.title(f"DSE Generator Simulator — Modbus TCP on port {server.port}")
        self.root.configure(bg="#1a1d21")
        self.root.geometry("1100x700")
        self.root.minsize(900, 500)

        # Style
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#1a1d21")
        style.configure("TLabel", background="#1a1d21", foreground="#e5e7eb", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 11, "bold"), foreground="#ffffff")
        style.configure("Header.TLabel", font=("Segoe UI", 10, "bold"), foreground="#9ca3af")
        style.configure("Value.TLabel", font=("Consolas", 10), foreground="#60a5fa")
        style.configure("Big.TLabel", font=("Consolas", 14, "bold"), foreground="#10b981")
        style.configure("Status.TLabel", font=("Segoe UI", 11, "bold"))

        self.facility_load_var = tk.IntVar(value=-1)  # -1 means disabled

        self._build_ui()
        self._update_gui()

    def _build_ui(self):
        # ── Top bar ──
        top = ttk.Frame(self.root, padding=10)
        top.pack(fill="x")

        ttk.Label(top, text="⚡ DSE 8620/8610 Generator Simulator", style="Title.TLabel").pack(side="left")

        self.server_label = ttk.Label(top, text=f"Modbus TCP — 127.0.0.1:{self.server.port}", style="Header.TLabel")
        self.server_label.pack(side="right", padx=10)

        self.poll_label = ttk.Label(top, text="Polls: 0", style="Value.TLabel")
        self.poll_label.pack(side="right", padx=10)

        # ── Separator ──
        sep = tk.Frame(self.root, height=1, bg="#374151")
        sep.pack(fill="x", padx=10, pady=(0, 10))

        # ── Facility Load Control ──
        fac_frame = ttk.Frame(self.root, padding=(10, 0, 10, 10))
        fac_frame.pack(fill="x")
        
        ttk.Label(fac_frame, text="Total Facility Load %:", style="Header.TLabel").pack(side="left")
        
        self.fac_slider = tk.Scale(
            fac_frame, from_=-1, to=100, orient="horizontal",
            variable=self.facility_load_var, bg="#1a1d21", fg="#10b981",
            troughcolor="#374151", highlightthickness=0, font=("Consolas", 10, "bold"),
            length=400, sliderlength=20
        )
        self.fac_slider.pack(side="left", padx=10)
        
        ttk.Label(fac_frame, text="(-1 = use individual generator sliders)").pack(side="left")

        # ── Separator ──
        sep2 = tk.Frame(self.root, height=1, bg="#374151")
        sep2.pack(fill="x", padx=10)

        # ── Generator panels (scrollable) ──
        container = ttk.Frame(self.root)
        container.pack(fill="both", expand=True, padx=10, pady=10)

        self.gen_frames: dict[int, dict] = {}

        for i, (unit_id, gen) in enumerate(self.generators.items()):
            frame = self._build_gen_panel(container, gen)
            frame.grid(row=i // 3, column=i % 3, padx=6, pady=6, sticky="nsew")

        # Make columns expand equally
        for c in range(min(3, len(self.generators))):
            container.columnconfigure(c, weight=1)

        # ── Bottom status bar ──
        bottom = ttk.Frame(self.root, padding=(10, 5))
        bottom.pack(fill="x", side="bottom")

        self.status_label = ttk.Label(bottom, text="Ready — Waiting for SCADA connection...", style="Header.TLabel")
        self.status_label.pack(side="left")

        ttk.Label(bottom, text="Power Fleet DSE Simulator v1.0", style="Header.TLabel").pack(side="right")

    def _build_gen_panel(self, parent, gen: SimulatedGenerator) -> ttk.Frame:
        """Build a visual panel for one generator."""
        outer = tk.Frame(parent, bg="#262a30", highlightbackground="#374151", highlightthickness=1, padx=12, pady=10)

        # Header
        header = tk.Frame(outer, bg="#262a30")
        header.pack(fill="x", pady=(0, 8))

        tk.Label(header, text=f"Unit {gen.unit_id}", bg="#262a30", fg="#9ca3af",
                 font=("Segoe UI", 8)).pack(side="right")
        tk.Label(header, text=gen.name, bg="#262a30", fg="#ffffff",
                 font=("Segoe UI", 11, "bold")).pack(side="left")

        # Status indicator
        status_frame = tk.Frame(outer, bg="#262a30")
        status_frame.pack(fill="x", pady=(0, 8))

        status_label = tk.Label(status_frame, text="● STOPPED", bg="#262a30", fg="#6B7280",
                                font=("Segoe UI", 12, "bold"))
        status_label.pack(side="left")

        rated_label = tk.Label(status_frame, text=f"{int(gen.rated_kw)} kW rated", bg="#262a30", fg="#6B7280",
                               font=("Segoe UI", 9))
        rated_label.pack(side="right")

        # Telemetry grid
        telemetry = tk.Frame(outer, bg="#2d3139")
        telemetry.pack(fill="x", pady=(0, 8))

        labels = {}
        fields = [
            ("Load", "kW", "load_kw"),
            ("Load %", "%", "load_pct"),
            ("Freq", "Hz", "freq"),
            ("Voltage", "V", "voltage"),
            ("RPM", "", "rpm"),
            ("Coolant", "°C", "coolant"),
            ("Oil", "bar", "oil"),
            ("Battery", "V", "battery"),
        ]

        for i, (label_text, unit, key) in enumerate(fields):
            row, col = divmod(i, 4)
            cell = tk.Frame(telemetry, bg="#2d3139", padx=6, pady=4)
            cell.grid(row=row, column=col, sticky="ew")
            telemetry.columnconfigure(col, weight=1)

            tk.Label(cell, text=label_text, bg="#2d3139", fg="#6B7280",
                     font=("Segoe UI", 7)).pack(anchor="w")
            val = tk.Label(cell, text="0", bg="#2d3139", fg="#60a5fa",
                           font=("Consolas", 10, "bold"))
            val.pack(anchor="w")
            labels[key] = val

        # Modbus command counters
        cmd_frame = tk.Frame(outer, bg="#262a30")
        cmd_frame.pack(fill="x", pady=(0, 6))

        tk.Label(cmd_frame, text="SCADA Commands:", bg="#262a30", fg="#6B7280",
                 font=("Segoe UI", 7)).pack(side="left")

        cmd_label = tk.Label(cmd_frame, text="START: 0  STOP: 0", bg="#262a30", fg="#f59e0b",
                             font=("Consolas", 8, "bold"))
        cmd_label.pack(side="right")

        # Control buttons
        btn_frame = tk.Frame(outer, bg="#262a30")
        btn_frame.pack(fill="x", pady=(4, 0))

        start_btn = tk.Button(btn_frame, text="▶ Start", bg="#065f46", fg="#ffffff",
                              activebackground="#047857", font=("Segoe UI", 9, "bold"),
                              relief="flat", padx=10, pady=3,
                              command=lambda g=gen: g.manual_start())
        start_btn.pack(side="left", padx=(0, 4))

        stop_btn = tk.Button(btn_frame, text="■ Stop", bg="#7f1d1d", fg="#ffffff",
                             activebackground="#991b1b", font=("Segoe UI", 9, "bold"),
                             relief="flat", padx=10, pady=3,
                             command=lambda g=gen: g.manual_stop())
        stop_btn.pack(side="left", padx=(0, 4))

        fault_btn = tk.Button(btn_frame, text="⚠ Fault", bg="#78350f", fg="#ffffff",
                              activebackground="#92400e", font=("Segoe UI", 9, "bold"),
                              relief="flat", padx=10, pady=3,
                              command=lambda g=gen: g.inject_fault("high_coolant"))
        fault_btn.pack(side="left", padx=(0, 4))

        clear_btn = tk.Button(btn_frame, text="✓ Clear", bg="#1e3a5f", fg="#ffffff",
                              activebackground="#1e40af", font=("Segoe UI", 9, "bold"),
                              relief="flat", padx=10, pady=3,
                              command=lambda g=gen: g.clear_fault())
        clear_btn.pack(side="left")

        # Load slider
        slider_frame = tk.Frame(outer, bg="#262a30")
        slider_frame.pack(fill="x", pady=(6, 0))

        tk.Label(slider_frame, text="Manual Load:", bg="#262a30", fg="#6B7280",
                 font=("Segoe UI", 8)).pack(side="left")

        auto_btn = tk.Button(slider_frame, text="Auto", bg="#374151", fg="#9ca3af",
                             font=("Segoe UI", 7), relief="flat", padx=6, pady=1,
                             command=lambda g=gen: setattr(g, 'manual_load_percent', -1))
        auto_btn.pack(side="right", padx=(4, 0))

        load_var = tk.IntVar(value=50)
        load_slider = tk.Scale(slider_frame, from_=0, to=100, orient="horizontal",
                               variable=load_var, bg="#262a30", fg="#60a5fa",
                               troughcolor="#374151", highlightthickness=0,
                               font=("Consolas", 7), length=120, sliderlength=12,
                               command=lambda v, g=gen: setattr(g, 'manual_load_percent', int(v)))
        load_slider.pack(side="right")

        self.gen_frames[gen.unit_id] = {
            "status_label": status_label,
            "labels": labels,
            "cmd_label": cmd_label,
            "load_slider": load_slider,
            "load_var": load_var,
        }

        return outer

    def _update_gui(self):
        """Periodic GUI update (runs on main thread)."""
        # Distribute facility load if active
        fac_load_pct = self.facility_load_var.get()
        if fac_load_pct >= 0:
            total_rated_kw = sum(g.rated_kw for g in self.generators.values())
            target_total_kw = total_rated_kw * (fac_load_pct / 100.0)
            
            running_gens = [g for g in self.generators.values() if g.engine_status in (4, 5)] # RUNNING or COOLDOWN
            
            if running_gens:
                # Distribute evenly across running gens
                kw_per_gen = target_total_kw / len(running_gens)
                for gen in running_gens:
                    pct = (kw_per_gen / gen.rated_kw) * 100.0
                    gen.manual_load_percent = min(110, int(pct)) # cap at 110%
                    
            # Idle gens get 0 load
            idle_gens = [g for g in self.generators.values() if g.engine_status not in (4, 5)]
            for gen in idle_gens:
                gen.manual_load_percent = 0

        for unit_id, gen in self.generators.items():
            f = self.gen_frames.get(unit_id)
            if not f:
                continue

            # Update slider to reflect actual manual load (useful if facility load is controlling it)
            if fac_load_pct >= 0 and gen.manual_load_percent != -1:
                f["load_var"].set(gen.manual_load_percent)

            # Status
            status_name = STATUS_NAMES.get(gen.engine_status, "UNKNOWN")
            status_color = STATUS_COLORS.get(gen.engine_status, "#6B7280")
            f["status_label"].config(text=f"● {status_name}", fg=status_color)

            # Telemetry values
            f["labels"]["load_kw"].config(text=f"{gen.load_kw:.0f} kW")
            f["labels"]["load_pct"].config(text=f"{gen.load_kw_percent:.0f}%")
            f["labels"]["freq"].config(text=f"{gen.frequency:.1f} Hz")
            f["labels"]["voltage"].config(text=f"{gen.voltage:.0f} V")
            f["labels"]["rpm"].config(text=f"{gen.engine_speed}")
            f["labels"]["coolant"].config(text=f"{gen.coolant_temp:.0f}°C")
            f["labels"]["oil"].config(text=f"{gen.oil_pressure:.1f} bar")
            f["labels"]["battery"].config(text=f"{gen.battery_voltage:.1f} V")

            # Command counters
            f["cmd_label"].config(
                text=f"START: {gen.start_commands_received}  STOP: {gen.stop_commands_received}"
            )

            # Color load based on percentage
            if gen.load_kw_percent > 80:
                f["labels"]["load_pct"].config(fg="#ef4444")
            elif gen.load_kw_percent > 50:
                f["labels"]["load_pct"].config(fg="#f59e0b")
            else:
                f["labels"]["load_pct"].config(fg="#10b981")

        # Poll counter
        self.poll_label.config(text=f"Polls: {self.server.poll_count}")

        # Status bar
        if self.server.is_running:
            self.status_label.config(text=f"✓ Modbus server running — {len(self.generators)} generators active")
        else:
            self.status_label.config(text="Starting Modbus server...")

        self.root.after(500, self._update_gui)

    def run(self):
        self.root.mainloop()


# ═══════════════════════════════════════════════════════════════════
# Main Entry Point
# ═══════════════════════════════════════════════════════════════════
def main():
    parser = argparse.ArgumentParser(description="DSE Generator Simulator with Modbus TCP")
    parser.add_argument("--host", default="127.0.0.1", help="Modbus TCP listen address")
    parser.add_argument("--port", type=int, default=5020, help="Modbus TCP port (default: 5020)")
    parser.add_argument("--units", type=int, default=3, help="Number of generator units (1-16)")
    args = parser.parse_args()

    num_units = max(1, min(16, args.units))

    # Create generators
    gen_names = [
        "Base Load", "Secondary", "Standby", "Peaker",
        "Backup A", "Backup B", "Emergency", "Auxiliary",
        "CHP Unit", "Island Gen", "Shore Power", "Portable",
        "Rooftop", "Container", "Tier-4", "Reserve",
    ]
    gen_kws = [500, 750, 500, 350, 600, 800, 450, 1000, 500, 750, 400, 650, 550, 900, 300, 1200]

    generators: dict[int, SimulatedGenerator] = {}
    for i in range(num_units):
        uid = i + 1
        generators[uid] = SimulatedGenerator(
            unit_id=uid,
            name=gen_names[i % len(gen_names)],
            rated_kw=gen_kws[i % len(gen_kws)],
        )

    # Start Modbus server in background thread
    server = ModbusServerThread(generators, args.host, args.port)
    server.start()

    # Give server time to bind
    time.sleep(0.5)

    # Launch GUI on main thread
    print(f"\n{'='*60}")
    print(f"  DSE Generator Simulator")
    print(f"  Modbus TCP Server: {args.host}:{args.port}")
    print(f"  Generators: {num_units}")
    print(f"{'='*60}")
    print(f"\n  Point your Power Fleet generators to:")
    print(f"  Address: {args.host}:{args.port}")
    print(f"  Unit IDs: 1 through {num_units}")
    print(f"\n  The GUI will show live telemetry and SCADA commands.\n")

    gui = SimulatorGUI(generators, server)
    gui.run()


if __name__ == "__main__":
    main()
