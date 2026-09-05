"""Unit tests for register_map parsing and lookup."""

from pathlib import Path
import pytest
from app.modbus.register_map import load_register_map, RegisterMap


@pytest.fixture
def register_map():
    path = Path(__file__).resolve().parent.parent / "register_map.yaml"
    return load_register_map(path)


def test_register_map_loading(register_map: RegisterMap):
    assert len(register_map.registers) > 10
    assert len(register_map.poll_groups) >= 3


def test_status_registers_exist(register_map: RegisterMap):
    engine_status = register_map.get("engine_status")
    assert engine_status is not None
    assert engine_status.data_type == "uint16"
    assert engine_status.is_readable
    assert 0 in engine_status.values
    assert engine_status.values[3] == "running"


def test_load_scale_applied(register_map: RegisterMap):
    load_kw = register_map.get("load_kw")
    assert load_kw is not None
    assert load_kw.scale == 0.1
    assert load_kw.unit == "kW"


def test_control_coils_writable(register_map: RegisterMap):
    start_coil = register_map.get("remote_start")
    stop_coil = register_map.get("remote_stop")
    assert start_coil is not None and start_coil.is_coil and start_coil.is_writable
    assert stop_coil is not None and stop_coil.is_coil and stop_coil.is_writable


def test_alarm_words_decoded(register_map: RegisterMap):
    alarm_1 = register_map.get("alarm_word_1")
    assert alarm_1 is not None
    assert len(alarm_1.bits) > 0
    assert alarm_1.bits[0] == "emergency_stop"
