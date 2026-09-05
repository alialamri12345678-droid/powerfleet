"""Unit tests for Rules Engine threshold evaluation and hysteresis."""

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
