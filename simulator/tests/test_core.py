import unittest
from pathlib import Path

from simulator_core.electrical import calculate_three_phase, calculate_three_phase_pq
from simulator_core.gencomm import (
    DataType, GenCommRegisterMap, IllegalAddress, IllegalWrite, RegisterAccess,
    RegisterDefinition, Sentinel, absolute_address, decode_value, encode_value,
    sentinel_words, split_address,
)
from simulator_core.profiles import load_controller_profile, load_generator_profile


ROOT = Path(__file__).resolve().parents[1]


class AddressTests(unittest.TestCase):
    def test_page_four_offset_zero(self):
        self.assertEqual(absolute_address(4, 0), 1024)
        self.assertEqual(split_address(1024), (4, 0))


class CodecTests(unittest.TestCase):
    def test_integer_types_and_scaling(self):
        cases = [
            (DataType.UINT16, 123.4, 0.1, [1234]),
            (DataType.INT16, -50, 1, [0xFFCE]),
            (DataType.UINT32, 70000, 1, [1, 4464]),
            (DataType.INT32, -70000, 1, [0xFFFE, 0xEE90]),
        ]
        for dtype, value, scale, expected in cases:
            definition = RegisterDefinition(4, 0, "value", dtype, scale=scale)
            self.assertEqual(encode_value(definition, value), expected)
            self.assertAlmostEqual(decode_value(definition, expected), value)

    def test_gencomm_word_order_is_most_significant_word_first(self):
        definition = RegisterDefinition(4, 8, "voltage", DataType.UINT32, scale=0.1)
        self.assertEqual(encode_value(definition, 480.0), [0, 4800])

    def test_sentinel_values_match_supplied_gencomm_table(self):
        self.assertEqual(sentinel_words(DataType.UINT16, Sentinel.UNIMPLEMENTED), [0xFFFF])
        self.assertEqual(sentinel_words(DataType.INT16, Sentinel.BAD_DATA), [0x7FFB])
        self.assertEqual(sentinel_words(DataType.UINT32, Sentinel.UNDER_RANGE), [0xFFFF, 0xFFFD])
        self.assertEqual(sentinel_words(DataType.INT32, Sentinel.TRANSDUCER_FAULT), [0x7FFF, 0xFFFC])

    def test_strings_have_no_null_terminator(self):
        ascii_def = RegisterDefinition(20, 0, "maker", DataType.ASCII, words=3)
        unicode_def = RegisterDefinition(24, 0, "identity", DataType.UNICODE, words=4)
        self.assertEqual(encode_value(ascii_def, "DSE"), [0x4453, 0x4520, 0x2020])
        self.assertEqual(decode_value(unicode_def, encode_value(unicode_def, "GEN1")), "GEN1")


class RegisterMapTests(unittest.TestCase):
    def setUp(self):
        self.command = []
        self.read_only = RegisterDefinition(4, 0, "oil pressure", DataType.UINT16, getter=lambda: 400)
        self.command_def = RegisterDefinition(
            16, 8, "system control key", DataType.UINT16,
            access=RegisterAccess.WRITE_ONLY, setter=self.command.append,
        )
        self.map = GenCommRegisterMap([self.read_only, self.command_def])

    def test_function_03_style_read_and_unsupported_sentinel(self):
        self.assertEqual(self.map.read(1024, 2), [400, 0xFFFF])

    def test_function_16_style_write(self):
        self.map.write(4104, [35700])
        self.assertEqual(self.command, [35700])

    def test_read_only_write_rejected_atomically(self):
        with self.assertRaises(IllegalWrite):
            self.map.write(1024, [1])
        self.assertEqual(self.command, [])

    def test_partial_32_bit_read_rejected(self):
        register_map = GenCommRegisterMap([RegisterDefinition(4, 8, "voltage", DataType.UINT32, getter=lambda: 480)])
        with self.assertRaises(IllegalAddress):
            register_map.read(1032, 1)


class ElectricalTests(unittest.TestCase):
    def test_balanced_three_phase_relationships(self):
        result = calculate_three_phase(400, 480, 0.8)
        self.assertAlmostEqual(result.apparent_power_kva, 500)
        self.assertAlmostEqual(result.reactive_power_kvar, 300)
        self.assertAlmostEqual(result.current_a, 601.4065, places=3)

    def test_stopped_source_has_zero_current(self):
        self.assertEqual(calculate_three_phase(0, 0, 0.8).current_a, 0)

    def test_active_and_reactive_power_produce_consistent_pf(self):
        result = calculate_three_phase_pq(400, 300, 400)
        self.assertEqual(result.apparent_power_kva, 500)
        self.assertEqual(result.power_factor, 0.8)


class ProfileTests(unittest.TestCase):
    def test_demo_generator_values_are_not_claimed_as_manufacturer_data(self):
        profile = load_generator_profile(ROOT / "config/equipment/generators/demo_500kw.json")
        self.assertEqual(profile.prime_power_kw.value, 500)
        self.assertEqual(profile.prime_power_kw.classification, "simulation_parameter")
        self.assertEqual(profile.engine_model.classification, "unknown")

    def test_controller_capabilities_are_data_driven(self):
        profile = load_controller_profile(ROOT / "config/controllers/dse8610_mkii_demo.json")
        self.assertIn(4, profile.supported_pages)
        self.assertIn("synchronization", profile.supported_features)


if __name__ == "__main__":
    unittest.main()
