"""Unit tests for Rules Engine threshold evaluation and hysteresis."""

from datetime import datetime, timedelta, timezone

import pytest
from app.modbus.gateway import ModbusGateway
from app.modbus.panel_state import PanelState
from app.rules.engine import RulesEngine


@pytest.mark.asyncio
async def test_threshold_hysteresis_rule():
    gateway = ModbusGateway()
    # Mock panels
    gateway.add_panel("p1", "site1", "Gen 1", "tcp", "127.0.0.1:5020", 1)
    gateway.add_panel("p2", "site1", "Gen 2", "tcp", "127.0.0.1:5020", 2)

    import time
    s1 = gateway.states["p1"]
    s1.is_reachable = True
    s1.engine_status = "running"
    s1.load_kw_percent = 80.0  # Above 70% threshold
    s1.last_poll_time = time.monotonic()

    s2 = gateway.states["p2"]
    s2.is_reachable = True
    s2.engine_status = "stopped"
    s2.run_hours = 120.0
    s2.last_poll_time = time.monotonic()

    engine = RulesEngine(gateway)

    # Backup pick should select p2 (fewest run hours)
    backup = await engine._pick_backup(["p2"])
    assert backup == "p2"


@pytest.mark.asyncio
async def test_threshold_no_action_when_within_deadband():
    gateway = ModbusGateway()
    gateway.add_panel("p1", "site1", "Gen 1", "tcp", "127.0.0.1:5020", 1)

    s1 = gateway.states["p1"]
    s1.is_reachable = True
    s1.engine_status = "running"
    s1.load_kw_percent = 60.0  # Between 50% stop and 70% start

    engine = RulesEngine(gateway)
    # Shouldn't trigger anything
    assert len(engine._threshold_started) == 0


@pytest.mark.asyncio
async def test_stop_is_blocked_when_remaining_capacity_is_insufficient():
    gateway = ModbusGateway()
    gateway.add_panel("p1", "site1", "Gen 1", "tcp", "127.0.0.1:5020", 1, rated_kw=500)
    gateway.add_panel("p2", "site1", "Gen 2", "tcp", "127.0.0.1:5020", 2, rated_kw=100)

    gateway.states["p1"].is_reachable = True
    gateway.states["p1"].engine_status = "running"
    gateway.states["p1"].load_kw = 350
    gateway.states["p2"].is_reachable = True
    gateway.states["p2"].engine_status = "running"
    gateway.states["p2"].load_kw = 50

    allowed, reason = await gateway._validate_safe_to_stop("p1", triggered_by="manual")

    assert allowed is False
    assert "exceed remaining capacity" in reason


@pytest.mark.asyncio
async def test_force_stop_override_bypasses_capacity_guard():
    gateway = ModbusGateway()
    gateway.add_panel("p1", "site1", "Gen 1", "tcp", "127.0.0.1:5020", 1, rated_kw=500)
    gateway.states["p1"].is_reachable = True
    gateway.states["p1"].engine_status = "running"
    gateway.states["p1"].load_kw = 350

    allowed, _ = await gateway._validate_safe_to_stop("p1", triggered_by="override")

    assert allowed is True


@pytest.mark.asyncio
async def test_overlapping_per_generator_threshold_uses_priority_selected_backup():
    gateway = ModbusGateway()
    gateway.add_panel("p1", "site1", "Gen 1", "tcp", "127.0.0.1:5020", 1, rated_kw=500)
    gateway.add_panel("p2", "site1", "Gen 2", "tcp", "127.0.0.1:5020", 2, rated_kw=500)
    gateway.states["p1"].is_reachable = True
    gateway.states["p1"].engine_status = "running"
    gateway.states["p1"].load_kw = 364
    gateway.states["p1"].load_kw_percent = 72.8
    gateway.states["p2"].is_reachable = True
    gateway.states["p2"].engine_status = "stopped"

    engine = RulesEngine(gateway)

    async def get_panel(panel_id):
        return {"rated_kw": 500, "priority": 1 if panel_id == "p1" else 2,
                "lead_rotation_order": 100, "maintenance_mode": False}

    async def get_starts(site_id):
        return [{"panel_id": "p2", "start_pct": 31, "priority_order": 2}]

    async def get_releases(site_id):
        return [{"panel_id": "p2", "release_pct": 50, "priority_order": 2}]

    engine._get_panel = get_panel
    engine._get_start_thresholds = get_starts
    engine._get_release_thresholds = get_releases
    await engine._evaluate_single_threshold({
        "site_id": "site1", "start_pct": 70, "stop_pct": 50, "dwell_seconds": 60,
    })

    assert "p2" in engine._threshold_started
    assert engine._threshold_wants["p2"] == "RUNNING"


@pytest.mark.asyncio
async def test_release_intent_is_retained_until_stopped_feedback():
    gateway = ModbusGateway()
    for panel_id in ("p1", "p2"):
        gateway.add_panel(panel_id, "site1", panel_id, "tcp", "127.0.0.1:5020", 1, rated_kw=500)
        gateway.states[panel_id].is_reachable = True
        gateway.states[panel_id].engine_status = "running"
        gateway.states[panel_id].load_kw = 50
        gateway.states[panel_id].load_kw_percent = 10

    engine = RulesEngine(gateway)
    started_at = datetime.now(timezone.utc) - timedelta(minutes=5)
    engine._threshold_started["p2"] = started_at
    engine._threshold_wants["p2"] = "RUNNING"

    async def get_panel(panel_id):
        return {"rated_kw": 500}

    async def get_releases(site_id):
        return [{"panel_id": "p2", "release_pct": 50, "priority_order": 2}]

    engine._get_panel = get_panel
    engine._get_release_thresholds = get_releases
    await engine._evaluate_single_threshold({
        "site_id": "site1", "start_pct": 70, "stop_pct": 50, "dwell_seconds": 60,
    })

    assert engine._threshold_started["p2"] == started_at
    assert engine._threshold_wants["p2"] == "STOPPED"


def test_startup_adopts_running_unscheduled_panel_for_release():
    gateway = ModbusGateway()
    for panel_id in ("scheduled", "backup", "stopped"):
        gateway.add_panel(panel_id, "site1", panel_id, "tcp", "127.0.0.1:5020", 1)
        gateway.states[panel_id].is_reachable = True
    gateway.states["scheduled"].engine_status = "running"
    gateway.states["backup"].engine_status = "running"
    gateway.states["stopped"].engine_status = "stopped"

    engine = RulesEngine(gateway)
    engine._schedule_wants["scheduled"] = "RUNNING"
    engine._adopt_unmanaged_running_panels()

    assert "scheduled" not in engine._threshold_started
    assert "stopped" not in engine._threshold_started
    assert "backup" in engine._threshold_started
    assert engine._threshold_wants["backup"] == "RUNNING"
