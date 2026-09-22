"""Deterministic, side-effect-free source and generator combination planner.

The controller remains responsible for synchronization, breaker sequencing and
protection. This module only proposes the required generator set.
"""
from __future__ import annotations

from itertools import combinations
from math import isfinite


DEFAULTS = {
    "mode": "legacy", "policy": "priority", "grid_present": False,
    "solar_present": False, "solar_grid_forming": False,
    "solar_curtailable": False, "grid_import_limit_kw": None,
    "max_load_percent": 80.0, "min_load_percent": 0.0,
    "reserve_kw": 0.0, "solar_loss_fraction": 1.0,
    "measurement_max_age_seconds": 15, "transition_dwell_seconds": 120,
    "topology_verified": False,
}


def settings(value):
    return {**DEFAULTS, **(value or {})}


def _fuel_lph(generator, load_kw):
    curve = sorted(generator.get("fuel_curve") or [], key=lambda p: p["load_percent"])
    rated = float(generator["rated_kw"])
    if len(curve) < 2 or rated <= 0:
        return None
    percent = 100 * load_kw / rated
    for left, right in zip(curve, curve[1:]):
        if left["load_percent"] <= percent <= right["load_percent"]:
            span = right["load_percent"] - left["load_percent"]
            if span <= 0:
                return None
            return left["litres_per_hour"] + (percent - left["load_percent"]) * (
                right["litres_per_hour"] - left["litres_per_hour"]) / span
    return None


def plan(config, measurement, generators, current_ids=(), pinned_ids=(), max_parallel=None):
    """Return the least disruptive feasible combination and decision evidence.

    `measurement` is a commissioned, fresh site snapshot validated by the caller.
    `generators` contains rated capacity and eligibility derived from current
    controller state. All power quantities are in kW.
    """
    cfg = settings(config)
    demand = float(measurement["load_kw"])
    solar = float(measurement.get("solar_kw", 0) or 0) if cfg["solar_present"] else 0.0
    grid = bool(cfg["grid_present"] and measurement.get("grid_connected"))
    if not all(isfinite(v) and v >= 0 for v in (demand, solar)):
        return {"status": "invalid_measurement", "target_ids": [], "reasons": ["Invalid site power reading"]}
    if solar > demand and not cfg["solar_curtailable"]:
        return {"status": "unsafe_source_balance", "target_ids": [],
                "reasons": ["Solar output exceeds site demand without confirmed curtailment"]}
    if solar and not grid and not cfg["solar_grid_forming"] and not measurement.get("bus_energized"):
        solar = 0.0
    import_limit = cfg["grid_import_limit_kw"]
    grid_capacity = (float(import_limit) if import_limit is not None else demand) if grid else 0.0
    if not isfinite(grid_capacity) or grid_capacity < 0:
        return {"status": "invalid_configuration", "target_ids": [], "reasons": ["Invalid grid import limit"]}
    normal_need = max(0.0, demand - solar - grid_capacity)
    solar_drop = solar * float(cfg["solar_loss_fraction"])
    secure_need = max(normal_need, demand - max(0.0, solar - solar_drop) - grid_capacity)
    grid_draw = min(grid_capacity, max(0.0, demand - solar)) if grid else 0.0
    grid_headroom = max(0.0, grid_capacity - grid_draw) if grid else 0.0
    required = max(0.0, secure_need + float(cfg["reserve_kw"]) - grid_headroom)
    if not isfinite(required) or required < 0:
        return {"status": "invalid_configuration", "target_ids": [], "reasons": ["Invalid reserve setting"]}
    current = set(current_ids)
    pinned = set(pinned_ids)
    eligible = [g for g in generators if g.get("eligible") and float(g.get("rated_kw", 0)) > 0]
    eligible.sort(key=lambda g: (g.get("priority", 100), g["id"]))
    if pinned - {g["id"] for g in eligible}:
        return {"status": "pinned_unavailable", "target_ids": sorted(current),
                "reasons": ["A required generator is unavailable"]}
    if len(eligible) > 16:
        return {"status": "fleet_limit", "target_ids": sorted(current),
                "reasons": ["Adaptive planning supports at most 16 generators per site"]}
    candidates = []
    limit = max_parallel or len(eligible)
    for count in range(len(eligible) + 1):
        if count > limit:
            break
        if count == 0 and not grid and measurement.get("bus_energized") and not cfg["solar_grid_forming"]:
            continue
        for group in combinations(eligible, count):
            ids = {g["id"] for g in group}
            if not pinned <= ids:
                continue
            capacity = sum(float(g["rated_kw"]) * float(g.get("max_load_percent", cfg["max_load_percent"])) / 100 for g in group)
            minimum = sum(float(g["rated_kw"]) * float(g.get("min_load_percent", cfg["min_load_percent"])) / 100 for g in group)
            if capacity + 1e-6 < required:
                continue
            # Grid import may be reduced, and measured solar may be curtailed
            # only when the installation explicitly supports that control.
            maximum_gen_load = demand - (0 if cfg["solar_curtailable"] else solar)
            if minimum > maximum_gen_load + 1e-6:
                continue
            starts = len(ids - current)
            stops = len(current - ids)
            rank = sum((index + 1) for index, g in enumerate(eligible) if g["id"] in ids)
            last_rank = max((index + 1 for index, g in enumerate(eligible) if g["id"] in ids), default=0)
            excess = capacity - required
            policy = cfg["policy"]
            if policy == "priority":
                score = (last_rank, count, rank, starts + stops)
            elif policy == "economy":
                output = max(normal_need, minimum)
                total_capacity = sum(float(g["rated_kw"]) for g in group)
                fuel = [_fuel_lph(g, output * float(g["rated_kw"]) / total_capacity) for g in group] if group else []
                score = (sum(fuel) if all(v is not None for v in fuel) else float("inf"),
                         starts + stops, excess, rank)
            else:
                score = (excess + 20 * starts + 10 * stops, count, rank)
            candidates.append((score, group, capacity, minimum))
    if not candidates:
        return {"status": "insufficient_capacity", "target_ids": sorted(current),
                "required_kw": round(required, 2), "reasons": ["No permitted generator combination covers demand and reserve"]}
    _, group, capacity, minimum = min(candidates, key=lambda item: item[0])
    target = [g["id"] for g in group]
    return {"status": "ready", "target_ids": target, "start_ids": sorted(set(target) - current),
            "release_ids": sorted(current - set(target)), "normal_generator_kw": round(normal_need, 2),
            "required_kw": round(required, 2), "usable_capacity_kw": round(capacity, 2),
            "minimum_loading_kw": round(minimum, 2), "grid_connected": grid,
            "solar_kw": round(solar, 2), "reasons": [f"{cfg['policy']} policy selected {len(group)} generator(s)"]}
