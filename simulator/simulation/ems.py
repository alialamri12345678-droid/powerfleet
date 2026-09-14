"""Supervisory power-management decisions; no transport or UI dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from .plant import Plant


@dataclass
class PowerManagementConfig:
    enabled: bool = True
    spinning_reserve_kw: float = 0.0
    minimum_generator_loading_enabled: bool = True
    grid_import_target_kw: float | None = None
    grid_export_limit_kw: float = 0.0
    load_share_mode: str = "proportional"
    automatic_start_stop: bool = True
    automatic_breaker_control: bool = False


class PowerManager:
    def __init__(self, plant: Plant, config: PowerManagementConfig | None = None):
        self.plant = plant
        self.config = config or PowerManagementConfig()

    def update(self) -> None:
        if not self.config.enabled:
            return
        demand_kw, demand_kvar = self.plant.total_demand()
        grid_connected = bool(self.plant.grid and self.plant.grid.healthy and self.plant.grid.breaker.closed)
        if self.config.automatic_start_stop and not grid_connected:
            required_capacity = demand_kw + self.config.spinning_reserve_kw
            selected_capacity = 0.0
            for generator in sorted((g for g in self.plant.generators if g.available), key=lambda g: g.priority):
                if selected_capacity < required_capacity:
                    generator.start()
                    selected_capacity += generator.rated_kw
        if self.config.automatic_breaker_control:
            for generator in self.plant.generators:
                if generator.state.value == "RUNNING_OFF_LOAD" and not generator.breaker.closed:
                    self.plant.close_generator_breaker(generator)
        connected = [g for g in self.plant.generators if g.connected]
        solar = self.plant.solar
        if solar:
            solar_limit = solar.available_kw
            if connected and self.config.minimum_generator_loading_enabled:
                minimum_genset_kw = sum(g.rated_kw * g.minimum_loading_pct / 100.0 for g in connected)
                solar_limit = min(solar_limit, max(0.0, demand_kw - minimum_genset_kw))
            if grid_connected and self.config.grid_export_limit_kw >= 0:
                solar_limit = min(solar_limit, max(0.0, demand_kw + self.config.grid_export_limit_kw))
            solar.curtailment_limit_kw = solar_limit
        solar_kw = solar.active_kw if solar else 0.0
        if connected:
            if grid_connected and self.config.grid_import_target_kw is not None:
                required = demand_kw - solar_kw - self.config.grid_import_target_kw
            elif grid_connected:
                required = sum(g.target_kw for g in connected)
            else:
                required = demand_kw - solar_kw
            self.plant.share_generator_load(max(0.0, required), self.config.load_share_mode)
            grid_kvar = self.plant.grid.reactive_kvar if grid_connected and self.plant.grid else 0.0
            solar_kvar = solar.reactive_kvar if solar else 0.0
            self.plant.share_reactive_load(demand_kvar - grid_kvar - solar_kvar)
