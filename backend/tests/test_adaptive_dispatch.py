"""Operational cases for the optional, isolated adaptive planner."""
from datetime import datetime, timedelta, timezone

import pytest

from app.modbus.gateway import ModbusGateway
from app.rules.adaptive_planner import plan


def fleet():
    return [
        {"id": "small", "rated_kw": 100, "priority": 2, "eligible": True},
        {"id": "medium", "rated_kw": 150, "priority": 1, "eligible": True},
        {"id": "large", "rated_kw": 500, "priority": 3, "eligible": True},
    ]


def test_size_aware_planning_selects_appropriate_combinations():
    cfg = {"policy": "capacity", "max_load_percent": 80, "reserve_kw": 30}
    assert plan(cfg, {"load_kw": 90}, fleet())["target_ids"] == ["medium"]
    assert set(plan(cfg, {"load_kw": 160}, fleet())["target_ids"]) == {"small", "medium"}
    assert plan(cfg, {"load_kw": 320}, fleet())["target_ids"] == ["large"]
    assert set(plan({**cfg, "policy": "priority"}, {"load_kw": 160}, fleet())["target_ids"]) == {"small", "medium"}


def test_grid_and_solar_require_their_own_verified_capabilities():
    cfg = {"grid_present": True, "solar_present": True, "grid_import_limit_kw": 200,
           "solar_loss_fraction": 1, "reserve_kw": 20, "policy": "capacity"}
    grid = plan(cfg, {"load_kw": 180, "solar_kw": 70, "grid_connected": True}, fleet())
    assert grid["target_ids"] == []
    island = plan(cfg, {"load_kw": 180, "solar_kw": 70, "grid_connected": False,
                        "bus_energized": True}, fleet())
    assert island["required_kw"] == 200
    assert set(island["target_ids"]) == {"small", "medium"}
    unsafe = plan({**cfg, "solar_curtailable": False},
                  {"load_kw": 60, "solar_kw": 70, "grid_connected": False}, fleet())
    assert unsafe["status"] == "unsafe_source_balance"


def test_max_parallel_and_pinned_units_are_hard_constraints():
    result = plan({"max_load_percent": 80, "reserve_kw": 30}, {"load_kw": 160}, fleet(),
                  pinned_ids={"small"}, max_parallel=1)
    assert result["status"] == "insufficient_capacity"
    unavailable = plan({}, {"load_kw": 40}, fleet(), pinned_ids={"missing"})
    assert unavailable["status"] == "pinned_unavailable"


@pytest.mark.asyncio
async def test_adaptive_stop_needs_confirmed_replacement_and_fresh_context():
    gateway = ModbusGateway()
    gateway.add_panel("p1", "site1", "Old", "tcp", "127.0.0.1:5020", 1, rated_kw=500)
    gateway.add_panel("p2", "site1", "New", "tcp", "127.0.0.1:5020", 2, rated_kw=150)
    for state in gateway.states.values():
        state.engine_status = "running"
        state.is_reachable = True
        state.mark_poll_success()
    context = {"checked_at": datetime.now(timezone.utc), "site_id": "site1",
               "source_fresh": True, "target_ids": ["p2"], "required_kw": 100,
               "max_load_percent": 80}
    allowed, reason = await gateway._validate_safe_to_stop("p1", "adaptive_dispatch", context)
    assert not allowed and "not confirmed" in reason
    gateway.states["p2"].generator_breaker = True
    gateway.states["p2"].reading_quality["generator_breaker"] = "good"
    assert (await gateway._validate_safe_to_stop("p1", "adaptive_dispatch", context))[0]
    context["checked_at"] = datetime.now(timezone.utc) - timedelta(seconds=10)
    assert not (await gateway._validate_safe_to_stop("p1", "adaptive_dispatch", context))[0]
