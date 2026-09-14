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


def test_gencomm_core_status_registers_exist(register_map: RegisterMap):
    assert register_map.version == "gencomm-2.236-mf-2022-05-26"
    assert register_map.get("engine_speed").address == 4 * 256 + 6
    assert register_map.get("control_mode").address == 3 * 256 + 4
    assert register_map.get("generator_state").address == 3 * 256 + 18
    assert register_map.get("standard_digital_outputs").address == 13 * 256


def test_load_scale_applied(register_map: RegisterMap):
    load_kw = register_map.get("load_kw")
    assert load_kw is not None
    assert load_kw.address == 6 * 256
    assert load_kw.data_type == "int32"
    assert load_kw.scale == 0.001
    assert load_kw.unit == "kW"


def test_control_key_pair_is_writable_holding_registers(register_map: RegisterMap):
    key = register_map.get("system_control_key")
    complement = register_map.get("system_control_key_complement")
    assert key.address == 16 * 256 + 8 and key.is_writable and not key.is_coil
    assert complement.address == key.address + 1 and complement.is_writable


def test_alarm_conditions_are_packed_nibbles(register_map: RegisterMap):
    alarm_1 = register_map.get("alarm_condition_01")
    assert alarm_1 is not None
    assert alarm_1.address == 8 * 256 + 1
    assert alarm_1.fields[0] == {"shift": 12, "mask": 15, "name": "emergency_stop"}


def test_maintenance_readings_include_fuel_level(register_map: RegisterMap):
    fuel = register_map.get("fuel_level_percent")
    assert fuel is not None and fuel.is_readable
    assert fuel.address == 4 * 256 + 3
    assert fuel.unit == "%"


def test_profile_filtering_removes_unsupported_accumulators(register_map: RegisterMap):
    assert register_map.for_profile("dse_3xx").get("run_hours") is None
    assert register_map.for_profile("dse_86xx_mkii").get("run_hours") is not None
