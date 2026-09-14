"""Manual fault injection mapped to physical state and alarms."""

from __future__ import annotations

from .plant import AlarmSeverity, Generator, GridSource, SolarSource


GENERATOR_FAULTS = {
    "low_oil_pressure": (AlarmSeverity.SHUTDOWN, "Low oil pressure"),
    "high_coolant_temperature": (AlarmSeverity.SHUTDOWN, "High coolant temperature"),
    "overspeed": (AlarmSeverity.SHUTDOWN, "Overspeed"),
    "underspeed": (AlarmSeverity.WARNING, "Underspeed"),
    "overfrequency": (AlarmSeverity.ELECTRICAL_TRIP, "Generator high frequency"),
    "underfrequency": (AlarmSeverity.ELECTRICAL_TRIP, "Generator low frequency"),
    "overvoltage": (AlarmSeverity.ELECTRICAL_TRIP, "Generator high voltage"),
    "undervoltage": (AlarmSeverity.ELECTRICAL_TRIP, "Generator low voltage"),
    "overcurrent": (AlarmSeverity.ELECTRICAL_TRIP, "Generator high current"),
    "reverse_power": (AlarmSeverity.ELECTRICAL_TRIP, "Generator reverse power"),
    "emergency_stop": (AlarmSeverity.SHUTDOWN, "Emergency stop"),
    "battery_low": (AlarmSeverity.WARNING, "Low battery voltage"),
    "charger_failure": (AlarmSeverity.WARNING, "Charge alternator failure"),
    "ecu_j1939_fault": (AlarmSeverity.WARNING, "ECU J1939 fault"),
    "loss_of_speed_signal": (AlarmSeverity.SHUTDOWN, "Loss of speed sensing"),
    "sensor_fault": (AlarmSeverity.WARNING, "Sensor fault"),
    "phase_loss": (AlarmSeverity.ELECTRICAL_TRIP, "Generator phase loss"),
    "phase_reversal": (AlarmSeverity.ELECTRICAL_TRIP, "Generator phase reversal"),
    "out_of_sync": (AlarmSeverity.ELECTRICAL_TRIP, "Out-of-sync condition"),
    "breaker_feedback_mismatch": (AlarmSeverity.WARNING, "Breaker feedback mismatch"),
}


def inject_generator_fault(generator: Generator, name: str) -> None:
    if name == "fail_to_start":
        generator.fail_to_start = True
        return
    if name == "fail_to_stop":
        generator.fail_to_stop = True
        return
    if name == "breaker_fails_to_open":
        generator.breaker.fail_to_open = True
        return
    if name == "breaker_fails_to_close":
        generator.breaker.fail_to_close = True
        return
    if name == "phase_reversal":
        generator.phase_rotation = "ACB"
    try:
        severity, message = GENERATOR_FAULTS[name]
    except KeyError as exc:
        raise ValueError(f"unknown generator fault: {name}") from exc
    generator.raise_alarm(name, severity, message)


def inject_grid_fault(grid: GridSource, name: str, active: bool = True) -> None:
    if name == "mains_failure":
        grid.available = not active
    elif name == "phase_reversal":
        grid.phase_rotation = "ACB" if active else "ABC"
        if active: grid.faults.add(name)
        else: grid.faults.discard(name)
    elif name == "phase_loss":
        if active: grid.faults.add(name)
        else: grid.faults.discard(name)
    elif name == "frequency_instability":
        if active: grid.faults.add(name)
        else: grid.faults.discard(name)
    elif active:
        grid.faults.add(name)
    else:
        grid.faults.discard(name)


def inject_solar_fault(solar: SolarSource, name: str | None) -> None:
    solar.fault = name
    if name == "inverter_offline":
        solar.online = False
    elif name is None:
        solar.online = True
    elif name == "reduced_irradiance":
        solar.irradiance_pct = min(solar.irradiance_pct, 20.0)
        solar.fault = None
    elif name == "power_curtailment":
        solar.curtailment_limit_kw = 0.25 * solar.rated_kw
        solar.fault = None
