import json
from pathlib import Path
import tempfile
import unittest

from runtime import SimulatorRuntime
from simulation.config import load_plant, restore_runtime_state, save_runtime_state


ROOT = Path(__file__).resolve().parents[1]


class ConfigurationTests(unittest.TestCase):
    def test_dynamic_demo_plant_loads_three_generators_grid_solar_and_loads(self):
        plant = load_plant(ROOT / "config/plant.test.json")
        self.assertEqual(len(plant.generators), 3)
        self.assertIsNotNone(plant.grid)
        self.assertIsNotNone(plant.solar)
        self.assertEqual(len(plant.loads), 4)

    def test_runtime_state_round_trip(self):
        plant = load_plant(ROOT / "config/plant.test.json")
        plant.generators[0].energy_kwh = 123.4
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "state.json"
            save_runtime_state(plant, path)
            restored = load_plant(ROOT / "config/plant.test.json")
            self.assertTrue(restore_runtime_state(restored, path))
            self.assertEqual(restored.generators[0].energy_kwh, 123.4)


class ControllerRuntimeTests(unittest.TestCase):
    def test_controller_profile_and_unit_ids_are_loaded(self):
        runtime = SimulatorRuntime(ROOT / "config/plant.test.json", enable_modbus=False)
        self.assertEqual(set(runtime.controllers), {10, 11, 12, 20})
        self.assertEqual(runtime.controllers[10].slave_address, 10)
        self.assertEqual(runtime.controllers[10].model, "DSE8610 MKII")
        self.assertEqual(runtime.controllers[20].model, "DSE8660 MKII")

    def test_page_one_and_six_operational_registers(self):
        runtime = SimulatorRuntime(ROOT / "config/plant.test.json", enable_modbus=False)
        controller = runtime.controllers[10]
        self.assertEqual(controller.read(256, 1), [10])
        self.assertEqual(controller.read(1536, 2), [0, 0])

    def test_mock_parameter_overrides_are_encoded_into_gencomm(self):
        runtime = SimulatorRuntime(ROOT / "config/plant.test.json", enable_modbus=False)
        controller = runtime.controllers[10]
        controller.generator.telemetry_overrides.update(fuel_level_pct=73, oil_temperature_c=91, voltage_l1_n_v=225.5)
        self.assertEqual(controller.read(1027, 1), [73])
        self.assertEqual(controller.read(1026, 1), [91])
        self.assertEqual(controller.read(1032, 2), [0, 2255])

    def test_gencomm_exposes_state_and_breaker_output_for_website(self):
        runtime = SimulatorRuntime(ROOT / "config/plant.test.json", enable_modbus=False)
        controller = runtime.controllers[10]
        generator = controller.generator
        generator.state = generator.state.__class__.ON_LOAD
        generator.breaker.state = generator.breaker.state.__class__.CLOSED
        generator.breaker.feedback_closed = True
        self.assertEqual(controller.read(3 * 256 + 18, 1), [8])
        self.assertTrue(controller.read(13 * 256, 1)[0] & (1 << 8))


if __name__ == "__main__":
    unittest.main()
