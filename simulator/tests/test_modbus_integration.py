import time
import unittest

from pymodbus.client import ModbusTcpClient

from runtime import SimulatorRuntime
from transports import ModbusTCPServer


class ModbusIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.runtime = SimulatorRuntime("config/plant.test.json", enable_modbus=False)
        cls.server = ModbusTCPServer({10: cls.runtime.controllers[10]}, "127.0.0.1", 15021)
        cls.server.start()
        deadline = time.monotonic() + 3
        while not cls.server.is_running and cls.server.error is None and time.monotonic() < deadline:
            time.sleep(0.02)
        cls.client = ModbusTcpClient("127.0.0.1", port=15021)
        if not cls.client.connect():
            raise RuntimeError(cls.server.error or "test Modbus server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.client.close()

    def test_function_03_reads_gencomm_page_four(self):
        response = self.client.read_holding_registers(1024, count=2, slave=10)
        self.assertFalse(response.isError())
        self.assertEqual(response.registers, [0, 25])

    def test_function_16_executes_valid_complemented_control_key(self):
        key = 35732
        response = self.client.write_registers(4104, [key, (~key) & 0xFFFF], slave=10)
        self.assertFalse(response.isError())
        self.assertTrue(self.runtime.plant.generators[0].commanded_start)

    def test_function_16_rejects_read_only_register_with_exception(self):
        response = self.client.write_registers(1024, [1], slave=10)
        self.assertTrue(response.isError())
        self.assertEqual(response.exception_code, 2)


if __name__ == "__main__":
    unittest.main()
