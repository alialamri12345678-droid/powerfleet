"""Reusable deterministic scenario runner."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from .faults import inject_generator_fault, inject_grid_fault
from .plant import Plant


@dataclass(frozen=True)
class ScenarioStep:
    name: str
    duration_s: float
    action: Callable[[Plant], None]


class ScenarioRunner:
    def __init__(self, plant: Plant, steps: list[ScenarioStep]):
        self.plant, self.steps = plant, steps
        self.index = 0
        self.elapsed_s = 0.0
        self.running = False

    @property
    def current_step(self) -> str:
        return self.steps[self.index].name if self.steps and self.index < len(self.steps) else "Complete"

    def run(self) -> None:
        self.running = True
        if self.steps and self.elapsed_s == 0:
            self.steps[self.index].action(self.plant)

    def pause(self) -> None:
        self.running = False

    def reset(self) -> None:
        self.index = 0
        self.elapsed_s = 0.0
        self.running = False

    def update(self, dt: float) -> None:
        if not self.running or self.index >= len(self.steps):
            return
        self.elapsed_s += dt
        if self.elapsed_s >= self.steps[self.index].duration_s:
            self.index += 1
            self.elapsed_s = 0.0
            if self.index < len(self.steps):
                self.steps[self.index].action(self.plant)
            else:
                self.running = False


def standard_scenarios(plant: Plant) -> dict[str, list[ScenarioStep]]:
    def grid_close(p: Plant) -> None:
        if p.grid:
            p.grid.available = True; p.grid.voltage_v = p.grid.nominal_voltage_v; p.grid.frequency_hz = p.grid.nominal_frequency_hz; p.grid.breaker.request_close()
    def grid_fail(p: Plant) -> None:
        if p.grid: inject_grid_fault(p.grid, "mains_failure", True)
    def start_all(p: Plant) -> None:
        for gen in p.generators: gen.start()
    def start_first(p: Plant) -> None:
        if p.generators: p.generators[0].start()
    def comm_fail(p: Plant) -> None:
        p.emit("communication_failure", "Scenario requested controller communication failure")
    def close_all_generators(p: Plant) -> None:
        for gen in p.generators: p.close_generator_breaker(gen)
    def fail_first_generator(p: Plant) -> None:
        if p.generators: inject_generator_fault(p.generators[0], "low_oil_pressure")
    def grid_restore_sync(p: Plant) -> None:
        grid_close(p)
        if p.grid:
            p.grid.breaker.request_open(); p.grid.breaker.update(1)
            p.synchronize_grid()
    return {
        "Normal grid operation": [ScenarioStep("Close grid breaker", 2, grid_close)],
        "Grid failure to generators": [ScenarioStep("Grid healthy", 2, grid_close), ScenarioStep("Grid failure", 1, grid_fail), ScenarioStep("Start generators", 15, start_all)],
        "Three generators load share": [ScenarioStep("Start generators", 15, start_all), ScenarioStep("Close and share", 10, close_all_generators)],
        "Generator failure while parallel": [ScenarioStep("Start generators", 15, start_all), ScenarioStep("Close and share", 10, close_all_generators), ScenarioStep("Trip first generator", 5, fail_first_generator)],
        "Grid restoration and synchronization": [ScenarioStep("Grid failure", 2, grid_fail), ScenarioStep("Start generator", 15, start_first), ScenarioStep("Close island generator", 3, close_all_generators), ScenarioStep("Restore and synchronize grid", 10, grid_restore_sync)],
        "Solar and grid": [ScenarioStep("Close grid breaker", 2, grid_close)],
        "Solar and generator island": [ScenarioStep("Grid failure", 1, grid_fail), ScenarioStep("Start generator", 15, start_first)],
        "Solar curtailment": [ScenarioStep("Start generator", 15, start_first)],
        "Communication failure": [ScenarioStep("Inject communication failure", 5, comm_fail)],
        "SCADA remote start": [ScenarioStep("Remote start first generator", 15, start_first)],
    }
