"""Modbus transport abstraction — RTU and TCP implementations.

Each panel can be configured to use either RS485/RTU or TCP/IP.
The gateway code only ever calls the Transport protocol, never
pymodbus clients directly.
"""

from __future__ import annotations

import asyncio
import logging
from abc import ABC, abstractmethod
from typing import Any

from pymodbus.client import AsyncModbusSerialClient, AsyncModbusTcpClient
from pymodbus.exceptions import ModbusException

logger = logging.getLogger(__name__)


class TransportError(Exception):
    """Raised when a Modbus read/write fails at the transport level."""
    pass


class ModbusTransport(ABC):
    """Protocol for Modbus communication with a single panel."""

    @abstractmethod
    async def connect(self) -> None:
        """Establish the underlying connection."""

    @abstractmethod
    async def disconnect(self) -> None:
        """Close the connection cleanly."""

    @abstractmethod
    async def read_holding_registers(
        self, address: int, count: int, unit: int
    ) -> list[int]:
        """Read holding registers and return raw 16-bit values."""

    @abstractmethod
    async def read_coils(
        self, address: int, count: int, unit: int
    ) -> list[bool]:
        """Read coil status."""

    @abstractmethod
    async def write_coil(
        self, address: int, value: bool, unit: int
    ) -> None:
        """Write a single coil."""

    @abstractmethod
    async def write_register(
        self, address: int, value: int, unit: int
    ) -> None:
        """Write a single holding register."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Whether the transport has an active connection."""
        
    async def _with_retry(self, operation_name: str, func, *args, **kwargs) -> Any:
        """Execute a Modbus operation with up to 2 retries on failure."""
        max_attempts = 3
        last_error = None
        
        for attempt in range(1, max_attempts + 1):
            try:
                self._check_connected()
                return await func(*args, **kwargs)
            except ModbusException as exc:
                last_error = exc
                logger.warning(
                    "Modbus %s failed on attempt %d/%d: %s",
                    operation_name, attempt, max_attempts, exc
                )
                if attempt < max_attempts:
                    await asyncio.sleep(0.5 * attempt)
            except TransportError as exc:
                # E.g. check_response failed
                last_error = exc
                logger.warning(
                    "Transport error in %s on attempt %d/%d: %s",
                    operation_name, attempt, max_attempts, exc
                )
                if attempt < max_attempts:
                    await asyncio.sleep(0.5 * attempt)
                    
        raise TransportError(f"Operation {operation_name} failed after {max_attempts} attempts. Last error: {last_error}")

    def _check_connected(self):
        if not self.is_connected:
            raise TransportError("Transport not connected")

    def _check_response(self, resp: Any, context: str):
        if hasattr(resp, "isError") and resp.isError():
            raise TransportError(f"Modbus error in {context}: {resp}")


class TCPTransport(ModbusTransport):
    """Modbus TCP transport wrapping pymodbus AsyncModbusTcpClient."""

    def __init__(self, host: str, port: int = 502, timeout: float = 3.0):
        self._host = host
        self._port = port
        self._timeout = timeout
        self._client: AsyncModbusTcpClient | None = None

    async def connect(self) -> None:
        self._client = AsyncModbusTcpClient(
            host=self._host,
            port=self._port,
            timeout=self._timeout,
        )
        connected = await self._client.connect()
        if not connected:
            raise TransportError(
                f"Failed to connect to TCP {self._host}:{self._port}"
            )
        logger.info("TCP connected to %s:%d", self._host, self._port)

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def read_holding_registers(
        self, address: int, count: int, unit: int
    ) -> list[int]:
        async def _do_read():
            resp = await self._client.read_holding_registers(
                address=address, count=count, slave=unit
            )
            self._check_response(resp, f"read_holding_registers({address}, {count})")
            return list(resp.registers)
            
        return await self._with_retry("read_holding_registers", _do_read)

    async def read_coils(
        self, address: int, count: int, unit: int
    ) -> list[bool]:
        async def _do_read():
            resp = await self._client.read_coils(
                address=address, count=count, slave=unit
            )
            self._check_response(resp, f"read_coils({address}, {count})")
            return list(resp.bits[:count])
            
        return await self._with_retry("read_coils", _do_read)

    async def write_coil(self, address: int, value: bool, unit: int) -> None:
        async def _do_write():
            resp = await self._client.write_coil(
                address=address, value=value, slave=unit
            )
            self._check_response(resp, f"write_coil({address}, {value})")
            
        await self._with_retry("write_coil", _do_write)

    async def write_register(
        self, address: int, value: int, unit: int
    ) -> None:
        async def _do_write():
            resp = await self._client.write_register(
                address=address, value=value, slave=unit
            )
            self._check_response(resp, f"write_register({address}, {value})")
            
        await self._with_retry("write_register", _do_write)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.connected




class RTUTransport(ModbusTransport):
    """Modbus RTU transport wrapping pymodbus AsyncModbusSerialClient."""

    def __init__(
        self,
        port: str,
        baudrate: int = 9600,
        bytesize: int = 8,
        parity: str = "N",
        stopbits: int = 1,
        timeout: float = 3.0,
    ):
        self._port = port
        self._baudrate = baudrate
        self._bytesize = bytesize
        self._parity = parity
        self._stopbits = stopbits
        self._timeout = timeout
        self._client: AsyncModbusSerialClient | None = None

    async def connect(self) -> None:
        self._client = AsyncModbusSerialClient(
            port=self._port,
            baudrate=self._baudrate,
            bytesize=self._bytesize,
            parity=self._parity,
            stopbits=self._stopbits,
            timeout=self._timeout,
        )
        connected = await self._client.connect()
        if not connected:
            raise TransportError(
                f"Failed to connect to RTU port {self._port}"
            )
        logger.info("RTU connected to %s @ %d baud", self._port, self._baudrate)

    async def disconnect(self) -> None:
        if self._client:
            self._client.close()
            self._client = None

    async def read_holding_registers(
        self, address: int, count: int, unit: int
    ) -> list[int]:
        async def _do_read():
            resp = await self._client.read_holding_registers(
                address=address, count=count, slave=unit
            )
            self._check_response(resp, f"read_holding_registers({address}, {count})")
            return list(resp.registers)
            
        return await self._with_retry("read_holding_registers", _do_read)

    async def read_coils(
        self, address: int, count: int, unit: int
    ) -> list[bool]:
        async def _do_read():
            resp = await self._client.read_coils(
                address=address, count=count, slave=unit
            )
            self._check_response(resp, f"read_coils({address}, {count})")
            return list(resp.bits[:count])
            
        return await self._with_retry("read_coils", _do_read)

    async def write_coil(self, address: int, value: bool, unit: int) -> None:
        async def _do_write():
            resp = await self._client.write_coil(
                address=address, value=value, slave=unit
            )
            self._check_response(resp, f"write_coil({address}, {value})")
            
        await self._with_retry("write_coil", _do_write)

    async def write_register(
        self, address: int, value: int, unit: int
    ) -> None:
        async def _do_write():
            resp = await self._client.write_register(
                address=address, value=value, slave=unit
            )
            self._check_response(resp, f"write_register({address}, {value})")
            
        await self._with_retry("write_register", _do_write)

    @property
    def is_connected(self) -> bool:
        return self._client is not None and self._client.connected




def create_transport(
    transport_type: str, address: str, **kwargs
) -> ModbusTransport:
    """Factory: create the correct transport from panel config.

    Args:
        transport_type: "tcp" or "rtu"
        address: "host:port" for TCP, "/dev/ttyUSB0" for RTU
        **kwargs: additional transport-specific options
    """
    if transport_type == "tcp":
        parts = address.split(":")
        host = parts[0]
        port = int(parts[1]) if len(parts) > 1 else 502
        return TCPTransport(host=host, port=port, **kwargs)
    elif transport_type == "rtu":
        return RTUTransport(port=address, **kwargs)
    else:
        raise ValueError(f"Unknown transport type: {transport_type!r}")
