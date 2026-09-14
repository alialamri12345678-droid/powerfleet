"""Quasi-steady-state electrical calculations used by all source models."""

from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class ThreePhaseMeasurement:
    line_voltage_v: float
    current_a: float
    active_power_kw: float
    reactive_power_kvar: float
    apparent_power_kva: float
    power_factor: float


def calculate_three_phase(active_power_kw: float, line_voltage_v: float, power_factor: float) -> ThreePhaseMeasurement:
    """Return an internally consistent balanced three-phase measurement.

    Positive kW/kVAr is generation. A negative power factor represents leading
    reactive power while active-power direction remains controlled by kW.
    """
    if line_voltage_v < 0:
        raise ValueError("line voltage cannot be negative")
    if not -1.0 <= power_factor <= 1.0 or power_factor == 0:
        raise ValueError("power factor must be in [-1, 1] and non-zero")
    if active_power_kw == 0 or line_voltage_v == 0:
        return ThreePhaseMeasurement(line_voltage_v, 0.0, active_power_kw, 0.0, 0.0, power_factor)

    pf_magnitude = abs(power_factor)
    apparent_kva = abs(active_power_kw) / pf_magnitude
    current_a = apparent_kva * 1000.0 / (math.sqrt(3.0) * line_voltage_v)
    reactive_magnitude = math.sqrt(max(0.0, apparent_kva**2 - active_power_kw**2))
    reactive_kvar = math.copysign(reactive_magnitude, power_factor)
    return ThreePhaseMeasurement(
        line_voltage_v=line_voltage_v,
        current_a=current_a,
        active_power_kw=active_power_kw,
        reactive_power_kvar=reactive_kvar,
        apparent_power_kva=apparent_kva,
        power_factor=power_factor,
    )


def calculate_three_phase_pq(active_power_kw: float, reactive_power_kvar: float, line_voltage_v: float) -> ThreePhaseMeasurement:
    """Return balanced three-phase measurements from active and reactive power."""
    if line_voltage_v < 0:
        raise ValueError("line voltage cannot be negative")
    apparent_kva = math.hypot(active_power_kw, reactive_power_kvar)
    current_a = apparent_kva * 1000.0 / (math.sqrt(3.0) * line_voltage_v) if line_voltage_v and apparent_kva else 0.0
    power_factor = active_power_kw / apparent_kva if apparent_kva else 1.0
    return ThreePhaseMeasurement(line_voltage_v, current_a, active_power_kw, reactive_power_kvar, apparent_kva, power_factor)
