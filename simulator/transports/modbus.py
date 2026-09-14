"""pymodbus adapter for controller emulators."""

from __future__ import annotations

import asyncio
import logging
import threading

from pymodbus.datastore import ModbusSequentialDataBlock, ModbusServerContext, ModbusSlaveContext
from pymodbus.server import StartAsyncSerialServer, StartAsyncTcpServer

from controllers.dse import DSEControllerEmulator

logger = logging.getLogger(__name__)


class GenCommDataBlock(ModbusSequentialDataBlock):
    def __init__(self, controller: DSEControllerEmulator):
        # ModbusSlaveContext adds one for traditional 4xxxx notation. Starting
        # the block at one and translating here preserves GenComm's zero-based
        # wire addresses.
        super().__init__(1, [0] * 65536)
        self.controller = controller

    def getValues(self, address, count=1):
        try:
            return self.controller.read(address - 1, count)
        except Exception:
            self.controller.diagnostics.exception_count += 1
            raise

    def setValues(self, address, values):
        try:
            self.controller.write(address - 1, list(values))
        except Exception:
            self.controller.diagnostics.exception_count += 1
            raise


class GenCommSlaveContext(ModbusSlaveContext):
    """Zero-based context with protocol validation that returns Modbus exceptions."""

    def __init__(self, controller: DSEControllerEmulator):
        super().__init__(
            di=ModbusSequentialDataBlock(0, [0]), co=ModbusSequentialDataBlock(0, [0]),
            hr=GenCommDataBlock(controller), ir=ModbusSequentialDataBlock(0, [0]),
        )
        self.controller = controller

    def validate(self, fc_as_hex, address, count=1):
        if fc_as_hex == 3:
            return self.controller.registers.validates_read(address, count)
        if fc_as_hex == 16:
            return self.controller.registers.validates_write(address, count)
        return False

    def getValues(self, fc_as_hex, address, count=1):
        return self.controller.read(address, count)

    def setValues(self, fc_as_hex, address, values):
        self.controller.write(address, list(values))


class ModbusTCPServer:
    def __init__(self, controllers: dict[int, DSEControllerEmulator], host: str = "0.0.0.0", port: int = 5021):
        self.controllers, self.host, self.port = controllers, host, port
        self.is_running = False
        self.error: str | None = None
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, daemon=True, name=f"modbus-{self.port}")
        self._thread.start()

    def _run(self) -> None:
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._serve())
        except Exception as exc:
            self.error = str(exc)
            logger.exception("Modbus TCP server failed on %s:%s", self.host, self.port)

    async def _serve(self) -> None:
        slaves = {}
        for unit_id, controller in self.controllers.items():
            slaves[unit_id] = GenCommSlaveContext(controller)
        context = ModbusServerContext(slaves=slaves, single=False)
        self.is_running = True
        logger.info("GenComm Modbus TCP listening on %s:%s (%s)", self.host, self.port, sorted(self.controllers))
        await StartAsyncTcpServer(context=context, address=(self.host, self.port))


class ModbusRTUServer(ModbusTCPServer):
    """RTU transport for a configured real or virtual serial port."""

    def __init__(self, controllers: dict[int, DSEControllerEmulator], serial_port: str, baudrate: int = 19200, bytesize: int = 8, parity: str = "N", stopbits: int = 1):
        super().__init__(controllers, serial_port, 0)
        self.serial_port, self.baudrate = serial_port, baudrate
        self.bytesize, self.parity, self.stopbits = bytesize, parity, stopbits

    async def _serve(self) -> None:
        slaves = {}
        for unit_id, controller in self.controllers.items():
            slaves[unit_id] = GenCommSlaveContext(controller)
        context = ModbusServerContext(slaves=slaves, single=False)
        self.is_running = True
        logger.info("GenComm Modbus RTU listening on %s (%s)", self.serial_port, sorted(self.controllers))
        await StartAsyncSerialServer(
            context=context, port=self.serial_port, baudrate=self.baudrate,
            bytesize=self.bytesize, parity=self.parity, stopbits=self.stopbits,
        )
