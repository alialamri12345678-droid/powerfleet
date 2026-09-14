"""Deterministic RMS/quasi-steady-state electrical plant model."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
import math
import random
from typing import Callable

from simulator_core.electrical import calculate_three_phase, calculate_three_phase_pq


class GeneratorState(str, Enum):
    STOPPED = "STOPPED"
    PRESTART = "PRESTART"
    CRANKING = "CRANKING"
    STARTING = "STARTING"
    WARMING_UP = "WARMING_UP"
    RUNNING_OFF_LOAD = "RUNNING_OFF_LOAD"
    SYNCHRONIZING = "SYNCHRONIZING"
    BREAKER_CLOSED = "BREAKER_CLOSED"
    ON_LOAD = "ON_LOAD"
    COOLING_DOWN = "COOLING_DOWN"
    STOPPING = "STOPPING"
    FAILED_TO_START = "FAILED_TO_START"
    SHUTDOWN = "SHUTDOWN"
    ELECTRICAL_TRIP = "ELECTRICAL_TRIP"


class BreakerState(str, Enum):
    OPEN = "OPEN"
    CLOSED = "CLOSED"
    OPENING = "OPENING"
    CLOSING = "CLOSING"
    FAILED = "FAILED"


class AlarmSeverity(str, Enum):
    INACTIVE = "inactive"
    WARNING = "warning"
    ELECTRICAL_TRIP = "electrical_trip"
    SHUTDOWN = "shutdown"
    CONTROLLED_SHUTDOWN = "controlled_shutdown"


@dataclass
class Alarm:
    code: str
    severity: AlarmSeverity
    message: str
    active: bool = True
    latched: bool = True
    occurred_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    cleared_at: datetime | None = None


@dataclass
class Breaker:
    name: str
    state: BreakerState = BreakerState.OPEN
    feedback_closed: bool = False
    operation_time_s: float = 0.2
    fail_to_open: bool = False
    fail_to_close: bool = False
    _remaining_s: float = 0.0

    @property
    def closed(self) -> bool:
        return self.state is BreakerState.CLOSED and self.feedback_closed

    def request_open(self) -> bool:
        if self.state is BreakerState.OPEN:
            return True
        self.state = BreakerState.OPENING
        self._remaining_s = self.operation_time_s
        return True

    def request_close(self, permitted: bool = True) -> bool:
        if not permitted or self.state is BreakerState.FAILED:
            return False
        if self.state in {BreakerState.CLOSED, BreakerState.CLOSING}:
            return True
        self.state = BreakerState.CLOSING
        self._remaining_s = self.operation_time_s
        return True

    def update(self, dt: float) -> None:
        if self.state not in {BreakerState.OPENING, BreakerState.CLOSING}:
            return
        self._remaining_s -= dt
        if self._remaining_s > 0:
            return
        if self.state is BreakerState.OPENING:
            if self.fail_to_open:
                self.state = BreakerState.FAILED
            else:
                self.state, self.feedback_closed = BreakerState.OPEN, False
        elif self.fail_to_close:
            self.state, self.feedback_closed = BreakerState.FAILED, False
        else:
            self.state, self.feedback_closed = BreakerState.CLOSED, True


@dataclass(frozen=True)
class SyncLimits:
    max_frequency_difference_hz: float = 0.2
    max_voltage_difference_pct: float = 5.0
    max_phase_angle_difference_deg: float = 10.0
    minimum_stable_s: float = 0.5
    timeout_s: float = 30.0


@dataclass
class Load:
    name: str
    active_kw: float
    power_factor: float = 0.9
    enabled: bool = True
    variation_pct: float = 0.0
    scheduled_multiplier: float = 1.0
    kind: str = "fixed"
    step_kw: float = 0.0
    motor_start_multiplier: float = 1.0
    motor_start_remaining_s: float = 0.0

    def trigger_step(self, delta_kw: float) -> None:
        self.step_kw += delta_kw

    def trigger_motor_start(self, duration_s: float = 3.0, multiplier: float = 5.0) -> None:
        self.motor_start_remaining_s = max(0.0, duration_s)
        self.motor_start_multiplier = max(1.0, multiplier)

    def update(self, dt: float) -> None:
        self.motor_start_remaining_s = max(0.0, self.motor_start_remaining_s - dt)

    def demand(self, rng: random.Random) -> tuple[float, float]:
        if not self.enabled:
            return 0.0, 0.0
        noise = rng.uniform(-self.variation_pct, self.variation_pct) / 100.0
        multiplier = self.motor_start_multiplier if self.motor_start_remaining_s > 0 else 1.0
        kw = max(0.0, (self.active_kw * self.scheduled_multiplier + self.step_kw) * multiplier * (1.0 + noise))
        pf = max(0.01, min(1.0, abs(self.power_factor)))
        kvar = kw * math.tan(math.acos(pf)) * (1 if self.power_factor >= 0 else -1)
        return kw, kvar


@dataclass
class GridSource:
    name: str = "GRID"
    nominal_voltage_v: float = 400.0
    nominal_frequency_hz: float = 50.0
    voltage_v: float = 400.0
    frequency_hz: float = 50.0
    phase_angle_deg: float = 0.0
    phase_rotation: str = "ABC"
    available: bool = True
    breaker: Breaker = field(default_factory=lambda: Breaker("GRID CB"))
    active_kw: float = 0.0
    reactive_kvar: float = 0.0
    faults: set[str] = field(default_factory=set)

    @property
    def healthy(self) -> bool:
        return self.available and not self.faults and 0.8 * self.nominal_voltage_v <= self.voltage_v <= 1.2 * self.nominal_voltage_v and abs(self.frequency_hz - self.nominal_frequency_hz) <= 5

    def update(self, dt: float) -> None:
        self.breaker.update(dt)
        self.phase_angle_deg = (self.phase_angle_deg + self.frequency_hz * 360.0 * dt) % 360.0
        if not self.available:
            self.voltage_v = 0.0
            self.frequency_hz = 0.0
            self.active_kw = self.reactive_kvar = 0.0
            self.breaker.request_open()
        elif "undervoltage" in self.faults:
            self.voltage_v = 0.75 * self.nominal_voltage_v
        elif "overvoltage" in self.faults:
            self.voltage_v = 1.25 * self.nominal_voltage_v
        else:
            self.voltage_v += (self.nominal_voltage_v - self.voltage_v) * min(1.0, dt)
        if "underfrequency" in self.faults:
            self.frequency_hz = self.nominal_frequency_hz - 6
        elif "overfrequency" in self.faults:
            self.frequency_hz = self.nominal_frequency_hz + 6
        elif self.available:
            self.frequency_hz += (self.nominal_frequency_hz - self.frequency_hz) * min(1.0, dt)
        if "frequency_instability" in self.faults:
            self.frequency_hz += math.sin(self.phase_angle_deg * math.pi / 180.0) * 2.0
        if self.faults:
            self.breaker.request_open()


@dataclass
class SolarSource:
    name: str
    rated_kw: float
    breaker: Breaker
    enabled: bool = True
    irradiance_pct: float = 100.0
    inverter_efficiency: float = 0.98
    active_power_setpoint_kw: float | None = None
    curtailment_limit_kw: float | None = None
    reactive_power_setpoint_kvar: float = 0.0
    power_factor_setpoint: float = 1.0
    ramp_kw_per_s: float = 100.0
    grid_forming: bool = False
    online: bool = True
    active_kw: float = 0.0
    reactive_kvar: float = 0.0
    fault: str | None = None

    @property
    def available_kw(self) -> float:
        return max(0.0, min(self.rated_kw, self.rated_kw * self.irradiance_pct / 100.0 * self.inverter_efficiency))

    def update(self, dt: float, bus_energized: bool) -> None:
        may_run = self.enabled and self.online and self.fault is None and self.breaker.closed and (bus_energized or self.grid_forming)
        target = self.available_kw if may_run else 0.0
        if self.active_power_setpoint_kw is not None:
            target = min(target, max(0.0, self.active_power_setpoint_kw))
        if self.curtailment_limit_kw is not None:
            target = min(target, max(0.0, self.curtailment_limit_kw))
        change = max(-self.ramp_kw_per_s * dt, min(self.ramp_kw_per_s * dt, target - self.active_kw))
        self.active_kw += change
        self.reactive_kvar = self.reactive_power_setpoint_kvar if may_run else 0.0


@dataclass
class Generator:
    name: str
    rated_kw: float
    rated_voltage_v: float
    rated_frequency_hz: float
    rated_power_factor: float
    rated_rpm: float
    breaker: Breaker
    priority: int = 1
    minimum_loading_pct: float = 30.0
    ramp_kw_per_s: float = 50.0
    start_delay_s: float = 2.0
    crank_duration_s: float = 3.0
    warm_up_s: float = 5.0
    cool_down_s: float = 5.0
    minimum_run_s: float = 10.0
    state: GeneratorState = GeneratorState.STOPPED
    commanded_start: bool = False
    commanded_stop: bool = False
    available: bool = True
    load_mode: str = "proportional"
    fixed_kw_setpoint: float | None = None
    target_kw: float = 0.0
    target_kvar: float = 0.0
    active_kw: float = 0.0
    reactive_kvar: float = 0.0
    voltage_v: float = 0.0
    frequency_hz: float = 0.0
    rpm: float = 0.0
    phase_angle_deg: float = 0.0
    coolant_temp_c: float = 25.0
    oil_pressure_kpa: float = 0.0
    battery_voltage_v: float = 24.5
    current_a: float = 0.0
    apparent_kva: float = 0.0
    power_factor: float = 0.8
    run_hours: float = 0.0
    energy_kwh: float = 0.0
    starts: int = 0
    fuel_used_l: float = 0.0
    fuel_curve_lph: tuple[tuple[float, float], ...] = ()
    fuel_level_pct: float = 100.0
    oil_temp_c: float = 25.0
    telemetry_overrides: dict[str, float] = field(default_factory=dict)
    alarms: dict[str, Alarm] = field(default_factory=dict)
    _state_elapsed_s: float = 0.0
    _run_elapsed_s: float = 0.0
    _sync_elapsed_s: float = 0.0
    _sync_stable_s: float = 0.0
    fail_to_start: bool = False
    fail_to_stop: bool = False
    phase_rotation: str = "ABC"

    @property
    def running(self) -> bool:
        return self.state in {
            GeneratorState.WARMING_UP, GeneratorState.RUNNING_OFF_LOAD,
            GeneratorState.SYNCHRONIZING, GeneratorState.BREAKER_CLOSED,
            GeneratorState.ON_LOAD, GeneratorState.COOLING_DOWN,
        }

    @property
    def connected(self) -> bool:
        return self.breaker.closed and self.running

    def telemetry(self, key: str, calculated: float) -> float:
        """Return a deliberate SCADA mock override or the calculated value."""
        return float(self.telemetry_overrides.get(key, calculated))

    def start(self) -> bool:
        if not self.available or self.state not in {GeneratorState.STOPPED, GeneratorState.FAILED_TO_START}:
            return False
        self.commanded_start, self.commanded_stop = True, False
        if self.state is GeneratorState.FAILED_TO_START:
            self.reset_alarms()
        return True

    def stop(self) -> bool:
        if self.state is GeneratorState.STOPPED:
            return True
        self.commanded_stop, self.commanded_start = True, False
        return True

    def transition(self, state: GeneratorState) -> None:
        self.state = state
        self._state_elapsed_s = 0.0

    def raise_alarm(self, code: str, severity: AlarmSeverity, message: str) -> None:
        self.alarms[code] = Alarm(code, severity, message)
        if severity is AlarmSeverity.SHUTDOWN:
            self.breaker.request_open()
            self.transition(GeneratorState.SHUTDOWN)
        elif severity is AlarmSeverity.ELECTRICAL_TRIP:
            self.breaker.request_open()
            self.transition(GeneratorState.ELECTRICAL_TRIP)

    def reset_alarms(self) -> None:
        now = datetime.now(timezone.utc)
        for alarm in self.alarms.values():
            alarm.active = False
            alarm.cleared_at = now
        if self.state in {GeneratorState.SHUTDOWN, GeneratorState.ELECTRICAL_TRIP, GeneratorState.FAILED_TO_START}:
            self.transition(GeneratorState.STOPPED)

    def _fuel_lph(self) -> float:
        if not self.fuel_curve_lph or not self.running:
            return 0.0
        fraction = max(0.0, min(1.0, self.active_kw / self.rated_kw))
        points = sorted(self.fuel_curve_lph)
        if fraction <= points[0][0]:
            return points[0][1] * fraction / max(points[0][0], 0.001)
        for (x0, y0), (x1, y1) in zip(points, points[1:]):
            if fraction <= x1:
                return y0 + (y1 - y0) * (fraction - x0) / (x1 - x0)
        return points[-1][1]

    def update(self, dt: float, bus_voltage_v: float, bus_frequency_hz: float, bus_phase_angle_deg: float, sync_limits: SyncLimits) -> None:
        self.breaker.update(dt)
        if not self.breaker.closed and self.state in {GeneratorState.BREAKER_CLOSED, GeneratorState.ON_LOAD}:
            self.active_kw = self.reactive_kvar = self.target_kw = self.target_kvar = 0.0
            self.transition(GeneratorState.RUNNING_OFF_LOAD)
        self._state_elapsed_s += dt
        if self.commanded_start and self.state is GeneratorState.STOPPED:
            self.transition(GeneratorState.PRESTART)
        if self.commanded_stop and self.state in {
            GeneratorState.WARMING_UP,
            GeneratorState.RUNNING_OFF_LOAD,
            GeneratorState.SYNCHRONIZING,
        } and not self.connected:
            self.transition(GeneratorState.COOLING_DOWN)

        if self.state is GeneratorState.PRESTART and self._state_elapsed_s >= self.start_delay_s:
            self.transition(GeneratorState.CRANKING)
        elif self.state is GeneratorState.CRANKING:
            self.rpm = min(self.rated_rpm * 0.35, self.rated_rpm * 0.35 * self._state_elapsed_s / max(self.crank_duration_s, 0.01))
            self.oil_pressure_kpa = 100.0 * self.rpm / max(self.rated_rpm, 1)
            if self._state_elapsed_s >= self.crank_duration_s:
                if self.fail_to_start:
                    self.raise_alarm("fail_to_start", AlarmSeverity.SHUTDOWN, "Failed to start")
                    self.transition(GeneratorState.FAILED_TO_START)
                else:
                    self.starts += 1
                    self.transition(GeneratorState.STARTING)
        elif self.state is GeneratorState.STARTING:
            fraction = min(1.0, self._state_elapsed_s / 2.0)
            self.rpm = self.rated_rpm * (0.35 + 0.65 * fraction)
            self.frequency_hz = self.rated_frequency_hz * fraction
            self.voltage_v = self.rated_voltage_v * fraction
            self.oil_pressure_kpa = 350.0 * fraction
            if fraction >= 1:
                self.transition(GeneratorState.WARMING_UP)
        elif self.state is GeneratorState.WARMING_UP:
            self._running_telemetry(dt)
            if self._state_elapsed_s >= self.warm_up_s:
                self.transition(GeneratorState.RUNNING_OFF_LOAD)
        elif self.state in {GeneratorState.RUNNING_OFF_LOAD, GeneratorState.SYNCHRONIZING}:
            self._running_telemetry(dt)
            if self.state is GeneratorState.SYNCHRONIZING:
                self._synchronize(dt, bus_voltage_v, bus_frequency_hz, bus_phase_angle_deg, sync_limits)
        elif self.state in {GeneratorState.BREAKER_CLOSED, GeneratorState.ON_LOAD}:
            self._running_telemetry(dt)
            change = max(-self.ramp_kw_per_s * dt, min(self.ramp_kw_per_s * dt, self.target_kw - self.active_kw))
            self.active_kw = max(-0.1 * self.rated_kw, min(1.1 * self.rated_kw, self.active_kw + change))
            kvar_change = max(-self.ramp_kw_per_s * dt, min(self.ramp_kw_per_s * dt, self.target_kvar - self.reactive_kvar))
            self.reactive_kvar += kvar_change
            self.state = GeneratorState.ON_LOAD if abs(self.active_kw) > 0.5 else GeneratorState.BREAKER_CLOSED
            if self.commanded_stop:
                self.target_kw = 0.0
                if abs(self.active_kw) <= 0.5:
                    self.breaker.request_open()
        elif self.state is GeneratorState.COOLING_DOWN:
            self._running_telemetry(dt)
            self.active_kw = self.reactive_kvar = 0.0
            if self._state_elapsed_s >= self.cool_down_s:
                self.transition(GeneratorState.STOPPING)
        elif self.state is GeneratorState.STOPPING:
            if self.fail_to_stop:
                self.raise_alarm("fail_to_stop", AlarmSeverity.WARNING, "Failed to stop")
                self.transition(GeneratorState.RUNNING_OFF_LOAD)
            else:
                fraction = max(0.0, 1.0 - self._state_elapsed_s / 2.0)
                self.rpm = self.rated_rpm * fraction
                self.frequency_hz = self.rated_frequency_hz * fraction
                self.voltage_v = self.rated_voltage_v * fraction
                if fraction <= 0:
                    self.commanded_stop = self.commanded_start = False
                    self.transition(GeneratorState.STOPPED)
        elif self.state is GeneratorState.STOPPED:
            self.rpm = self.frequency_hz = self.voltage_v = 0.0
            self.active_kw = self.reactive_kvar = self.current_a = self.apparent_kva = 0.0
            self.oil_pressure_kpa = 0.0
            self.coolant_temp_c += (25.0 - self.coolant_temp_c) * min(1.0, dt / 120.0)

        if self.running:
            self._run_elapsed_s += dt
            self.run_hours += dt / 3600.0
            self.energy_kwh += max(0.0, self.active_kw) * dt / 3600.0
            self.fuel_used_l += self._fuel_lph() * dt / 3600.0
        self._apply_fault_telemetry()
        if self.voltage_v > 0:
            measurement = calculate_three_phase_pq(self.active_kw, self.reactive_kvar, self.voltage_v)
            self.current_a, self.apparent_kva, self.power_factor = measurement.current_a, measurement.apparent_power_kva, measurement.power_factor

    def _apply_fault_telemetry(self) -> None:
        active = {code for code, alarm in self.alarms.items() if alarm.active}
        if "low_oil_pressure" in active:
            self.oil_pressure_kpa = min(self.oil_pressure_kpa, 50.0)
        if "high_coolant_temperature" in active:
            self.coolant_temp_c = max(self.coolant_temp_c, 110.0)
        if "overspeed" in active:
            self.rpm = max(self.rpm, self.rated_rpm * 1.15)
        if "underspeed" in active:
            self.rpm = min(self.rpm, self.rated_rpm * .8)
        if "overfrequency" in active:
            self.frequency_hz = max(self.frequency_hz, self.rated_frequency_hz * 1.1)
        if "underfrequency" in active:
            self.frequency_hz = min(self.frequency_hz, self.rated_frequency_hz * .85)
        if "overvoltage" in active:
            self.voltage_v = max(self.voltage_v, self.rated_voltage_v * 1.15)
        if "undervoltage" in active:
            self.voltage_v = min(self.voltage_v, self.rated_voltage_v * .75)
        if "battery_low" in active:
            self.battery_voltage_v = min(self.battery_voltage_v, 18.0)
        if "loss_of_speed_signal" in active:
            self.rpm = 0.0

    def _running_telemetry(self, dt: float) -> None:
        self.rpm += (self.rated_rpm - self.rpm) * min(1.0, dt * 2.0)
        self.frequency_hz += (self.rated_frequency_hz - self.frequency_hz) * min(1.0, dt * 2.0)
        self.voltage_v += (self.rated_voltage_v - self.voltage_v) * min(1.0, dt * 2.0)
        target_temp = 78.0 + 12.0 * max(0.0, self.active_kw / self.rated_kw)
        self.coolant_temp_c += (target_temp - self.coolant_temp_c) * min(1.0, dt / 90.0)
        self.oil_temp_c += (target_temp + 5.0 - self.oil_temp_c) * min(1.0, dt / 120.0)
        self.oil_pressure_kpa += (400.0 - self.oil_pressure_kpa) * min(1.0, dt / 2.0)
        self.battery_voltage_v += (27.5 - self.battery_voltage_v) * min(1.0, dt / 5.0)
        self.phase_angle_deg = (self.phase_angle_deg + self.frequency_hz * 360.0 * dt) % 360.0

    def begin_synchronizing(self) -> bool:
        if self.state is not GeneratorState.RUNNING_OFF_LOAD:
            return False
        self.transition(GeneratorState.SYNCHRONIZING)
        self._sync_elapsed_s = self._sync_stable_s = 0.0
        return True

    def _synchronize(self, dt: float, bus_v: float, bus_hz: float, bus_angle: float, limits: SyncLimits) -> None:
        self._sync_elapsed_s += dt
        if bus_v <= 0:
            if self.breaker.request_close():
                return
        voltage_error = bus_v - self.voltage_v
        frequency_error = bus_hz - self.frequency_hz
        angle_error = ((bus_angle - self.phase_angle_deg + 180.0) % 360.0) - 180.0
        self.voltage_v += voltage_error * min(1.0, dt * 1.5)
        self.frequency_hz += frequency_error * min(1.0, dt * 1.5)
        self.phase_angle_deg = (self.phase_angle_deg + angle_error * min(1.0, dt * 2.0)) % 360.0
        acceptable = (
            abs(frequency_error) <= limits.max_frequency_difference_hz
            and abs(voltage_error) <= bus_v * limits.max_voltage_difference_pct / 100.0
            and abs(angle_error) <= limits.max_phase_angle_difference_deg
            and self.phase_rotation == "ABC"
        )
        self._sync_stable_s = self._sync_stable_s + dt if acceptable else 0.0
        if self._sync_stable_s >= limits.minimum_stable_s:
            self.breaker.request_close(True)
        if self.breaker.closed:
            self.transition(GeneratorState.BREAKER_CLOSED)
        elif self._sync_elapsed_s >= limits.timeout_s:
            self.raise_alarm("sync_timeout", AlarmSeverity.WARNING, "Synchronization timeout")
            self.transition(GeneratorState.RUNNING_OFF_LOAD)


@dataclass
class Plant:
    name: str
    nominal_voltage_v: float
    nominal_frequency_hz: float
    generators: list[Generator]
    loads: list[Load]
    grid: GridSource | None = None
    solar: SolarSource | None = None
    sync_limits: SyncLimits = field(default_factory=SyncLimits)
    simulation_speed: float = 1.0
    paused: bool = False
    bus_voltage_v: float = 0.0
    bus_frequency_hz: float = 0.0
    bus_phase_angle_deg: float = 0.0
    bus_active_kw: float = 0.0
    bus_reactive_kvar: float = 0.0
    grid_import_kw: float = 0.0
    rng_seed: int = 1
    event_sink: Callable[[str, str], None] | None = None
    _rng: random.Random = field(init=False, repr=False)
    grid_sync_requested: bool = False
    grid_sync_elapsed_s: float = 0.0
    grid_sync_stable_s: float = 0.0

    def __post_init__(self) -> None:
        self._rng = random.Random(self.rng_seed)

    @property
    def bus_energized(self) -> bool:
        return self.bus_voltage_v > 0.5 * self.nominal_voltage_v

    def total_demand(self) -> tuple[float, float]:
        demands = [load.demand(self._rng) for load in self.loads]
        return sum(x[0] for x in demands), sum(x[1] for x in demands)

    def emit(self, event: str, detail: str) -> None:
        if self.event_sink:
            self.event_sink(event, detail)

    def update(self, real_dt: float) -> None:
        if self.paused:
            return
        dt = real_dt * self.simulation_speed
        for load in self.loads:
            load.update(dt)
        if self.grid:
            self.grid.update(dt)
        reference_v = reference_hz = 0.0
        reference_angle = self.bus_phase_angle_deg
        if self.grid and self.grid.healthy and self.grid.breaker.closed:
            reference_v, reference_hz, reference_angle = self.grid.voltage_v, self.grid.frequency_hz, self.grid.phase_angle_deg
        else:
            connected = [g for g in self.generators if g.connected]
            if connected:
                reference_v = sum(g.voltage_v for g in connected) / len(connected)
                reference_hz = sum(g.frequency_hz for g in connected) / len(connected)
                reference_angle = connected[0].phase_angle_deg
        self.bus_voltage_v, self.bus_frequency_hz = reference_v, reference_hz
        self.bus_phase_angle_deg = reference_angle

        for generator in self.generators:
            generator.update(dt, reference_v, reference_hz, reference_angle, self.sync_limits)
        self._update_grid_synchronization(dt)
        if self.solar:
            self.solar.breaker.update(dt)
            self.solar.update(dt, self.bus_energized)

        demand_kw, demand_kvar = self.total_demand()
        gen_kw = sum(g.active_kw for g in self.generators if g.connected)
        gen_kvar = sum(g.reactive_kvar for g in self.generators if g.connected)
        solar_kw = self.solar.active_kw if self.solar else 0.0
        solar_kvar = self.solar.reactive_kvar if self.solar else 0.0
        grid_connected = bool(self.grid and self.grid.healthy and self.grid.breaker.closed)
        self.grid_import_kw = demand_kw - gen_kw - solar_kw if grid_connected else 0.0
        if self.grid:
            self.grid.active_kw = self.grid_import_kw
            self.grid.reactive_kvar = demand_kvar - gen_kvar - solar_kvar if grid_connected else 0.0
        self.bus_active_kw, self.bus_reactive_kvar = demand_kw, demand_kvar

    def share_generator_load(self, required_kw: float, mode: str = "proportional") -> None:
        online = [g for g in self.generators if g.connected and g.available and not any(a.active and a.severity in {AlarmSeverity.SHUTDOWN, AlarmSeverity.ELECTRICAL_TRIP} for a in g.alarms.values())]
        if not online:
            return
        fixed = [g for g in online if g.load_mode in {"fixed_kw", "base_load"} and g.fixed_kw_setpoint is not None]
        remaining = required_kw
        for generator in fixed:
            generator.target_kw = max(0.0, min(generator.rated_kw, generator.fixed_kw_setpoint or 0.0))
            remaining -= generator.target_kw
        sharing = [g for g in online if g not in fixed]
        if not sharing:
            return
        if mode == "priority":
            remaining = max(0.0, remaining)
            for generator in sorted(sharing, key=lambda g: g.priority):
                generator.target_kw = min(generator.rated_kw, remaining)
                remaining -= generator.target_kw
        else:
            total_rating = sum(g.rated_kw for g in sharing)
            for generator in sharing:
                generator.target_kw = max(0.0, remaining) * generator.rated_kw / total_rating

    def share_reactive_load(self, required_kvar: float) -> None:
        online = [g for g in self.generators if g.connected and g.available]
        if not online:
            return
        total_kva = sum(g.rated_kw / max(g.rated_power_factor, .01) for g in online)
        for generator in online:
            generator.target_kvar = required_kvar * (generator.rated_kw / max(generator.rated_power_factor, .01)) / total_kva

    def close_generator_breaker(self, generator: Generator, force: bool = False) -> bool:
        if generator.state is not GeneratorState.RUNNING_OFF_LOAD:
            return False
        if not self.bus_energized:
            accepted = generator.breaker.request_close(True)
            if accepted:
                generator.transition(GeneratorState.SYNCHRONIZING)
            return accepted
        if force:
            accepted = generator.breaker.request_close(True)
            if accepted:
                generator.raise_alarm("out_of_sync_close", AlarmSeverity.ELECTRICAL_TRIP, "Forced out-of-sync close")
            return accepted
        return generator.begin_synchronizing()

    def synchronize_grid(self) -> bool:
        if not self.grid or not self.grid.healthy:
            return False
        if not self.bus_energized:
            return self.grid.breaker.request_close(True)
        self.grid_sync_requested = True
        self.grid_sync_elapsed_s = self.grid_sync_stable_s = 0.0
        return True

    def _update_grid_synchronization(self, dt: float) -> None:
        if not self.grid_sync_requested or not self.grid or self.grid.breaker.closed:
            return
        self.grid_sync_elapsed_s += dt
        angle_error = ((self.grid.phase_angle_deg - self.bus_phase_angle_deg + 180) % 360) - 180
        frequency_error = self.grid.frequency_hz - self.bus_frequency_hz
        voltage_error = self.grid.voltage_v - self.bus_voltage_v
        connected = [g for g in self.generators if g.connected]
        for generator in connected:
            generator.frequency_hz += frequency_error * min(1.0, dt)
            generator.voltage_v += voltage_error * min(1.0, dt)
            generator.phase_angle_deg = (generator.phase_angle_deg + angle_error * min(1.0, dt * 2)) % 360
        acceptable = bool(connected) and abs(frequency_error) <= self.sync_limits.max_frequency_difference_hz and abs(voltage_error) <= self.grid.voltage_v * self.sync_limits.max_voltage_difference_pct / 100 and abs(angle_error) <= self.sync_limits.max_phase_angle_difference_deg and self.grid.phase_rotation == "ABC"
        self.grid_sync_stable_s = self.grid_sync_stable_s + dt if acceptable else 0.0
        if self.grid_sync_stable_s >= self.sync_limits.minimum_stable_s:
            self.grid.breaker.request_close(True)
        if self.grid_sync_elapsed_s >= self.sync_limits.timeout_s:
            self.grid_sync_requested = False
            self.emit("grid_sync_timeout", "Grid synchronization timed out")
