"""Explainable preventive-maintenance analysis for one generator."""

from __future__ import annotations

from dataclasses import dataclass
from math import ceil
from statistics import mean
from typing import Any, Iterable


@dataclass(frozen=True)
class MetricRule:
    key: str
    label: str
    unit: str
    low_warning: float | None = None
    high_warning: float | None = None
    high_critical: float | None = None
    running_only: bool = False


RULES = (
    MetricRule("coolant_temperature", "Coolant temperature", "°C", high_warning=90, high_critical=100, running_only=True),
    MetricRule("oil_pressure", "Oil pressure", "bar", low_warning=2.0, running_only=True),
    MetricRule("battery_voltage", "Starter battery voltage", "V", low_warning=11.8, high_warning=15.0),
    MetricRule("fuel_level_percent", "Fuel level", "%", low_warning=20.0),
    MetricRule("frequency", "Generator frequency", "Hz", low_warning=48.5, high_warning=51.5, running_only=True),
    MetricRule("load_kw_percent", "Generator load", "%", high_warning=90.0, high_critical=100.0, running_only=True),
)


def _values(samples: Iterable[Any], rule: MetricRule) -> list[float]:
    values: list[float] = []
    for sample in samples:
        if rule.running_only and sample.engine_status != "running":
            continue
        value = getattr(sample, rule.key, None)
        if value is not None:
            values.append(float(value))
    return values


def analyze_generator(panel: Any, samples: list[Any], alarms: list[Any], live: Any | None,
                      last_service: Any | None = None) -> dict[str, Any]:
    """Return a transparent, deterministic report; it is not a failure diagnosis."""
    latest = live or (samples[-1] if samples else None)
    findings: list[dict[str, Any]] = []
    trends: dict[str, dict[str, float]] = {}
    configured_limits = panel.maintenance_limits or {}

    for rule in RULES:
        values = _values(samples, rule)
        if not values and latest is not None:
            value = getattr(latest, rule.key, None)
            if value is not None and (not rule.running_only or getattr(latest, "engine_status", "") == "running"):
                values = [float(value)]
        if not values:
            continue
        trends[rule.key] = {
            "minimum": round(min(values), 2),
            "average": round(mean(values), 2),
            "maximum": round(max(values), 2),
        }
        current = values[-1]
        severity = None
        detail = ""
        low_warning = configured_limits.get(f"{rule.key}_low_warning", rule.low_warning)
        high_warning = configured_limits.get(f"{rule.key}_high_warning", rule.high_warning)
        high_critical = configured_limits.get(f"{rule.key}_high_critical", rule.high_critical)
        if high_critical is not None and max(values) >= high_critical:
            severity = "critical"
            detail = f"Maximum {rule.label.lower()} reached {max(values):.1f} {rule.unit}."
        elif low_warning is not None and min(values) < low_warning:
            severity = "warning"
            detail = f"Minimum {rule.label.lower()} was {min(values):.1f} {rule.unit}."
        elif high_warning is not None and max(values) > high_warning:
            severity = "warning"
            detail = f"Maximum {rule.label.lower()} was {max(values):.1f} {rule.unit}."
        if severity:
            recommendations = {
                "coolant_temperature": "Inspect coolant level, radiator airflow, hoses and thermostat before the next loaded run.",
                "oil_pressure": "Verify oil level and grade, inspect for leaks, and confirm pressure with a calibrated instrument.",
                "battery_voltage": "Inspect terminals and charging system, then load-test the starter battery.",
                "fuel_level_percent": "Refuel and inspect the tank, transfer pump, filters and level sender.",
                "frequency": "Check speed control/governor behavior and confirm the configured nominal frequency.",
                "load_kw_percent": "Review load sharing and capacity; inspect the unit if overload occurred.",
            }
            findings.append({
                "severity": severity,
                "metric": rule.key,
                "title": f"{rule.label} requires attention",
                "detail": detail,
                "recommendation": recommendations[rule.key],
                "current_value": round(current, 2),
                "unit": rule.unit,
            })

    if alarms:
        alarm_names = sorted({a.value or "Unspecified alarm" for a in alarms})
        findings.append({
            "severity": "critical",
            "metric": "alarms",
            "title": f"{len(alarms)} alarm occurrence(s) recorded",
            "detail": ", ".join(alarm_names[:8]),
            "recommendation": "Review the alarm history and close out the underlying causes before relying on the unit.",
            "current_value": len(alarms),
            "unit": "events",
        })

    run_hours = float(getattr(latest, "run_hours", 0.0) or 0.0) if latest else 0.0
    service_interval = float(panel.maintenance_interval_hours or 250.0)
    last_service_hours = float(last_service.run_hours) if last_service else 0.0
    next_service = last_service_hours + service_interval
    if not last_service and run_hours > next_service:
        next_service = ceil(max(run_hours, 1.0) / service_interval) * service_interval
    remaining = max(0.0, next_service - run_hours)
    if remaining <= 25:
        findings.append({
            "severity": "warning" if remaining > 0 else "critical",
            "metric": "run_hours",
            "title": "Routine service interval is approaching" if remaining > 0 else "Routine service interval reached",
            "detail": f"Approximately {remaining:.1f} running hours remain to the {next_service:.0f}-hour interval.",
            "recommendation": "Plan the manufacturer-prescribed service and record completion in the maintenance system.",
            "current_value": round(run_hours, 1),
            "unit": "hours",
        })

    critical = sum(1 for item in findings if item["severity"] == "critical")
    warnings = sum(1 for item in findings if item["severity"] == "warning")
    score = max(0, 100 - critical * 25 - warnings * 10)
    condition = "Attention required" if critical else ("Plan maintenance" if warnings else "No condition warning detected")
    current_readings = dict(getattr(latest, "readings", {}) or {}) if latest else {}
    return {
        "panel_id": panel.id,
        "generator_name": panel.name,
        "controller_profile": panel.controller_profile,
        "condition_score": score,
        "condition": condition,
        "sample_count": len(samples),
        "data_from": samples[0].recorded_at if samples else None,
        "data_to": samples[-1].recorded_at if samples else None,
        "current_readings": current_readings,
        "reading_units": dict(getattr(live, "reading_units", {}) or {}) if live else {},
        "trends": trends,
        "findings": findings,
        "service": {
            "current_run_hours": round(run_hours, 1),
            "service_interval_hours": service_interval,
            "next_service_hours": next_service,
            "hours_remaining": round(remaining, 1),
            "last_service_hours": round(last_service_hours, 1),
        },
        "limitations": [
            "This report supports preventive maintenance planning; it does not replace inspection or the engine manufacturer's service schedule.",
            "Accuracy depends on commissioned controller addresses, scaling and sensor calibration.",
        ],
    }
