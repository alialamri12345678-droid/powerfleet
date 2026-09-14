"""GenComm address, datatype, scaling, sentinel, and access semantics.

The register layer deliberately knows nothing about sockets or plant physics.
Addresses are zero-based, as specified by GenComm.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Callable, Iterable


def absolute_address(page: int, offset: int) -> int:
    if not 0 <= page <= 255 or not 0 <= offset <= 255:
        raise ValueError("GenComm page and offset must be between 0 and 255")
    return page * 256 + offset


def split_address(address: int) -> tuple[int, int]:
    if not 0 <= address <= 0xFFFF:
        raise ValueError("GenComm address must be between 0 and 65535")
    return divmod(address, 256)


class DataType(str, Enum):
    UINT16 = "uint16"
    INT16 = "int16"
    UINT32 = "uint32"
    INT32 = "int32"
    BITFIELD = "bitfield"
    ASCII = "ascii"
    UNICODE = "unicode"


class RegisterAccess(str, Enum):
    READ_ONLY = "read_only"
    WRITE_ONLY = "write_only"
    READ_WRITE = "read_write"


class Sentinel(str, Enum):
    UNIMPLEMENTED = "unimplemented"
    OVER_RANGE = "over_range"
    UNDER_RANGE = "under_range"
    TRANSDUCER_FAULT = "transducer_fault"
    BAD_DATA = "bad_data"
    HIGH_DIGITAL = "high_digital"
    LOW_DIGITAL = "low_digital"
    RESERVED = "reserved"


_SENTINEL_DECREMENT = {
    Sentinel.UNIMPLEMENTED: 0, Sentinel.OVER_RANGE: 1, Sentinel.UNDER_RANGE: 2,
    Sentinel.TRANSDUCER_FAULT: 3, Sentinel.BAD_DATA: 4,
    Sentinel.HIGH_DIGITAL: 5, Sentinel.LOW_DIGITAL: 6, Sentinel.RESERVED: 7,
}


class GenCommError(Exception):
    modbus_exception_code = 2


class IllegalAddress(GenCommError):
    pass


class IllegalWrite(GenCommError):
    pass


@dataclass(frozen=True)
class RegisterDefinition:
    page: int
    offset: int
    name: str
    data_type: DataType
    scale: float = 1.0
    units: str = ""
    access: RegisterAccess = RegisterAccess.READ_ONLY
    words: int | None = None
    getter: Callable[[], object] | None = None
    setter: Callable[[object], None] | None = None

    @property
    def address(self) -> int:
        return absolute_address(self.page, self.offset)

    @property
    def word_count(self) -> int:
        if self.words is not None:
            return self.words
        return 2 if self.data_type in {DataType.UINT32, DataType.INT32} else 1


def sentinel_words(data_type: DataType, sentinel: Sentinel, words: int = 1) -> list[int]:
    decrement = _SENTINEL_DECREMENT[sentinel]
    if data_type in {DataType.UINT16, DataType.BITFIELD}:
        return [0xFFFF - decrement]
    if data_type is DataType.INT16:
        return [0x7FFF - decrement]
    if data_type is DataType.UINT32:
        value = 0xFFFFFFFF - decrement
        return [(value >> 16) & 0xFFFF, value & 0xFFFF]
    if data_type is DataType.INT32:
        value = 0x7FFFFFFF - decrement
        return [(value >> 16) & 0xFFFF, value & 0xFFFF]
    if data_type in {DataType.ASCII, DataType.UNICODE}:
        return [0x2020] * words
    raise ValueError(data_type)


def encode_value(definition: RegisterDefinition, value: object) -> list[int]:
    if isinstance(value, Sentinel):
        return sentinel_words(definition.data_type, value, definition.word_count)
    if definition.data_type is DataType.ASCII:
        data = str(value).encode("latin-1", errors="replace")[: definition.word_count * 2].ljust(definition.word_count * 2, b" ")
        return [(data[i] << 8) | data[i + 1] for i in range(0, len(data), 2)]
    if definition.data_type is DataType.UNICODE:
        chars = list(str(value)[: definition.word_count])
        chars.extend(" " for _ in range(definition.word_count - len(chars)))
        return [ord(char) for char in chars]

    raw = int(round(float(value) / definition.scale))
    bits = 32 if definition.data_type in {DataType.UINT32, DataType.INT32} else 16
    signed = definition.data_type in {DataType.INT16, DataType.INT32}
    minimum, maximum = (-(1 << (bits - 1)), (1 << (bits - 1)) - 1) if signed else (0, (1 << bits) - 1)
    if not minimum <= raw <= maximum:
        raise ValueError(f"{definition.name} raw value {raw} does not fit {definition.data_type.value}")
    raw &= (1 << bits) - 1
    return [raw] if bits == 16 else [(raw >> 16) & 0xFFFF, raw & 0xFFFF]


def decode_value(definition: RegisterDefinition, words: Iterable[int]) -> object:
    values = list(words)
    if len(values) != definition.word_count:
        raise ValueError("complete multi-register values must be transferred in one operation")
    if definition.data_type is DataType.ASCII:
        return bytes(byte for word in values for byte in (word >> 8, word & 0xFF)).decode("latin-1").rstrip(" ")
    if definition.data_type is DataType.UNICODE:
        return "".join(chr(word) for word in values).rstrip(" ")
    raw = values[0] if len(values) == 1 else (values[0] << 16) | values[1]
    bits = 16 * len(values)
    if definition.data_type in {DataType.INT16, DataType.INT32} and raw & (1 << (bits - 1)):
        raw -= 1 << bits
    return raw * definition.scale


class GenCommRegisterMap:
    """Protocol-neutral register map suitable for Modbus functions 03 and 16."""

    def __init__(self, definitions: Iterable[RegisterDefinition]):
        self._by_start: dict[int, RegisterDefinition] = {}
        self._by_word: dict[int, tuple[RegisterDefinition, int]] = {}
        for definition in definitions:
            if definition.address in self._by_start:
                raise ValueError(f"duplicate register {definition.address}")
            self._by_start[definition.address] = definition
            for index in range(definition.word_count):
                address = definition.address + index
                if address in self._by_word:
                    raise ValueError(f"overlapping register {address}")
                self._by_word[address] = (definition, index)

    def read(self, address: int, count: int) -> list[int]:
        if not 1 <= count <= 125:
            raise IllegalAddress("function 03 count must be 1..125")
        result: list[int] = []
        cursor = address
        end = address + count
        while cursor < end:
            item = self._by_word.get(cursor)
            if item is None:
                result.append(0xFFFF)  # GenComm permits sentinel reads across reserved gaps.
                cursor += 1
                continue
            definition, index = item
            if index != 0 or cursor + definition.word_count > end:
                raise IllegalAddress("multi-register value must be read atomically")
            if definition.access is RegisterAccess.WRITE_ONLY:
                raise IllegalAddress("write-only register")
            value = definition.getter() if definition.getter else Sentinel.UNIMPLEMENTED
            result.extend(encode_value(definition, value))
            cursor += definition.word_count
        return result

    def write(self, address: int, words: Iterable[int]) -> None:
        values = list(words)
        if not 1 <= len(values) <= 123:
            raise IllegalAddress("function 16 count must be 1..123")
        cursor = address
        consumed = 0
        pending: list[tuple[RegisterDefinition, object]] = []
        while consumed < len(values):
            item = self._by_word.get(cursor)
            if item is None or item[1] != 0:
                raise IllegalAddress(f"unsupported register {cursor}")
            definition = item[0]
            if definition.access is RegisterAccess.READ_ONLY or definition.setter is None:
                raise IllegalWrite(f"register {cursor} is read-only or unimplemented")
            if consumed + definition.word_count > len(values):
                raise IllegalAddress("multi-register value must be written atomically")
            chunk = values[consumed : consumed + definition.word_count]
            pending.append((definition, decode_value(definition, chunk)))
            consumed += definition.word_count
            cursor += definition.word_count
        for definition, value in pending:
            definition.setter(value)

    def inspect(self, address: int) -> dict[str, object] | None:
        item = self._by_word.get(address)
        if item is None:
            return None
        definition, word_index = item
        page, offset = split_address(address)
        return {
            "address": address, "page": page, "offset": offset,
            "name": definition.name, "datatype": definition.data_type.value,
            "scale": definition.scale, "units": definition.units,
            "access": definition.access.value, "word_index": word_index,
        }

    def validates_read(self, address: int, count: int) -> bool:
        if not 1 <= count <= 125 or address < 0 or address + count > 65536:
            return False
        cursor, end = address, address + count
        while cursor < end:
            item = self._by_word.get(cursor)
            if item is None:
                if cursor // 256 <= 127:
                    cursor += 1
                    continue
                return False
            definition, index = item
            if index != 0 or definition.access is RegisterAccess.WRITE_ONLY or cursor + definition.word_count > end:
                return False
            cursor += definition.word_count
        return True

    def validates_write(self, address: int, count: int) -> bool:
        if not 1 <= count <= 123 or address < 0 or address + count > 65536:
            return False
        cursor, end = address, address + count
        while cursor < end:
            item = self._by_word.get(cursor)
            if item is None or item[1] != 0:
                return False
            definition = item[0]
            if definition.access is RegisterAccess.READ_ONLY or definition.setter is None or cursor + definition.word_count > end:
                return False
            cursor += definition.word_count
        return True
