from pathlib import Path
import tempfile
import unittest

from configuration import ConfigurationError, SiteRepository


ROOT = Path(__file__).resolve().parents[1]


class SiteRepositoryTests(unittest.TestCase):
    def test_create_clone_and_delete_site(self):
        with tempfile.TemporaryDirectory() as directory:
            repository = SiteRepository(directory)
            first = repository.create_site("North Plant", 415, 50)
            clone = repository.clone_site(first, "North Plant Test")
            self.assertEqual(repository.load(first)["voltage_v"], 415)
            self.assertEqual(repository.load(clone)["name"], "North Plant Test")
            repository.delete_site(clone)
            self.assertFalse(clone.exists())

    def test_duplicate_endpoint_and_unit_is_rejected(self):
        repository = SiteRepository(ROOT / "config")
        data = repository.load(ROOT / "config/plant.test.json")
        duplicate = dict(data["generators"][0])
        duplicate["name"] = "DUPLICATE"
        data["generators"].append(duplicate)
        with self.assertRaises(ConfigurationError):
            repository.validate(data, ROOT / "config")

    def test_generator_limit_is_twenty(self):
        repository = SiteRepository(ROOT / "config")
        data = repository.load(ROOT / "config/plant.test.json")
        template = data["generators"][0]
        data["generators"] = []
        for index in range(21):
            item = dict(template)
            item["name"] = f"GEN{index + 1}"
            item["modbus"] = {"host": "0.0.0.0", "port": 5021, "unit_id": index + 1}
            data["generators"].append(item)
        with self.assertRaises(ConfigurationError):
            repository.validate(data, ROOT / "config")


if __name__ == "__main__":
    unittest.main()
