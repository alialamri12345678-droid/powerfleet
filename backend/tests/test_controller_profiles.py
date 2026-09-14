from pathlib import Path

from app.controllers import create_adapter, list_controller_profiles
from app.modbus.register_map import load_register_map
from app.modbus.panel_state import PanelState


def test_profiles_include_document_families_without_redundant_8620():
    ids = {profile["id"] for profile in list_controller_profiles()}
    assert "dse8620_mkii" not in ids
    assert "dse_86xx_mkii" in ids
    assert "dse_73xx_mkii" in ids
    assert "dse_87xx_88xx" in ids


def test_gencomm_command_is_atomic_key_and_ones_complement():
    register_map = load_register_map(Path(__file__).resolve().parent.parent / "register_map.yaml")
    adapter = create_adapter("dse_86xx_mkii", register_map)
    command = adapter.command_write("remote_start")
    assert command.address == 16 * 256 + 8
    assert command.values == (35732, (~35732) & 0xFFFF)


def test_adapter_normalizes_generator_state_breaker_and_sync():
    register_map = load_register_map(Path(__file__).resolve().parent.parent / "register_map.yaml")
    adapter = create_adapter("dse_86xx_mkii", register_map)
    state = PanelState("panel-1", "GEN1")
    adapter.apply_reading(state, register_map.get("engine_speed"), 1500)
    adapter.apply_reading(state, register_map.get("generator_state"), 8)
    adapter.apply_reading(state, register_map.get("standard_digital_outputs"), 1 << 8)
    assert state.engine_status == "running"
    assert state.generator_status == "on_load"
    assert state.generator_breaker is True
    assert state.sync_status is True
