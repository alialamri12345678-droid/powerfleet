"""Application composition root."""

from __future__ import annotations

import json
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from controllers import DSEControllerEmulator, DSEMainsControllerEmulator
from simulator_core.profiles import load_controller_profile_reference
from simulation.config import load_plant, restore_runtime_state, save_runtime_state
from simulation.ems import PowerManagementConfig, PowerManager
from simulation.scenarios import ScenarioRunner, standard_scenarios
from transports import ModbusRTUServer, ModbusTCPServer


class SimulatorRuntime:
    def __init__(self, config_path: str | Path, enable_modbus: bool = True):
        self.config_path = Path(config_path).resolve()
        config_root = self.config_path.parent.parent if self.config_path.parent.name == "sites" else self.config_path.parent
        self.site_id = self.config_path.stem.replace("plant.", "")
        self.site_data_dir = config_root / "site_data" / self.site_id
        self.site_data_dir.mkdir(parents=True, exist_ok=True)
        self.config_root = config_root
        self.raw_config = json.loads(self.config_path.read_text(encoding="utf-8"))
        self.plant = load_plant(self.config_path)
        self.state_path = self.site_data_dir / "runtime.json"
        restored = restore_runtime_state(self.plant, self.state_path)
        legacy_state = self.config_path.with_suffix(".runtime.json")
        if not restored and legacy_state.exists():
            restore_runtime_state(self.plant, legacy_state)
        ems_raw = self.raw_config.get("power_management", {})
        self.manager = PowerManager(self.plant, PowerManagementConfig(
            enabled=bool(ems_raw.get("enabled", True)),
            spinning_reserve_kw=float(ems_raw.get("spinning_reserve_kw", 0)),
            minimum_generator_loading_enabled=bool(ems_raw.get("minimum_generator_loading_enabled", True)),
            grid_import_target_kw=(None if ems_raw.get("grid_import_target_kw") is None else float(ems_raw["grid_import_target_kw"])),
            grid_export_limit_kw=float(ems_raw.get("grid_export_limit_kw", 0)),
            load_share_mode=str(ems_raw.get("load_share_mode", "proportional")),
            automatic_start_stop=bool(ems_raw.get("automatic_start_stop", True)),
            automatic_breaker_control=bool(ems_raw.get("automatic_breaker_control", False)),
        ))
        self.controllers: dict[int, DSEControllerEmulator] = {}
        self.controller_devices: list[tuple[dict, object]] = []
        self._endpoint_bindings: list[tuple[dict, object]] = []
        self.servers: list[ModbusTCPServer | ModbusRTUServer] = []
        self.scenarios = standard_scenarios(self.plant)
        self.scenario_runner: ScenarioRunner | None = None
        self._configure_logging()
        self.plant.event_sink = lambda event, detail: logging.getLogger("events").info("%s: %s", event, detail)
        self._build_controllers()
        self._last_states: dict[str, tuple[object, object, int]] = {
            g.name: (g.state, g.breaker.state, 0) for g in self.plant.generators
        }
        self._last_grid_state = self.plant.grid.breaker.state if self.plant.grid else None
        self._last_pv_limit = self.plant.solar.curtailment_limit_kw if self.plant.solar else None
        if enable_modbus:
            self._build_servers()

    def _configure_logging(self) -> None:
        log_dir = self.site_data_dir / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        root = logging.getLogger()
        root.setLevel(logging.INFO)
        for existing in tuple(root.handlers):
            if getattr(existing, "plant_simulator_handler", False):
                root.removeHandler(existing)
                existing.close()
        handler = RotatingFileHandler(log_dir / "simulator.log", maxBytes=2_000_000, backupCount=5, encoding="utf-8")
        handler.plant_simulator_handler = True
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        root.addHandler(handler)

    def _build_controllers(self) -> None:
        for index, (generator, item) in enumerate(zip(self.plant.generators, self.raw_config.get("generators", [])), 1):
            modbus = item.get("modbus", {})
            unit_id = int(modbus.get("unit_id", index))
            reference = item.get("controller_profile", "controllers/dse8610_mkii_demo.json")
            profile = load_controller_profile_reference(self.config_root, reference)
            controller = DSEControllerEmulator(profile.model, profile.family, profile.gencomm_version, generator, self.plant, 100000 + index, profile.supported_pages)
            controller.slave_address = unit_id
            self.controllers.setdefault(unit_id, controller)
            self.controller_devices.append((modbus, controller))
            self._endpoint_bindings.append((modbus, controller))
        mains = self.raw_config.get("mains_controller")
        if mains and self.plant.grid:
            profile = load_controller_profile_reference(self.config_root, mains.get("controller_profile", "controllers/dse8660_mkii_demo.json"))
            mb = mains.get("modbus", {})
            unit_id = int(mb.get("unit_id", 20))
            controller = DSEMainsControllerEmulator(profile.model, profile.family, profile.gencomm_version, self.plant, 200001, profile.supported_pages)
            controller.slave_address = unit_id
            self.controllers.setdefault(unit_id, controller)
            self.controller_devices.append((mb, controller))
            self._endpoint_bindings.append((mb, controller))

    def _build_servers(self) -> None:
        endpoints: dict[tuple[str, int], dict[int, DSEControllerEmulator]] = {}
        for mb, controller in self._endpoint_bindings:
            endpoint = (mb.get("host", "0.0.0.0"), int(mb.get("port", 5021)))
            endpoints.setdefault(endpoint, {})[int(mb.get("unit_id", 10))] = controller
        self.servers = [ModbusTCPServer(controllers, host, port) for (host, port), controllers in endpoints.items()]
        rtu = self.raw_config.get("modbus_rtu", {})
        if rtu.get("enabled") and rtu.get("serial_port"):
            self.servers.append(ModbusRTUServer(
                self.controllers, rtu["serial_port"], int(rtu.get("baudrate", 19200)),
                int(rtu.get("data_bits", 8)), str(rtu.get("parity", "N")), int(rtu.get("stop_bits", 1)),
            ))

    def start_servers(self) -> None:
        for server in self.servers:
            server.start()

    def save(self) -> None:
        save_runtime_state(self.plant, self.state_path)

    def start_scenario(self, name: str) -> None:
        self.scenario_runner = ScenarioRunner(self.plant, self.scenarios[name])
        self.scenario_runner.run()

    def update(self, real_dt: float) -> None:
        if self.scenario_runner:
            self.scenario_runner.update(real_dt * self.plant.simulation_speed)
        self.manager.update()
        self.plant.update(real_dt)
        event_log = logging.getLogger("events")
        for generator in self.plant.generators:
            old_state, old_breaker, old_alarm_count = self._last_states[generator.name]
            alarm_count = sum(alarm.active for alarm in generator.alarms.values())
            if generator.state != old_state:
                event_log.info("generator_state %s %s -> %s", generator.name, old_state, generator.state)
            if generator.breaker.state != old_breaker:
                event_log.info("breaker %s %s -> %s", generator.breaker.name, old_breaker, generator.breaker.state)
            if alarm_count != old_alarm_count:
                event_log.info("alarms %s active=%s", generator.name, alarm_count)
            self._last_states[generator.name] = (generator.state, generator.breaker.state, alarm_count)
        if self.plant.grid and self.plant.grid.breaker.state != self._last_grid_state:
            event_log.info("breaker %s %s -> %s", self.plant.grid.breaker.name, self._last_grid_state, self.plant.grid.breaker.state)
            self._last_grid_state = self.plant.grid.breaker.state
        if self.plant.solar and self.plant.solar.curtailment_limit_kw != self._last_pv_limit:
            event_log.info("pv_curtailment limit_kw=%s", self.plant.solar.curtailment_limit_kw)
            self._last_pv_limit = self.plant.solar.curtailment_limit_kw
