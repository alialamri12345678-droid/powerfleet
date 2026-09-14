"""Persistent JSON plant configuration loader and saver."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from simulator_core.profiles import load_generator_profile_reference
from .plant import Breaker, BreakerState, Generator, GridSource, Load, Plant, SolarSource, SyncLimits


def load_plant(path: str | Path) -> Plant:
    config_path = Path(path)
    raw = json.loads(config_path.read_text(encoding="utf-8"))
    base = config_path.parent
    config_root = base.parent if base.name == "sites" else base
    generators = []
    for item in raw.get("generators", []):
        reference = item["equipment_profile"]
        if Path(reference).is_absolute():
            profile = load_generator_profile_reference(Path(reference).parent, Path(reference).name)
        else:
            profile = load_generator_profile_reference(config_root, reference)
        def value(name: str, default: Any) -> Any:
            field = getattr(profile, name)
            return default if field.value is None else field.value
        def parameter(name: str, default: Any) -> Any:
            field = profile.parameters.get(name)
            return default if field is None or field.value is None else field.value
        generators.append(Generator(
            name=item["name"], rated_kw=float(item.get("rated_kw_override", value("prime_power_kw", 500))),
            rated_voltage_v=float(value("rated_voltage_v", raw.get("voltage_v", 400))),
            rated_frequency_hz=float(value("rated_frequency_hz", raw.get("frequency_hz", 50))),
            rated_power_factor=float(value("rated_power_factor", 0.8)),
            rated_rpm=float(value("rated_rpm", 1500)), breaker=Breaker(f"{item['name']} CB"),
            priority=int(item.get("priority", 1)),
            load_mode=str(item.get("load_mode", "proportional")),
            fixed_kw_setpoint=(None if item.get("fixed_kw_setpoint") is None else float(item["fixed_kw_setpoint"])),
            minimum_loading_pct=float(parameter("minimum_recommended_loading_pct", 30)),
            ramp_kw_per_s=float(parameter("ramp_up_kw_per_s", 50)),
            start_delay_s=float(parameter("start_delay_s", 2)),
            crank_duration_s=float(parameter("crank_duration_s", 3)),
            warm_up_s=float(parameter("warm_up_s", 5)), cool_down_s=float(parameter("cool_down_s", 5)),
            fuel_curve_lph=tuple(
                (fraction, float(profile.parameters[key].value))
                for fraction, key in ((.25, "fuel_consumption_lph_25"), (.5, "fuel_consumption_lph_50"), (.75, "fuel_consumption_lph_75"), (1, "fuel_consumption_lph_100"))
                if key in profile.parameters and profile.parameters[key].value is not None
            ),
        ))
    grid_raw = raw.get("grid", {})
    grid = None
    if grid_raw.get("enabled", False):
        grid_breaker = Breaker("GRID CB")
        if grid_raw.get("closed_on_start", True):
            grid_breaker.state, grid_breaker.feedback_closed = BreakerState.CLOSED, True
        grid = GridSource(
            nominal_voltage_v=float(grid_raw.get("voltage_v", raw.get("voltage_v", 400))),
            nominal_frequency_hz=float(grid_raw.get("frequency_hz", raw.get("frequency_hz", 50))),
            voltage_v=float(grid_raw.get("voltage_v", raw.get("voltage_v", 400))),
            frequency_hz=float(grid_raw.get("frequency_hz", raw.get("frequency_hz", 50))),
            breaker=grid_breaker,
        )
    solar_raw = raw.get("solar", {})
    solar = None
    if solar_raw.get("enabled", False):
        solar_breaker = Breaker("PV CB")
        if solar_raw.get("closed_on_start", True):
            solar_breaker.state, solar_breaker.feedback_closed = BreakerState.CLOSED, True
        solar = SolarSource(
            name=solar_raw.get("name", "SOLAR"), rated_kw=float(solar_raw.get("rated_kw", 500)),
            breaker=solar_breaker, irradiance_pct=float(solar_raw.get("irradiance_pct", 100)),
            inverter_efficiency=float(solar_raw.get("inverter_efficiency", .98)),
            ramp_kw_per_s=float(solar_raw.get("ramp_kw_per_s", 100)),
            grid_forming=bool(solar_raw.get("grid_forming", False)),
        )
    loads = [Load(**item) for item in raw.get("loads", [])]
    sync = SyncLimits(**raw.get("synchronization", {}))
    return Plant(raw["name"], float(raw.get("voltage_v", 400)), float(raw.get("frequency_hz", 50)), generators, loads, grid, solar, sync)


def save_runtime_state(plant: Plant, path: str | Path) -> None:
    data = {
        "name": plant.name, "simulation_speed": plant.simulation_speed,
        "paused": plant.paused,
        "generators": [{"name": g.name, "run_hours": g.run_hours, "energy_kwh": g.energy_kwh, "starts": g.starts, "fuel_used_l": g.fuel_used_l, "load_mode": g.load_mode, "fixed_kw_setpoint": g.fixed_kw_setpoint, "telemetry_overrides": g.telemetry_overrides} for g in plant.generators],
    }
    Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")


def restore_runtime_state(plant: Plant, path: str | Path) -> bool:
    state_path = Path(path)
    if not state_path.exists():
        return False
    raw = json.loads(state_path.read_text(encoding="utf-8"))
    plant.simulation_speed = float(raw.get("simulation_speed", 1.0))
    saved = {item["name"]: item for item in raw.get("generators", [])}
    for generator in plant.generators:
        item = saved.get(generator.name)
        if item:
            generator.run_hours = float(item.get("run_hours", generator.run_hours))
            generator.energy_kwh = float(item.get("energy_kwh", generator.energy_kwh))
            generator.starts = int(item.get("starts", generator.starts))
            generator.fuel_used_l = float(item.get("fuel_used_l", generator.fuel_used_l))
            generator.load_mode = str(item.get("load_mode", generator.load_mode))
            generator.fixed_kw_setpoint = item.get("fixed_kw_setpoint", generator.fixed_kw_setpoint)
            generator.telemetry_overrides = {str(key): float(value) for key, value in item.get("telemetry_overrides", {}).items()}
    return True
