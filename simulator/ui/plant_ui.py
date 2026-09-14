"""Plant overview and SCADA diagnostics UI."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
import tkinter as tk
from tkinter import messagebox, simpledialog, ttk

from configuration import ConfigurationError, SiteRepository
from runtime import SimulatorRuntime
from simulator_core.profiles import load_controller_profile_reference, load_generator_profile_reference
from simulation.faults import GENERATOR_FAULTS, inject_generator_fault, inject_grid_fault, inject_solar_fault
from simulation.plant import GeneratorState


MOCK_PARAMETERS = {
    "Fuel level": ("fuel_level_pct", "%"),
    "Coolant temperature": ("coolant_temperature_c", "°C"),
    "Oil pressure": ("oil_pressure_bar", "bar"),
    "Battery voltage": ("battery_voltage_v", "V"),
    "Engine speed": ("engine_speed_rpm", "RPM"),
    "Frequency": ("frequency_hz", "Hz"),
    "Active power": ("active_power_kw", "kW"),
    "Apparent power": ("apparent_power_kva", "kVA"),
    "Reactive power": ("reactive_power_kvar", "kVAr"),
    "Reactive load": ("reactive_load_pct", "%"),
    "L1-N voltage": ("voltage_l1_n_v", "V"),
    "L2-N voltage": ("voltage_l2_n_v", "V"),
    "L3-N voltage": ("voltage_l3_n_v", "V"),
    "L1-L2 voltage": ("voltage_l1_l2_v", "V"),
    "L2-L3 voltage": ("voltage_l2_l3_v", "V"),
    "L3-L1 voltage": ("voltage_l3_l1_v", "V"),
    "Current L1": ("current_l1_a", "A"),
    "Current L2": ("current_l2_a", "A"),
    "Current L3": ("current_l3_a", "A"),
    "Power L1": ("power_l1_kw", "kW"),
    "Power L2": ("power_l2_kw", "kW"),
    "Power L3": ("power_l3_kw", "kW"),
    "Power factor": ("power_factor", "PF"),
    "Energy produced": ("energy_produced_kwh", "kWh"),
    "Start count": ("start_count", ""),
    "Oil temperature": ("oil_temperature_c", "°C"),
    "Charge alternator voltage": ("charge_alternator_voltage_v", "V"),
    "Fuel used": ("fuel_used_l", "L"),
    "Generator state code": ("generator_state", "code"),
    "Manufacturer code": ("manufacturer_code", "code"),
    "Model number": ("model_number", "code"),
    "Control mode": ("control_mode", "code"),
    "Controller status": ("controller_status", "bits"),
}


class PlantSimulatorUI:
    def __init__(self, runtime: SimulatorRuntime):
        self.runtime = runtime
        self.restart_with: Path | None = None
        self.root = tk.Tk()
        self.root.title(f"SIMULATOR ONLY — {runtime.plant.name}")
        self.root.geometry("1280x820")
        self.root.minsize(1000, 650)
        self.root.configure(bg="#111827")
        self.root.protocol("WM_DELETE_WINDOW", self._close)
        self._last_tick = datetime.now()
        config_parent = runtime.config_path.parent
        self.config_root = config_parent.parent if config_parent.name == "sites" else config_parent
        self.site_repository = SiteRepository(self.config_root)
        self.config_data = self.site_repository.load(runtime.config_path)
        self.generator_rows: list[dict[str, tk.Widget]] = []
        self.load_controls: dict[str, dict[str, object]] = {}
        self.auto_breaker = tk.BooleanVar(value=runtime.manager.config.automatic_breaker_control)
        self._style()
        self._build()
        self._tick()

    def _style(self) -> None:
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame", background="#111827")
        style.configure("TLabel", background="#111827", foreground="#e5e7eb", font=("Segoe UI", 9))
        style.configure("Title.TLabel", font=("Segoe UI", 15, "bold"), foreground="#f59e0b")
        style.configure("Value.TLabel", font=("Consolas", 10, "bold"), foreground="#60a5fa")
        style.configure("TNotebook", background="#111827")
        style.configure("TNotebook.Tab", padding=(12, 6))

    def _build(self) -> None:
        header = ttk.Frame(self.root, padding=10)
        header.pack(fill="x")
        ttk.Label(header, text="⚠ SIMULATED PLANT — NOT FOR EQUIPMENT CONTROL", style="Title.TLabel").pack(side="left")
        self.speed = tk.StringVar(value="1")
        ttk.Label(header, text="Speed").pack(side="right")
        ttk.Combobox(header, textvariable=self.speed, values=("0", "1", "2", "5", "10"), width=5, state="readonly").pack(side="right", padx=6)
        ttk.Button(header, text="Save state", command=self.runtime.save).pack(side="right", padx=10)

        notebook = ttk.Notebook(self.root)
        notebook.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.overview = ttk.Frame(notebook, padding=12)
        self.diagnostics = ttk.Frame(notebook, padding=12)
        self.scenario_tab = ttk.Frame(notebook, padding=12)
        self.logs_tab = ttk.Frame(notebook, padding=12)
        self.config_tab = ttk.Frame(notebook, padding=12)
        notebook.add(self.overview, text="Plant overview")
        notebook.add(self.diagnostics, text="SCADA diagnostics")
        notebook.add(self.scenario_tab, text="Scenarios and faults")
        notebook.add(self.logs_tab, text="Event log")
        notebook.add(self.config_tab, text="Plant configuration")
        self._build_overview()
        self._build_diagnostics()
        self._build_scenarios()
        self._build_logs()
        self._build_configuration()

    def _build_configuration(self) -> None:
        site_bar = ttk.Frame(self.config_tab)
        site_bar.pack(fill="x", pady=(0, 12))
        self.site_choice = tk.StringVar(value=str(self.runtime.config_path))
        self.site_paths = {f"{self.site_repository.site_name(path)} — {path.name}": path for path in self.site_repository.list_sites()}
        current_label = next((label for label, path in self.site_paths.items() if path == self.runtime.config_path), str(self.runtime.config_path))
        self.site_choice.set(current_label)
        ttk.Label(site_bar, text="Sites").pack(side="left")
        self.site_combo = ttk.Combobox(site_bar, textvariable=self.site_choice, values=tuple(self.site_paths), width=42, state="readonly")
        self.site_combo.pack(side="left", padx=6)
        ttk.Button(site_bar, text="Open site now", command=self._select_site).pack(side="left")
        ttk.Button(site_bar, text="New site", command=self._new_site).pack(side="left", padx=5)
        ttk.Button(site_bar, text="Clone site", command=self._clone_site).pack(side="left")
        ttk.Button(site_bar, text="Delete site", command=self._delete_site).pack(side="left", padx=5)

        general = ttk.LabelFrame(self.config_tab, text="Site and sources", padding=8)
        general.pack(fill="x")
        self.cfg_site_name = tk.StringVar(value=self.config_data.get("name", ""))
        self.cfg_voltage = tk.StringVar(value=str(self.config_data.get("voltage_v", 400)))
        self.cfg_frequency = tk.StringVar(value=str(self.config_data.get("frequency_hz", 50)))
        self.cfg_grid_enabled = tk.BooleanVar(value=self.config_data.get("grid", {}).get("enabled", True))
        self.cfg_solar_enabled = tk.BooleanVar(value=self.config_data.get("solar", {}).get("enabled", False))
        self.cfg_solar_kw = tk.StringVar(value=str(self.config_data.get("solar", {}).get("rated_kw", 500)))
        fields = (("Site name", self.cfg_site_name, 26), ("Voltage V", self.cfg_voltage, 8), ("Frequency Hz", self.cfg_frequency, 8), ("Solar kW", self.cfg_solar_kw, 8))
        for label, variable, width in fields:
            ttk.Label(general, text=label).pack(side="left", padx=(8, 3))
            ttk.Entry(general, textvariable=variable, width=width).pack(side="left")
        ttk.Checkbutton(general, text="Grid enabled", variable=self.cfg_grid_enabled).pack(side="left", padx=8)
        ttk.Checkbutton(general, text="Solar enabled", variable=self.cfg_solar_enabled).pack(side="left")

        mains = ttk.LabelFrame(self.config_tab, text="Grid / mains DSE panel", padding=8)
        mains.pack(fill="x", pady=(10, 0))
        mains_data = self.config_data.get("mains_controller", {})
        mains_mb = mains_data.get("modbus", {})
        self.mains_options = self.site_repository.controller_profile_options("mains")
        def option_label(options: dict[str, str], reference: str) -> str:
            return next((label for label, value in options.items() if value == reference), next(iter(options), ""))
        self.cfg_mains_enabled = tk.BooleanVar(value=bool(mains_data))
        self.cfg_mains_profile = tk.StringVar(value=option_label(self.mains_options, mains_data.get("controller_profile", "")))
        self.cfg_mains_host = tk.StringVar(value=mains_mb.get("host", "0.0.0.0"))
        self.cfg_mains_port = tk.StringVar(value=str(mains_mb.get("port", 5021)))
        self.cfg_mains_unit = tk.StringVar(value=str(mains_mb.get("unit_id", 20)))
        ttk.Checkbutton(mains, text="Enabled", variable=self.cfg_mains_enabled).pack(side="left")
        ttk.Label(mains, text="Panel").pack(side="left", padx=(10, 3))
        ttk.Combobox(mains, textvariable=self.cfg_mains_profile, values=tuple(self.mains_options), width=35, state="readonly").pack(side="left")
        for label, variable, width in (("Host", self.cfg_mains_host, 12), ("Port", self.cfg_mains_port, 7), ("Unit", self.cfg_mains_unit, 5)):
            ttk.Label(mains, text=label).pack(side="left", padx=(8, 3))
            ttk.Entry(mains, textvariable=variable, width=width).pack(side="left")

        generators = ttk.LabelFrame(self.config_tab, text="Generators and DSE endpoints", padding=8)
        generators.pack(fill="both", expand=True, pady=12)
        columns = ("name", "kw", "equipment", "controller", "host", "port", "unit")
        self.config_tree = ttk.Treeview(generators, columns=columns, show="headings", height=12)
        headings = {"name": "Name", "kw": "Size kW", "equipment": "Generator profile", "controller": "Panel model", "host": "TCP host", "port": "TCP port", "unit": "Unit ID"}
        widths = {"name": 100, "kw": 70, "equipment": 180, "controller": 180, "host": 105, "port": 70, "unit": 60}
        for column in columns:
            self.config_tree.heading(column, text=headings[column]); self.config_tree.column(column, width=widths[column], anchor="w")
        self.config_tree.pack(fill="both", expand=True)
        controls = ttk.Frame(generators)
        controls.pack(fill="x", pady=(8, 0))
        ttk.Button(controls, text="Add generator", command=self._add_generator_dialog).pack(side="left")
        ttk.Button(controls, text="Edit selected", command=self._edit_generator_dialog).pack(side="left", padx=5)
        ttk.Button(controls, text="Delete selected", command=self._delete_generator).pack(side="left")
        ttk.Button(controls, text="Save and apply to all tabs", command=self._save_configuration).pack(side="right")
        ttk.Label(controls, text="Apply rebuilds the plant, tabs, scenarios and Modbus endpoints.").pack(side="right", padx=12)
        self._refresh_generator_tree()

    def _build_overview(self) -> None:
        source = ttk.Frame(self.overview)
        source.pack(fill="x")
        self.grid_label = ttk.Label(source, style="Value.TLabel")
        self.grid_label.pack(side="left")
        if self.runtime.plant.grid:
            ttk.Button(source, text="Open grid CB", command=self.runtime.plant.grid.breaker.request_open).pack(side="left", padx=8)
            ttk.Button(source, text="Sync/close grid CB", command=self.runtime.plant.synchronize_grid).pack(side="left")
        self.solar_label = ttk.Label(source, style="Value.TLabel")
        self.solar_label.pack(side="right")
        if self.runtime.plant.solar:
            ttk.Button(source, text="Close PV CB", command=self.runtime.plant.solar.breaker.request_close).pack(side="right", padx=8)
            ttk.Button(source, text="Open PV CB", command=self.runtime.plant.solar.breaker.request_open).pack(side="right")
        ttk.Checkbutton(
            self.overview, text="Automatically synchronize/close ready generator breakers",
            variable=self.auto_breaker, command=self._set_automatic_breaker_control,
        ).pack(anchor="w", pady=(8, 0))
        bus = tk.Frame(self.overview, bg="#2563eb", height=8)
        bus.pack(fill="x", pady=14)
        self.bus_label = ttk.Label(self.overview, style="Value.TLabel")
        self.bus_label.pack()
        table = ttk.Frame(self.overview)
        table.pack(fill="both", expand=True, pady=12)
        headers = ("Generator", "State", "Breaker", "V", "Hz", "kW", "kVAr", "A", "PF", "Alarms", "Load setpoint", "Controls")
        for col, heading in enumerate(headers):
            ttk.Label(table, text=heading).grid(row=0, column=col, padx=5, pady=5, sticky="w")
        for row, generator in enumerate(self.runtime.plant.generators, 1):
            widgets = {}
            for col, key in enumerate(headers[:10]):
                label = ttk.Label(table, style="Value.TLabel")
                label.grid(row=row, column=col, padx=5, pady=6, sticky="w")
                widgets[key] = label
            load_frame = ttk.Frame(table)
            load_frame.grid(row=row, column=10, sticky="w")
            setpoint = generator.fixed_kw_setpoint if generator.fixed_kw_setpoint is not None else generator.target_kw
            load_variable = tk.DoubleVar(value=max(0.0, min(generator.rated_kw, setpoint)))
            load_scale = tk.Scale(
                load_frame, from_=0, to=generator.rated_kw, resolution=max(1, generator.rated_kw / 100),
                orient="horizontal", length=145, showvalue=False, variable=load_variable,
                bg="#111827", fg="#e5e7eb", troughcolor="#374151", highlightthickness=0,
                command=lambda value, g=generator: self._set_generator_load(g, value),
            )
            load_scale.pack(side="left")
            load_scale.bind("<ButtonRelease-1>", lambda _event, g=generator: self._log_generator_load(g))
            load_label = ttk.Label(load_frame, width=15, style="Value.TLabel")
            load_label.pack(side="left", padx=3)
            ttk.Button(load_frame, text="Auto", command=lambda g=generator: self._set_auto_load(g)).pack(side="left")
            self.load_controls[generator.name] = {"variable": load_variable, "label": load_label}
            controls = ttk.Frame(table)
            controls.grid(row=row, column=11, sticky="w")
            ttk.Button(controls, text="Start", command=generator.start).pack(side="left")
            ttk.Button(controls, text="Stop", command=generator.stop).pack(side="left")
            ttk.Button(controls, text="Close CB", command=lambda g=generator: self._request_close_breaker(g)).pack(side="left")
            ttk.Button(controls, text="Open CB", command=generator.breaker.request_open).pack(side="left")
            ttk.Button(controls, text="Reset", command=generator.reset_alarms).pack(side="left")
            ttk.Button(controls, text="Parameters ▼", command=lambda g=generator: self._show_parameter_editor(g)).pack(side="left")
            widgets["Generator"].config(text=generator.name)
            widgets["Generator"].bind("<Button-1>", lambda _event, g=generator: self._show_generator_details(g))
            self.generator_rows.append(widgets)

    def _set_generator_load(self, generator, value: str) -> None:
        generator.load_mode = "fixed_kw"
        generator.fixed_kw_setpoint = max(0.0, min(generator.rated_kw, float(value)))

    def _log_generator_load(self, generator) -> None:
        self._event("load_setpoint", f"{generator.name}: manual {generator.fixed_kw_setpoint:.1f} kW")

    def _set_auto_load(self, generator) -> None:
        generator.load_mode = "proportional"
        generator.fixed_kw_setpoint = None
        self._event("load_setpoint", f"{generator.name}: automatic proportional sharing")

    def _set_automatic_breaker_control(self) -> None:
        enabled = self.auto_breaker.get()
        self.runtime.manager.config.automatic_breaker_control = enabled
        self._event("breaker_control", "automatic" if enabled else "manual")

    def _request_close_breaker(self, generator) -> None:
        if generator.breaker.closed:
            self._event("breaker_command", f"{generator.name}: breaker is already closed")
            return
        if generator.state is GeneratorState.SYNCHRONIZING:
            self._event("breaker_command", f"{generator.name}: synchronization already in progress")
            return
        if self.runtime.plant.close_generator_breaker(generator):
            status = "dead-bus closing" if not self.runtime.plant.bus_energized else "synchronization started"
            self._event("breaker_command", f"{generator.name}: {status}")
            return
        messagebox.showwarning(
            "Close generator breaker",
            f"{generator.name} breaker cannot close while state is {generator.state.value}.\n\n"
            "Start the engine and wait for RUNNING_OFF_LOAD. If the bus is energized, the simulator will then synchronize voltage, frequency and phase before closing.",
        )

    def _calculated_parameter_value(self, generator, key: str) -> float:
        values = {
            "fuel_level_pct": generator.fuel_level_pct,
            "coolant_temperature_c": generator.coolant_temp_c,
            "oil_pressure_bar": generator.oil_pressure_kpa / 100.0,
            "battery_voltage_v": generator.battery_voltage_v,
            "engine_speed_rpm": generator.rpm,
            "frequency_hz": generator.frequency_hz,
            "active_power_kw": generator.active_kw,
            "apparent_power_kva": generator.apparent_kva,
            "reactive_power_kvar": generator.reactive_kvar,
            "reactive_load_pct": 100 * generator.reactive_kvar / max(generator.rated_kw, 1),
            "voltage_l1_n_v": generator.voltage_v / 3**.5,
            "voltage_l2_n_v": generator.voltage_v / 3**.5,
            "voltage_l3_n_v": generator.voltage_v / 3**.5,
            "voltage_l1_l2_v": generator.voltage_v,
            "voltage_l2_l3_v": generator.voltage_v,
            "voltage_l3_l1_v": generator.voltage_v,
            "current_l1_a": generator.current_a,
            "current_l2_a": generator.current_a,
            "current_l3_a": generator.current_a,
            "power_l1_kw": generator.active_kw / 3,
            "power_l2_kw": generator.active_kw / 3,
            "power_l3_kw": generator.active_kw / 3,
            "power_factor": generator.power_factor,
            "energy_produced_kwh": generator.energy_kwh,
            "start_count": generator.starts,
            "oil_temperature_c": generator.oil_temp_c,
            "charge_alternator_voltage_v": generator.battery_voltage_v if generator.running else 0,
            "fuel_used_l": generator.fuel_used_l,
            "generator_state": list(GeneratorState).index(generator.state),
            "manufacturer_code": 1,
            "model_number": 0,
            "control_mode": 1,
            "controller_status": 0,
        }
        return float(values[key])

    def _show_parameter_editor(self, generator) -> None:
        window = tk.Toplevel(self.root)
        window.title(f"SIMULATED PARAMETER OVERRIDES — {generator.name}")
        window.geometry("680x480")
        window.transient(self.root)
        ttk.Label(
            window,
            text="Direct SCADA mock overrides. Phase-specific overrides may intentionally create unbalanced or inconsistent readings.",
            wraplength=640,
        ).pack(fill="x", padx=12, pady=10)
        editor = ttk.Frame(window, padding=10)
        editor.pack(fill="x")
        parameter = tk.StringVar(value=next(iter(MOCK_PARAMETERS)))
        value = tk.StringVar()
        units = tk.StringVar()
        ttk.Label(editor, text="Parameter").grid(row=0, column=0, sticky="w")
        parameter_combo = ttk.Combobox(editor, textvariable=parameter, values=tuple(MOCK_PARAMETERS), width=32, state="readonly")
        parameter_combo.grid(row=1, column=0, padx=(0, 8), sticky="ew")
        ttk.Label(editor, text="Mock value").grid(row=0, column=1, sticky="w")
        ttk.Entry(editor, textvariable=value, width=18).grid(row=1, column=1, padx=(0, 5))
        ttk.Label(editor, textvariable=units, width=8).grid(row=1, column=2, sticky="w")
        tree = ttk.Treeview(window, columns=("parameter", "value", "unit"), show="headings", height=13)
        for column, title, width in (("parameter", "Overridden parameter", 280), ("value", "Value", 130), ("unit", "Unit", 80)):
            tree.heading(column, text=title); tree.column(column, width=width, anchor="w")
        tree.pack(fill="both", expand=True, padx=12, pady=8)

        def refresh() -> None:
            for item in tree.get_children(): tree.delete(item)
            labels = {key: (label, unit) for label, (key, unit) in MOCK_PARAMETERS.items()}
            for key, override in sorted(generator.telemetry_overrides.items()):
                label, unit = labels.get(key, (key, ""))
                tree.insert("", "end", values=(label, override, unit))

        def select_parameter(_event=None) -> None:
            key, unit = MOCK_PARAMETERS[parameter.get()]
            units.set(unit)
            value.set(str(generator.telemetry_overrides.get(key, self._calculated_parameter_value(generator, key))))

        def apply_override() -> None:
            key, _unit = MOCK_PARAMETERS[parameter.get()]
            try:
                number = float(value.get())
                if key == "fuel_level_pct" and not 0 <= number <= 100: raise ValueError("fuel level must be 0..100%")
                if key == "power_factor" and not -1 <= number <= 1: raise ValueError("power factor must be -1..1")
                if key in {"start_count", "generator_state", "manufacturer_code", "model_number", "control_mode", "controller_status"}:
                    number = int(number)
                generator.telemetry_overrides[key] = number
            except ValueError as exc:
                messagebox.showerror("Parameter override", str(exc), parent=window); return
            self._event("telemetry_override", f"{generator.name}: {key}={number}")
            refresh()

        def clear_selected() -> None:
            key, _unit = MOCK_PARAMETERS[parameter.get()]
            generator.telemetry_overrides.pop(key, None)
            select_parameter(); refresh()
            self._event("telemetry_override", f"{generator.name}: cleared {key}")

        def clear_all() -> None:
            generator.telemetry_overrides.clear(); select_parameter(); refresh()
            self._event("telemetry_override", f"{generator.name}: cleared all")

        parameter_combo.bind("<<ComboboxSelected>>", select_parameter)
        ttk.Button(editor, text="Apply override", command=apply_override).grid(row=1, column=3, padx=4)
        ttk.Button(editor, text="Clear selected", command=clear_selected).grid(row=1, column=4, padx=4)
        ttk.Button(editor, text="Clear all", command=clear_all).grid(row=1, column=5, padx=4)
        select_parameter(); refresh()

    def _build_diagnostics(self) -> None:
        self.diag_text = tk.Text(self.diagnostics, bg="#0b1220", fg="#d1d5db", font=("Consolas", 10), height=14)
        self.diag_text.pack(fill="x")
        inspector = ttk.Frame(self.diagnostics, padding=(0, 12))
        inspector.pack(fill="x")
        self.device_options = {
            f"{mb.get('host', '0.0.0.0')}:{mb.get('port', 5021)} / unit {mb.get('unit_id', 10)} / {controller.model}": controller
            for mb, controller in self.runtime.controller_devices
        }
        self.unit_var = tk.StringVar(value=next(iter(self.device_options), "No controller configured"))
        self.page_var, self.offset_var, self.address_var = tk.StringVar(value="4"), tk.StringVar(value="0"), tk.StringVar(value="")
        ttk.Label(inspector, text="Controller").pack(side="left", padx=(8, 3))
        ttk.Combobox(inspector, textvariable=self.unit_var, values=tuple(self.device_options), width=42, state="readonly").pack(side="left")
        for label, variable in (("Page", self.page_var), ("Offset", self.offset_var), ("Absolute address", self.address_var)):
            ttk.Label(inspector, text=label).pack(side="left", padx=(8, 3))
            ttk.Entry(inspector, textvariable=variable, width=8).pack(side="left")
        ttk.Button(inspector, text="Inspect", command=self._inspect_register).pack(side="left", padx=10)
        self.inspect_text = tk.Text(self.diagnostics, bg="#0b1220", fg="#93c5fd", font=("Consolas", 10), height=10)
        self.inspect_text.pack(fill="both", expand=True)

    def _build_scenarios(self) -> None:
        top = ttk.Frame(self.scenario_tab)
        top.pack(fill="x")
        self.scenario_name = tk.StringVar(value=next(iter(self.runtime.scenarios)))
        ttk.Combobox(top, textvariable=self.scenario_name, values=tuple(self.runtime.scenarios), width=40, state="readonly").pack(side="left")
        ttk.Button(top, text="Run", command=lambda: self.runtime.start_scenario(self.scenario_name.get())).pack(side="left")
        ttk.Button(top, text="Pause", command=self._pause_scenario).pack(side="left")
        ttk.Button(top, text="Reset", command=self._reset_scenario).pack(side="left")
        self.scenario_status = ttk.Label(top, style="Value.TLabel")
        self.scenario_status.pack(side="left", padx=20)
        fault = ttk.Frame(self.scenario_tab, padding=(0, 20))
        fault.pack(fill="x")
        self.fault_gen = tk.StringVar(value=self.runtime.plant.generators[0].name if self.runtime.plant.generators else "")
        self.fault_name = tk.StringVar(value=next(iter(GENERATOR_FAULTS)))
        ttk.Combobox(fault, textvariable=self.fault_gen, values=tuple(g.name for g in self.runtime.plant.generators), state="readonly").pack(side="left")
        ttk.Combobox(fault, textvariable=self.fault_name, values=tuple(GENERATOR_FAULTS) + ("fail_to_start", "fail_to_stop", "breaker_fails_to_open", "breaker_fails_to_close"), width=30, state="readonly").pack(side="left")
        ttk.Button(fault, text="Inject generator fault", command=self._inject_generator_fault).pack(side="left")
        if self.runtime.plant.grid:
            ttk.Button(fault, text="Grid failure", command=lambda: inject_grid_fault(self.runtime.plant.grid, "mains_failure", True)).pack(side="left", padx=8)
            ttk.Button(fault, text="Grid restore", command=self._restore_grid).pack(side="left")
        if self.runtime.plant.solar:
            ttk.Button(fault, text="PV trip", command=lambda: inject_solar_fault(self.runtime.plant.solar, "inverter_trip")).pack(side="left", padx=8)
            ttk.Button(fault, text="PV reset", command=lambda: inject_solar_fault(self.runtime.plant.solar, None)).pack(side="left")
        communications = ttk.Frame(self.scenario_tab, padding=(0, 8))
        communications.pack(fill="x")
        ttk.Label(communications, text="Communication faults use the controller selected in SCADA diagnostics:").pack(side="left")
        ttk.Button(communications, text="Offline", command=lambda: self._set_comm_fault("offline")).pack(side="left")
        ttk.Button(communications, text="500 ms delay", command=lambda: self._set_comm_fault("delay")).pack(side="left")
        ttk.Button(communications, text="Intermittent", command=lambda: self._set_comm_fault("intermittent")).pack(side="left")
        ttk.Button(communications, text="Restore", command=lambda: self._set_comm_fault("restore")).pack(side="left")

    def _build_logs(self) -> None:
        self.event_text = tk.Text(self.logs_tab, bg="#0b1220", fg="#d1d5db", font=("Consolas", 9))
        self.event_text.pack(fill="both", expand=True)
        file_event_sink = self.runtime.plant.event_sink
        def combined_event_sink(event: str, detail: str) -> None:
            if file_event_sink:
                file_event_sink(event, detail)
            self._event(event, detail)
        self.runtime.plant.event_sink = combined_event_sink

    def _event(self, event: str, detail: str) -> None:
        line = f"{datetime.now().isoformat(timespec='seconds')} {event}: {detail}\n"
        self.event_text.insert("end", line)
        self.event_text.see("end")

    def _inspect_register(self) -> None:
        try:
            controller = self.device_options[self.unit_var.get()]
            address = int(self.address_var.get()) if self.address_var.get().strip() else int(self.page_var.get()) * 256 + int(self.offset_var.get())
            info = controller.registers.inspect(address)
            page, offset = divmod(address, 256)
            self.page_var.set(str(page)); self.offset_var.set(str(offset)); self.address_var.set(str(address))
            raw = controller.read(info["address"] - info["word_index"], controller.registers._by_word[address][0].word_count) if info else [0xFFFF]
            lines = [f"{key}: {value}" for key, value in (info or {"address": address, "page": page, "offset": offset, "status": "reserved/unimplemented"}).items()]
            lines.append(f"raw words: {' '.join(f'0x{x:04X}' for x in raw)}")
            self.inspect_text.delete("1.0", "end"); self.inspect_text.insert("end", "\n".join(lines))
        except Exception as exc:
            messagebox.showerror("Register inspector", str(exc))

    def _inject_generator_fault(self) -> None:
        generator = next((g for g in self.runtime.plant.generators if g.name == self.fault_gen.get()), None)
        if generator is None:
            messagebox.showwarning("Generator fault", "This site has no generator configured.")
            return
        inject_generator_fault(generator, self.fault_name.get())
        self._event("fault", f"{generator.name}: {self.fault_name.get()}")

    def _show_generator_details(self, generator) -> None:
        window = tk.Toplevel(self.root)
        window.title(f"SIMULATOR — {generator.name} details")
        window.geometry("680x560")
        text = tk.Text(window, bg="#0b1220", fg="#d1d5db", font=("Consolas", 10))
        text.pack(fill="both", expand=True)
        controller_item = next((item for item in self.runtime.raw_config["generators"] if item["name"] == generator.name), {})
        mb = controller_item.get("modbus", {})
        controller = next((candidate for binding, candidate in self.runtime.controller_devices if binding is mb), None)
        values = {
            "Equipment profile": controller_item.get("equipment_profile"),
            "Controller profile": controller_item.get("controller_profile"),
            "Controller": controller.model if controller else "unknown",
            "Modbus": controller_item.get("modbus"),
            "State": generator.state.value, "Breaker": generator.breaker.state.value,
            "Voltage V": generator.voltage_v, "Frequency Hz": generator.frequency_hz,
            "Active kW": generator.active_kw, "Reactive kVAr": generator.reactive_kvar,
            "Current A": generator.current_a, "Power factor": generator.power_factor,
            "RPM": generator.rpm, "Oil pressure kPa": generator.oil_pressure_kpa,
            "Coolant degC": generator.coolant_temp_c, "Battery V": generator.battery_voltage_v,
            "Sync frequency difference Hz": generator.frequency_hz - self.runtime.plant.bus_frequency_hz,
            "Sync voltage difference V": generator.voltage_v - self.runtime.plant.bus_voltage_v,
            "Sync phase difference deg": ((generator.phase_angle_deg - self.runtime.plant.bus_phase_angle_deg + 180) % 360) - 180,
            "Inputs": {"remote_start": generator.commanded_start, "remote_stop": generator.commanded_stop},
            "Outputs": {"fuel": generator.running, "starter": generator.state.value == "CRANKING", "breaker": generator.breaker.closed},
            "Active alarms": [f"{alarm.severity.value}: {alarm.message}" for alarm in generator.alarms.values() if alarm.active],
        }
        text.insert("end", "\n".join(f"{key}: {value}" for key, value in values.items()))
        text.config(state="disabled")

    def _refresh_generator_tree(self) -> None:
        for item_id in self.config_tree.get_children(): self.config_tree.delete(item_id)
        for index, item in enumerate(self.config_data.get("generators", [])):
            try:
                profile = load_generator_profile_reference(self.config_root, item["equipment_profile"])
                controller = load_controller_profile_reference(self.config_root, item["controller_profile"])
                kw = item.get("rated_kw_override", profile.prime_power_kw.value)
                equipment_name = f"{profile.manufacturer.value or 'Unknown'} / {profile.model.value or profile.profile_id}"
                controller_name = controller.model
            except Exception:
                kw = item.get("rated_kw_override", "?")
                equipment_name = item.get("equipment_profile", "?")
                controller_name = item.get("controller_profile", "?")
            mb = item.get("modbus", {})
            self.config_tree.insert("", "end", iid=str(index), values=(item.get("name"), kw, equipment_name, controller_name, mb.get("host"), mb.get("port"), mb.get("unit_id")))

    def _apply_general_configuration(self) -> None:
        self.config_data["name"] = self.cfg_site_name.get().strip()
        self.config_data["voltage_v"] = float(self.cfg_voltage.get())
        self.config_data["frequency_hz"] = float(self.cfg_frequency.get())
        grid = self.config_data.setdefault("grid", {})
        grid.update(enabled=self.cfg_grid_enabled.get(), voltage_v=float(self.cfg_voltage.get()), frequency_hz=float(self.cfg_frequency.get()))
        solar = self.config_data.setdefault("solar", {})
        solar.update(enabled=self.cfg_solar_enabled.get(), rated_kw=float(self.cfg_solar_kw.get()))
        power_management = self.config_data.setdefault("power_management", {})
        power_management["automatic_breaker_control"] = self.auto_breaker.get()
        if self.cfg_mains_enabled.get():
            self.config_data["mains_controller"] = {
                "controller_profile": self.mains_options[self.cfg_mains_profile.get()],
                "modbus": {"host": self.cfg_mains_host.get().strip() or "0.0.0.0", "port": int(self.cfg_mains_port.get()), "unit_id": int(self.cfg_mains_unit.get())},
            }
        else:
            self.config_data.pop("mains_controller", None)

    def _save_configuration(self) -> None:
        try:
            self._apply_general_configuration()
            self.site_repository.save(self.runtime.config_path, self.config_data)
        except (ConfigurationError, ValueError, KeyError, OSError) as exc:
            messagebox.showerror("Plant configuration", str(exc)); return
        self._restart(self.runtime.config_path)

    def _selected_generator_index(self) -> int | None:
        selected = self.config_tree.selection()
        return int(selected[0]) if selected else None

    def _add_generator_dialog(self) -> None:
        self._generator_dialog(None)

    def _edit_generator_dialog(self) -> None:
        index = self._selected_generator_index()
        if index is None:
            messagebox.showwarning("Generator", "Select a generator first."); return
        self._generator_dialog(index)

    def _generator_dialog(self, index: int | None) -> None:
        existing = self.config_data.get("generators", [])[index] if index is not None else {}
        window = tk.Toplevel(self.root); window.title("Edit generator" if index is not None else "Add generator"); window.transient(self.root); window.grab_set()
        equipment = self.site_repository.generator_profile_options()
        controllers = self.site_repository.controller_profile_options("generator")
        def selected_label(options: dict[str, str], reference: str) -> str:
            return next((label for label, value in options.items() if value == reference), next(iter(options), ""))
        values = {
            "name": tk.StringVar(value=existing.get("name", f"GEN{len(self.config_data.get('generators', [])) + 1}")),
            "equipment": tk.StringVar(value=selected_label(equipment, existing.get("equipment_profile", ""))),
            "controller": tk.StringVar(value=selected_label(controllers, existing.get("controller_profile", ""))),
            "size": tk.StringVar(value=str(existing.get("rated_kw_override", ""))),
            "host": tk.StringVar(value=existing.get("modbus", {}).get("host", "0.0.0.0")),
            "port": tk.StringVar(value=str(existing.get("modbus", {}).get("port", 5021))),
            "unit": tk.StringVar(value=str(existing.get("modbus", {}).get("unit_id", 10 + len(self.config_data.get("generators", []))))),
        }
        rows = (("Name", "name", None), ("Generator type/profile", "equipment", tuple(equipment)), ("Panel/controller model", "controller", tuple(controllers)), ("Size override kW (blank uses profile)", "size", None), ("TCP bind host/IP", "host", None), ("TCP port", "port", None), ("Modbus unit ID", "unit", None))
        for row, (label, key, choices) in enumerate(rows):
            ttk.Label(window, text=label).grid(row=row, column=0, padx=10, pady=7, sticky="w")
            widget = ttk.Combobox(window, textvariable=values[key], values=choices, state="readonly", width=32) if choices else ttk.Entry(window, textvariable=values[key], width=35)
            widget.grid(row=row, column=1, padx=10, pady=7)
        def commit() -> None:
            try:
                equipment_value = equipment[values["equipment"].get()]
                controller_value = controllers[values["controller"].get()]
                size = float(values["size"].get()) if values["size"].get().strip() else None
                if index is None:
                    self.site_repository.add_generator(self.config_data, values["name"].get(), equipment_value, controller_value, values["host"].get(), int(values["port"].get()), int(values["unit"].get()), size)
                else:
                    item = self.config_data["generators"][index]
                    item.update(name=values["name"].get().strip(), equipment_profile=equipment_value, controller_profile=controller_value, modbus={"host": values["host"].get().strip(), "port": int(values["port"].get()), "unit_id": int(values["unit"].get())})
                    if size is None: item.pop("rated_kw_override", None)
                    else: item["rated_kw_override"] = size
                self._apply_general_configuration(); self.site_repository.validate(self.config_data, self.config_root)
            except (ConfigurationError, ValueError, KeyError) as exc:
                messagebox.showerror("Generator", str(exc), parent=window); return
            self._refresh_generator_tree(); window.destroy()
        ttk.Button(window, text="Apply", command=commit).grid(row=len(rows), column=0, columnspan=2, pady=12)

    def _delete_generator(self) -> None:
        index = self._selected_generator_index()
        if index is None:
            messagebox.showwarning("Generator", "Select a generator first."); return
        name = self.config_data["generators"][index]["name"]
        if messagebox.askyesno("Delete generator", f"Remove {name} from this site's saved configuration?"):
            self.config_data["generators"].pop(index); self._refresh_generator_tree()

    def _refresh_site_list(self, select: Path | None = None) -> None:
        self.site_paths = {f"{self.site_repository.site_name(path)} — {path.name}": path for path in self.site_repository.list_sites()}
        self.site_combo.config(values=tuple(self.site_paths))
        if select:
            label = next((key for key, path in self.site_paths.items() if path == select.resolve()), None)
            if label: self.site_choice.set(label)

    def _new_site(self) -> None:
        name = simpledialog.askstring("New site", "Site name:", parent=self.root)
        if not name: return
        try: path = self.site_repository.create_site(name, float(self.cfg_voltage.get()), float(self.cfg_frequency.get()))
        except (ConfigurationError, ValueError, OSError) as exc: messagebox.showerror("New site", str(exc)); return
        self._refresh_site_list(path)

    def _clone_site(self) -> None:
        name = simpledialog.askstring("Clone site", "Name for the cloned site:", parent=self.root)
        if not name: return
        try: path = self.site_repository.clone_site(self.runtime.config_path, name)
        except (ConfigurationError, ValueError, OSError) as exc: messagebox.showerror("Clone site", str(exc)); return
        self._refresh_site_list(path)

    def _delete_site(self) -> None:
        path = self.site_paths.get(self.site_choice.get())
        if not path: return
        if path.resolve() == self.runtime.config_path:
            messagebox.showwarning("Delete site", "Open a different site before deleting the site that is currently running.")
            return
        if not messagebox.askyesno("Delete site", f"Move saved site {self.site_repository.site_name(path)} and its isolated data to the recoverable trash folder?"): return
        try: self.site_repository.delete_site(path)
        except (ConfigurationError, OSError) as exc: messagebox.showerror("Delete site", str(exc)); return
        self._refresh_site_list()

    def _select_site(self) -> None:
        path = self.site_paths.get(self.site_choice.get())
        if not path: return
        self._restart(path)

    def _restart(self, path: Path) -> None:
        path = path.resolve()
        (self.config_root / "active_site.txt").write_text(str(path), encoding="utf-8")
        self.runtime.save()
        self.restart_with = path
        self.root.destroy()

    def _restore_grid(self) -> None:
        grid = self.runtime.plant.grid
        if grid:
            inject_grid_fault(grid, "mains_failure", False)
            grid.available, grid.voltage_v, grid.frequency_hz = True, grid.nominal_voltage_v, grid.nominal_frequency_hz

    def _set_comm_fault(self, mode: str) -> None:
        try:
            diagnostics = self.device_options[self.unit_var.get()].diagnostics
        except KeyError:
            messagebox.showerror("Communication fault", "Select a configured controller on SCADA diagnostics")
            return
        diagnostics.online = mode != "offline"
        diagnostics.response_delay_s = 0.5 if mode == "delay" else 0.0
        diagnostics.intermittent_failure_probability = 0.35 if mode == "intermittent" else 0.0
        self._event("communication_fault", f"{self.unit_var.get()}: {mode}")

    def _pause_scenario(self) -> None:
        if self.runtime.scenario_runner: self.runtime.scenario_runner.pause()

    def _reset_scenario(self) -> None:
        if self.runtime.scenario_runner: self.runtime.scenario_runner.reset()

    def _tick(self) -> None:
        now = datetime.now()
        dt = min(1.0, max(0.001, (now - self._last_tick).total_seconds()))
        self._last_tick = now
        speed = float(self.speed.get())
        self.runtime.plant.paused = speed == 0
        self.runtime.plant.simulation_speed = max(1, speed)
        self.runtime.update(dt)
        plant = self.runtime.plant
        grid = plant.grid
        self.grid_label.config(text=(f"GRID [{grid.breaker.state.value}]  {grid.voltage_v:.0f} V  {grid.frequency_hz:.2f} Hz  {grid.active_kw:+.0f} kW" if grid else "GRID disabled"))
        solar = plant.solar
        self.solar_label.config(text=(f"SOLAR [{solar.breaker.state.value}]  {solar.active_kw:.0f}/{solar.available_kw:.0f} kW" if solar else "SOLAR disabled"))
        self.bus_label.config(text=f"COMMON BUS  {plant.bus_voltage_v:.0f} V  {plant.bus_frequency_hz:.2f} Hz  Load {plant.bus_active_kw:.0f} kW / {plant.bus_reactive_kvar:.0f} kVAr")
        for generator, labels in zip(plant.generators, self.generator_rows):
            values = {"State": generator.state.value, "Breaker": generator.breaker.state.value, "V": f"{generator.voltage_v:.0f}", "Hz": f"{generator.frequency_hz:.2f}", "kW": f"{generator.active_kw:.0f}", "kVAr": f"{generator.reactive_kvar:.0f}", "A": f"{generator.current_a:.0f}", "PF": f"{generator.power_factor:.2f}", "Alarms": str(sum(a.active for a in generator.alarms.values()))}
            for key, value in values.items(): labels[key].config(text=value)
            load_label = self.load_controls[generator.name]["label"]
            mode = "MANUAL" if generator.load_mode in {"fixed_kw", "base_load"} else "AUTO"
            load_label.config(text=f"{mode} {generator.target_kw:.0f} kW")
        self._update_diagnostics()
        runner = self.runtime.scenario_runner
        self.scenario_status.config(text=f"Step: {runner.current_step}" if runner else "No scenario running")
        self.root.after(200, self._tick)

    def _update_diagnostics(self) -> None:
        lines = []
        for config, controller in self.runtime.controller_devices:
            unit = int(config.get("unit_id", controller.slave_address))
            d = controller.diagnostics
            lines.append(f"{config.get('host','0.0.0.0')}:{config.get('port',5021)} unit={unit:3} {controller.model:14} online={d.online!s:5} requests={d.request_count:6} last_fc={d.last_function} last_reg={d.last_register} exceptions={d.exception_count}")
        self.diag_text.delete("1.0", "end"); self.diag_text.insert("end", "\n".join(lines))

    def run(self) -> Path | None:
        self.root.mainloop()
        return self.restart_with

    def _close(self) -> None:
        self.runtime.save()
        self.root.destroy()
