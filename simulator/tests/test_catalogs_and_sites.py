import json
import logging
from pathlib import Path
import shutil
import tempfile
import unittest

from configuration import SiteRepository
from runtime import SimulatorRuntime
from simulator_core.profiles import load_controller_profile_reference, load_generator_profile_reference


ROOT = Path(__file__).resolve().parents[1]


class CatalogAndSiteLifecycleTests(unittest.TestCase):
    def tearDown(self):
        root = logging.getLogger()
        for handler in tuple(root.handlers):
            if getattr(handler, "plant_simulator_handler", False):
                root.removeHandler(handler)
                handler.close()

    def test_catalog_contains_ten_adjustable_manufacturers(self):
        raw = json.loads((ROOT / "config/catalogs/generator_manufacturers.json").read_text(encoding="utf-8"))
        self.assertEqual(len(raw["profiles"]), 10)
        profile = load_generator_profile_reference(ROOT / "config", "catalog:generator:caterpillar_adjustable")
        self.assertEqual(profile.manufacturer.classification, "manufacturer_spec")
        self.assertEqual(profile.prime_power_kw.classification, "simulation_parameter")

    def test_dse_catalog_has_current_and_common_legacy_models(self):
        raw = json.loads((ROOT / "config/catalogs/dse_controllers.json").read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(raw["profiles"]), 30)
        profile = load_controller_profile_reference(ROOT / "config", "catalog:controller:dse8610_mkii")
        self.assertIn("synchronization", profile.supported_features)

    def test_two_sites_have_isolated_state_logs_and_topology(self):
        with tempfile.TemporaryDirectory() as directory:
            config_root = Path(directory) / "config"
            shutil.copytree(ROOT / "config/catalogs", config_root / "catalogs")
            repository = SiteRepository(config_root)
            north = repository.create_site("North")
            north_data = repository.load(north)
            repository.add_generator(north_data, "N-GEN1", "catalog:generator:cummins_adjustable", "catalog:controller:dse8610_mkii", "127.0.0.1", 15021, 10, 900)
            repository.add_generator(north_data, "N-GEN2", "catalog:generator:mtu_adjustable", "catalog:controller:dse7320_mkii", "127.0.0.1", 15022, 10, 450)
            repository.save(north, north_data)
            south = repository.create_site("South")
            south_data = repository.load(south)
            repository.add_generator(south_data, "S-GEN1", "catalog:generator:yanmar_adjustable", "catalog:controller:dse6110_mkiii", "127.0.0.1", 15031, 10, 250)
            repository.save(south, south_data)

            north_runtime = SimulatorRuntime(north, enable_modbus=False)
            self.assertEqual([g.name for g in north_runtime.plant.generators], ["N-GEN1", "N-GEN2"])
            self.assertEqual(len(north_runtime.controller_devices), 2)
            self.assertEqual(len(north_runtime.controllers), 1)  # Same unit ID is valid on distinct TCP endpoints.
            north_runtime.save()
            south_runtime = SimulatorRuntime(south, enable_modbus=False)
            self.assertEqual([g.name for g in south_runtime.plant.generators], ["S-GEN1"])
            south_runtime.save()

            self.assertNotEqual(north_runtime.site_data_dir, south_runtime.site_data_dir)
            self.assertTrue(north_runtime.state_path.exists())
            self.assertTrue(south_runtime.state_path.exists())
            self.assertTrue((north_runtime.site_data_dir / "logs/simulator.log").exists())
            self.assertTrue((south_runtime.site_data_dir / "logs/simulator.log").exists())
            for handler in tuple(logging.getLogger().handlers):
                if getattr(handler, "plant_simulator_handler", False):
                    logging.getLogger().removeHandler(handler)
                    handler.close()


if __name__ == "__main__":
    unittest.main()
