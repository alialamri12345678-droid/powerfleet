"""Unit tests for the CooldownManager rate-limiter."""

import time
import pytest
from app.modbus.cooldown import CooldownManager


def test_initial_start_allowed():
    cd = CooldownManager(min_run_seconds=10, min_rest_seconds=10)
    res = cd.check_start("panel_1")
    assert res.allowed is True


def test_stop_blocked_during_run_cooldown():
    cd = CooldownManager(min_run_seconds=30, min_rest_seconds=30)
    cd.record_start("panel_1")

    # Immediately check stop
    res = cd.check_stop("panel_1")
    assert res.allowed is False
    assert "Run cooldown active" in res.reason
    assert res.retry_after_seconds > 0


def test_start_blocked_during_rest_cooldown():
    cd = CooldownManager(min_run_seconds=30, min_rest_seconds=30)
    cd.record_stop("panel_1")

    # Immediately check start
    res = cd.check_start("panel_1")
    assert res.allowed is False
    assert "Rest cooldown active" in res.reason
    assert res.retry_after_seconds > 0


def test_different_panels_independent():
    cd = CooldownManager(min_run_seconds=30, min_rest_seconds=30)
    cd.record_start("panel_1")

    # panel_2 should still be allowed to stop or start
    res = cd.check_stop("panel_2")
    assert res.allowed is True
