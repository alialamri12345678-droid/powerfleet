"""DSE controller emulator mapping a generator to GenComm registers."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
import random
import time
import zlib

from simulator_core.gencomm import DataType, GenCommRegisterMap, RegisterAccess, RegisterDefinition, Sentinel
from simulation.plant import AlarmSeverity, Generator, GeneratorState, Plant


STATE_CODE = {state: index for index, state in enumerate(GeneratorState)}
ALARM_SLOT = {
    "emergency_stop": (1, 12), "low_oil_pressure": (1, 8), "high_coolant_temperature": (1, 4),
    "underspeed": (2, 12), "overspeed": (2, 8), "fail_to_start": (2, 4), "fail_to_stop": (2, 0),
    "loss_of_speed_signal": (3, 12), "undervoltage": (3, 8), "overvoltage": (3, 4), "underfrequency": (3, 0),
    "overfrequency": (4, 12), "overcurrent": (4, 8), "reverse_power": (4, 0),
    "charger_failure": (6, 0), "battery_low": (7, 12),
    "breaker_fails_to_close": (8, 12), "breaker_fails_to_open": (8, 4),
}


@dataclass
class CommunicationDiagnostics:
    online: bool = True
    request_count: int = 0
    exception_count: int = 0
    last_request_at: datetime | None = None
    last_function: int | None = None
    last_register: int | None = None
    response_delay_s: float = 0.0
    intermittent_failure_probability: float = 0.0


class DSEControllerEmulator:
    """Controller behavior stays separate from the generator and plant models."""

    def __init__(self, model: str, family: str, gencomm_version: int, generator: Generator, plant: Plant, serial_number: int = 1, supported_pages: tuple[int, ...] | None = None):
        self.model, self.family, self.gencomm_version = model, family, gencomm_version
        self.generator, self.plant, self.serial_number = generator, plant, serial_number
        self.supported_pages = supported_pages
        self.mode = "auto"
        self.slave_address = 10
        self.baud_rate_code = 7
        self.diagnostics = CommunicationDiagnostics()
        self._control_key = 0
        self._control_complement = 0
        self._rng = random.Random(serial_number)
        self.registers = GenCommRegisterMap(self._definitions())

    def _definitions(self) -> list[RegisterDefinition]:
        g, p = self.generator, self.plant
        ro = RegisterAccess.READ_ONLY
        wo = RegisterAccess.WRITE_ONLY
        definitions = [
            RegisterDefinition(0, 0, "Extended exception code", DataType.UINT16, getter=lambda: 0),
            RegisterDefinition(0, 1, "Extended exception address", DataType.UINT16, getter=lambda: 0),
            RegisterDefinition(0, 6, "Password status", DataType.UINT16, getter=lambda: 0),
            RegisterDefinition(0, 9, "GenComm version", DataType.UINT16, getter=lambda: self.gencomm_version),
            RegisterDefinition(1, 0, "Current slave address", DataType.UINT16, access=RegisterAccess.READ_WRITE, getter=lambda: self.slave_address, setter=lambda value: setattr(self, "slave_address", int(value))),
            RegisterDefinition(1, 1, "Site identity code", DataType.UINT16, access=RegisterAccess.READ_WRITE, getter=lambda: 0, setter=lambda value: None),
            RegisterDefinition(1, 2, "Device identity code", DataType.UINT16, access=RegisterAccess.READ_WRITE, getter=lambda: self.serial_number & 0xFFFF, setter=lambda value: None),
            RegisterDefinition(1, 3, "Baud rate", DataType.UINT16, access=RegisterAccess.READ_WRITE, getter=lambda: self.baud_rate_code, setter=lambda value: setattr(self, "baud_rate_code", int(value))),
            RegisterDefinition(1, 4, "Current language code", DataType.UINT16, access=RegisterAccess.READ_WRITE, getter=lambda: 0x0409, setter=lambda value: None),
            RegisterDefinition(3, 0, "Manufacturer code", DataType.UINT16, getter=lambda: g.telemetry("manufacturer_code", 1)),
            RegisterDefinition(3, 1, "Model number", DataType.UINT16, getter=lambda: g.telemetry("model_number", zlib.crc32(self.model.encode()) % 65534)),
            RegisterDefinition(3, 2, "Serial number", DataType.UINT32, getter=lambda: self.serial_number),
            RegisterDefinition(3, 4, "Control mode", DataType.UINT16, getter=lambda: g.telemetry("control_mode", {"stop": 0, "auto": 1, "manual": 2}.get(self.mode, 1))),
            RegisterDefinition(3, 6, "Alarm status flags", DataType.BITFIELD, getter=lambda: g.telemetry("controller_status", self._alarm_status_word())),
            RegisterDefinition(3, 10, "Engine state timer", DataType.UINT16, units="s", getter=lambda: min(65534, int(g._state_elapsed_s))),
            RegisterDefinition(3, 18, "Engine state", DataType.UINT16, getter=lambda: g.telemetry("generator_state", STATE_CODE[g.state])),
            RegisterDefinition(4, 0, "Oil pressure", DataType.UINT16, units="kPa", getter=lambda: g.telemetry("oil_pressure_bar", g.oil_pressure_kpa / 100.0) * 100.0),
            RegisterDefinition(4, 1, "Coolant temperature", DataType.INT16, units="degC", getter=lambda: g.telemetry("coolant_temperature_c", g.coolant_temp_c)),
            RegisterDefinition(4, 2, "Oil temperature", DataType.INT16, units="degC", getter=lambda: g.telemetry("oil_temperature_c", g.oil_temp_c)),
            RegisterDefinition(4, 3, "Fuel level", DataType.UINT16, units="%", getter=lambda: g.telemetry("fuel_level_pct", g.fuel_level_pct)),
            RegisterDefinition(4, 4, "Charge alternator voltage", DataType.UINT16, scale=.1, units="V", getter=lambda: g.telemetry("charge_alternator_voltage_v", g.battery_voltage_v if g.running else 0)),
            RegisterDefinition(4, 5, "Engine battery voltage", DataType.UINT16, scale=.1, units="V", getter=lambda: g.telemetry("battery_voltage_v", g.battery_voltage_v)),
            RegisterDefinition(4, 6, "Engine speed", DataType.UINT16, units="RPM", getter=lambda: g.telemetry("engine_speed_rpm", g.rpm)),
            RegisterDefinition(4, 7, "Generator frequency", DataType.UINT16, scale=.1, units="Hz", getter=lambda: g.telemetry("frequency_hz", g.frequency_hz)),
            RegisterDefinition(4, 8, "Generator L1-N voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: g.telemetry("voltage_l1_n_v", g.voltage_v / 3**.5)),
            RegisterDefinition(4, 10, "Generator L2-N voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: g.telemetry("voltage_l2_n_v", g.voltage_v / 3**.5)),
            RegisterDefinition(4, 12, "Generator L3-N voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: g.telemetry("voltage_l3_n_v", g.voltage_v / 3**.5)),
            RegisterDefinition(4, 14, "Generator L1-L2 voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: g.telemetry("voltage_l1_l2_v", g.voltage_v)),
            RegisterDefinition(4, 16, "Generator L2-L3 voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: g.telemetry("voltage_l2_l3_v", g.voltage_v)),
            RegisterDefinition(4, 18, "Generator L3-L1 voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: g.telemetry("voltage_l3_l1_v", g.voltage_v)),
            RegisterDefinition(4, 20, "Generator L1 current", DataType.UINT32, scale=.1, units="A", getter=lambda: g.telemetry("current_l1_a", g.current_a)),
            RegisterDefinition(4, 22, "Generator L2 current", DataType.UINT32, scale=.1, units="A", getter=lambda: g.telemetry("current_l2_a", g.current_a)),
            RegisterDefinition(4, 24, "Generator L3 current", DataType.UINT32, scale=.1, units="A", getter=lambda: g.telemetry("current_l3_a", g.current_a)),
            RegisterDefinition(4, 28, "Generator L1 watts", DataType.INT32, units="W", getter=lambda: g.telemetry("power_l1_kw", g.active_kw / 3) * 1000),
            RegisterDefinition(4, 30, "Generator L2 watts", DataType.INT32, units="W", getter=lambda: g.telemetry("power_l2_kw", g.active_kw / 3) * 1000),
            RegisterDefinition(4, 32, "Generator L3 watts", DataType.INT32, units="W", getter=lambda: g.telemetry("power_l3_kw", g.active_kw / 3) * 1000),
            RegisterDefinition(4, 35, "Mains frequency", DataType.UINT16, scale=.1, units="Hz", getter=lambda: p.grid.frequency_hz if p.grid else Sentinel.UNIMPLEMENTED),
            RegisterDefinition(4, 67, "Bus frequency", DataType.UINT16, scale=.1, units="Hz", getter=lambda: p.bus_frequency_hz),
            RegisterDefinition(4, 74, "Bus L1-L2 voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: p.bus_voltage_v),
            RegisterDefinition(5, 0, "Generator total watts", DataType.INT32, units="W", getter=lambda: g.telemetry("active_power_kw", g.active_kw) * 1000),
            RegisterDefinition(5, 8, "Generator total VA", DataType.UINT32, units="VA", getter=lambda: g.telemetry("apparent_power_kva", g.apparent_kva) * 1000),
            RegisterDefinition(5, 16, "Generator total Var", DataType.INT32, units="var", getter=lambda: g.telemetry("reactive_power_kvar", g.reactive_kvar) * 1000),
            RegisterDefinition(5, 21, "Generator average power factor", DataType.INT16, scale=.01, getter=lambda: g.telemetry("power_factor", g.power_factor)),
            RegisterDefinition(5, 22, "Generator percentage full power", DataType.INT16, scale=.1, units="%", getter=lambda: 100 * g.active_kw / g.rated_kw),
            RegisterDefinition(6, 0, "Generator total watts", DataType.INT32, units="W", getter=lambda: g.telemetry("active_power_kw", g.active_kw) * 1000),
            RegisterDefinition(6, 2, "Generator L1 VA", DataType.UINT32, units="VA", getter=lambda: g.apparent_kva * 1000 / 3),
            RegisterDefinition(6, 4, "Generator L2 VA", DataType.UINT32, units="VA", getter=lambda: g.apparent_kva * 1000 / 3),
            RegisterDefinition(6, 6, "Generator L3 VA", DataType.UINT32, units="VA", getter=lambda: g.apparent_kva * 1000 / 3),
            RegisterDefinition(6, 8, "Generator total VA", DataType.UINT32, units="VA", getter=lambda: g.telemetry("apparent_power_kva", g.apparent_kva) * 1000),
            RegisterDefinition(6, 10, "Generator L1 Var", DataType.INT32, units="var", getter=lambda: g.reactive_kvar * 1000 / 3),
            RegisterDefinition(6, 12, "Generator L2 Var", DataType.INT32, units="var", getter=lambda: g.reactive_kvar * 1000 / 3),
            RegisterDefinition(6, 14, "Generator L3 Var", DataType.INT32, units="var", getter=lambda: g.reactive_kvar * 1000 / 3),
            RegisterDefinition(6, 16, "Generator total Var", DataType.INT32, units="var", getter=lambda: g.telemetry("reactive_power_kvar", g.reactive_kvar) * 1000),
            RegisterDefinition(6, 21, "Generator average power factor", DataType.INT16, scale=.01, getter=lambda: g.telemetry("power_factor", g.power_factor)),
            RegisterDefinition(6, 22, "Generator percentage full power", DataType.INT16, scale=.1, units="%", getter=lambda: 100 * g.active_kw / g.rated_kw),
            RegisterDefinition(6, 23, "Generator percentage reactive power", DataType.INT16, scale=.1, units="%", getter=lambda: g.telemetry("reactive_load_pct", 100 * g.reactive_kvar / max(g.rated_kw, 1))),
            RegisterDefinition(7, 6, "Engine run time", DataType.UINT32, units="s", getter=lambda: g.run_hours * 3600),
            RegisterDefinition(7, 8, "Generator positive kWh", DataType.UINT32, scale=.1, units="kWh", getter=lambda: g.telemetry("energy_produced_kwh", g.energy_kwh)),
            RegisterDefinition(7, 16, "Number of starts", DataType.UINT32, getter=lambda: g.telemetry("start_count", g.starts)),
            RegisterDefinition(7, 34, "Fuel used", DataType.UINT32, units="L", getter=lambda: g.telemetry("fuel_used_l", g.fuel_used_l)),
            RegisterDefinition(8, 0, "Number of named alarms", DataType.UINT16, getter=lambda: 128),
            RegisterDefinition(11, 0, "Software version", DataType.UINT16, scale=.01, getter=lambda: 1.00),
            RegisterDefinition(12, 0, "Standard digital inputs", DataType.BITFIELD, getter=self._digital_inputs),
            RegisterDefinition(13, 0, "Standard digital outputs", DataType.BITFIELD, getter=self._digital_outputs),
            RegisterDefinition(14, 0, "Number of LEDs", DataType.UINT16, getter=lambda: 4),
            RegisterDefinition(16, 0, "Supported system controls", DataType.BITFIELD, getter=lambda: 0xFFC0),
            RegisterDefinition(16, 1, "Supported system controls 16-31", DataType.BITFIELD, getter=lambda: 0),
            RegisterDefinition(16, 2, "Supported system controls 32-47", DataType.BITFIELD, getter=lambda: 0xF000),
            RegisterDefinition(16, 8, "System control key", DataType.UINT16, access=wo, setter=self._set_control_key),
            RegisterDefinition(16, 9, "Complement of system control key", DataType.UINT16, access=wo, setter=self._set_control_complement),
            RegisterDefinition(17, 0, "Number of active decoded DTCs", DataType.UINT16, getter=lambda: 1 if "ecu_j1939_fault" in g.alarms and g.alarms["ecu_j1939_fault"].active else 0),
            RegisterDefinition(18, 0, "Number of active raw DTCs", DataType.UINT16, getter=lambda: 1 if "ecu_j1939_fault" in g.alarms and g.alarms["ecu_j1939_fault"].active else 0),
            RegisterDefinition(20, 0, "Manufacturer string", DataType.UNICODE, words=32, getter=lambda: "Deep Sea Electronics"),
            RegisterDefinition(20, 32, "Model string", DataType.UNICODE, words=32, getter=lambda: self.model),
            RegisterDefinition(24, 0, "Identity string 1", DataType.UNICODE, words=32, getter=lambda: g.name),
            RegisterDefinition(24, 32, "Identity string 2", DataType.UNICODE, words=32, getter=lambda: str(self.serial_number)),
        ]
        for offset in range(1, 33):
            if offset not in {definition.offset for definition in definitions if definition.page == 8}:
                definitions.append(RegisterDefinition(8, offset, f"Alarm conditions {offset}", DataType.BITFIELD, getter=lambda o=offset: self._alarm_word(o)))
        return [definition for definition in definitions if self.supported_pages is None or definition.page in self.supported_pages]

    def _alarm_status_word(self) -> int:
        severities = {alarm.severity for alarm in self.generator.alarms.values() if alarm.active}
        return (0x1000 if AlarmSeverity.SHUTDOWN in severities else 0) | (0x0800 if AlarmSeverity.ELECTRICAL_TRIP in severities else 0) | (0x0400 if AlarmSeverity.WARNING in severities else 0)

    def _alarm_word(self, offset: int) -> int:
        word = 0
        for code, alarm in self.generator.alarms.items():
            if alarm.active and code in ALARM_SLOT and ALARM_SLOT[code][0] == offset:
                word |= list(AlarmSeverity).index(alarm.severity) << ALARM_SLOT[code][1]
        return word

    def _digital_inputs(self) -> int:
        return (1 << 7) if self.generator.commanded_start else 0

    def _digital_outputs(self) -> int:
        return ((1 if self.generator.running else 0) << 14) | ((1 if self.generator.state is GeneratorState.CRANKING else 0) << 12) | ((1 if self.generator.breaker.closed else 0) << 8)

    def _set_control_key(self, value: object) -> None:
        self._control_key = int(value)

    def _set_control_complement(self, value: object) -> None:
        self._control_complement = int(value)
        if self._control_complement == ((~self._control_key) & 0xFFFF):
            self.execute_control(self._control_key)

    def execute_control(self, key: int) -> bool:
        function = key - 35700
        if function == 0:
            self.mode = "stop"; return self.generator.stop()
        if function in {1, 32}:
            self.mode = "auto"; return self.generator.start() if function == 32 else True
        if function == 2:
            self.mode = "manual"; return True
        if function == 5:
            return self.generator.start() if self.mode in {"manual", "test"} else False
        if function in {7, 34}:
            self.generator.reset_alarms(); return True
        if function == 8:
            return self.plant.close_generator_breaker(self.generator)
        if function == 9:
            return self.generator.breaker.request_open()
        if function == 33:
            return self.generator.stop()
        return False

    def read(self, address: int, count: int) -> list[int]:
        self._communication_gate()
        self._record(3, address)
        values = self.registers.read(address, count)
        logging.getLogger("modbus").info("unit=%s fc=03 address=%s count=%s response=%s", self.slave_address, address, count, values)
        return values

    def write(self, address: int, values: list[int]) -> None:
        self._communication_gate()
        self._record(16, address)
        logging.getLogger("modbus").info("unit=%s fc=16 address=%s values=%s", self.slave_address, address, values)
        self.registers.write(address, values)

    def _communication_gate(self) -> None:
        if not self.diagnostics.online:
            raise TimeoutError("controller offline")
        if self.diagnostics.response_delay_s > 0:
            time.sleep(self.diagnostics.response_delay_s)
        if self._rng.random() < self.diagnostics.intermittent_failure_probability:
            raise TimeoutError("simulated intermittent communication failure")

    def _record(self, function: int, address: int) -> None:
        self.diagnostics.request_count += 1
        self.diagnostics.last_request_at = datetime.now(timezone.utc)
        self.diagnostics.last_function = function
        self.diagnostics.last_register = address


class DSEMainsControllerEmulator:
    """Mains/bus controller with a controller-specific operational map."""

    def __init__(self, model: str, family: str, gencomm_version: int, plant: Plant, serial_number: int = 1, supported_pages: tuple[int, ...] | None = None):
        self.model, self.family, self.gencomm_version = model, family, gencomm_version
        self.plant, self.serial_number, self.supported_pages = plant, serial_number, supported_pages
        self.slave_address = 10
        self.diagnostics = CommunicationDiagnostics()
        self._control_key = self._control_complement = 0
        self._rng = random.Random(serial_number)
        self.registers = GenCommRegisterMap(self._definitions())

    def _definitions(self) -> list[RegisterDefinition]:
        p = self.plant
        wo = RegisterAccess.WRITE_ONLY
        definitions = [
            RegisterDefinition(0, 0, "Extended exception code", DataType.UINT16, getter=lambda: 0),
            RegisterDefinition(0, 1, "Extended exception address", DataType.UINT16, getter=lambda: 0),
            RegisterDefinition(0, 9, "GenComm version", DataType.UINT16, getter=lambda: self.gencomm_version),
            RegisterDefinition(1, 0, "Current slave address", DataType.UINT16, getter=lambda: self.slave_address),
            RegisterDefinition(3, 0, "Manufacturer code", DataType.UINT16, getter=lambda: 1),
            RegisterDefinition(3, 1, "Model number", DataType.UINT16, getter=lambda: abs(hash(self.model)) % 65534),
            RegisterDefinition(3, 2, "Serial number", DataType.UINT32, getter=lambda: self.serial_number),
            RegisterDefinition(4, 35, "Mains frequency", DataType.UINT16, scale=.1, units="Hz", getter=lambda: p.grid.frequency_hz if p.grid else Sentinel.UNIMPLEMENTED),
            RegisterDefinition(4, 42, "Mains L1-L2 voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: p.grid.voltage_v if p.grid else Sentinel.UNIMPLEMENTED),
            RegisterDefinition(4, 67, "Bus frequency", DataType.UINT16, scale=.1, units="Hz", getter=lambda: p.bus_frequency_hz),
            RegisterDefinition(4, 74, "Bus L1-L2 voltage", DataType.UINT32, scale=.1, units="V", getter=lambda: p.bus_voltage_v),
            RegisterDefinition(6, 24, "Mains total watts", DataType.INT32, units="W", getter=lambda: p.grid_import_kw * 1000),
            RegisterDefinition(6, 48, "Bus total watts", DataType.INT32, units="W", getter=lambda: p.bus_active_kw * 1000),
            RegisterDefinition(16, 0, "Supported system controls", DataType.BITFIELD, getter=lambda: 0x00C0),
            RegisterDefinition(16, 8, "System control key", DataType.UINT16, access=wo, setter=lambda value: setattr(self, "_control_key", int(value))),
            RegisterDefinition(16, 9, "Complement system control key", DataType.UINT16, access=wo, setter=self._set_complement),
            RegisterDefinition(20, 0, "Manufacturer string", DataType.UNICODE, words=32, getter=lambda: "Deep Sea Electronics"),
            RegisterDefinition(20, 32, "Model string", DataType.UNICODE, words=32, getter=lambda: self.model),
            RegisterDefinition(24, 0, "Identity string 1", DataType.UNICODE, words=32, getter=lambda: p.name + " MAINS"),
        ]
        return [d for d in definitions if self.supported_pages is None or d.page in self.supported_pages]

    def _set_complement(self, value: object) -> None:
        self._control_complement = int(value)
        if self._control_complement != ((~self._control_key) & 0xFFFF) or not self.plant.grid:
            return
        function = self._control_key - 35700
        if function == 8:
            self.plant.grid.breaker.request_open()
        elif function == 9:
            self.plant.synchronize_grid()
        elif function in {7, 34}:
            self.plant.grid.faults.clear()

    def _communication_gate(self) -> None:
        if not self.diagnostics.online:
            raise TimeoutError("controller offline")
        if self.diagnostics.response_delay_s: time.sleep(self.diagnostics.response_delay_s)
        if self._rng.random() < self.diagnostics.intermittent_failure_probability: raise TimeoutError("simulated intermittent communication failure")

    def read(self, address: int, count: int) -> list[int]:
        self._communication_gate(); self._record(3, address)
        values = self.registers.read(address, count)
        logging.getLogger("modbus").info("unit=%s fc=03 address=%s count=%s response=%s", self.slave_address, address, count, values)
        return values

    def write(self, address: int, values: list[int]) -> None:
        self._communication_gate(); self._record(16, address)
        logging.getLogger("modbus").info("unit=%s fc=16 address=%s values=%s", self.slave_address, address, values)
        self.registers.write(address, values)

    def _record(self, function: int, address: int) -> None:
        self.diagnostics.request_count += 1; self.diagnostics.last_request_at = datetime.now(timezone.utc)
        self.diagnostics.last_function, self.diagnostics.last_register = function, address
