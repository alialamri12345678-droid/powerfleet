# Simulator architecture and incremental migration

## Current architecture

`dse_simulator.py` is a standalone Python application. Tkinter owns the UI, a
background asyncio thread runs pymodbus TCP, and `SimulatedGenerator` owns the
engine sequence, telemetry, commands, and alarms. Register definitions are a
single in-code dictionary. There is no persistence other than command-line
arguments, no plant/bus abstraction, and no automated test suite.

The current executable, Tkinter panels, pymodbus server lifecycle, unit-ID
routing, start/stop controls, basic fault controls, and timed start/cooldown
behaviour are useful and should be retained during migration.

## Main limitations

- UI, simulation, GenComm encoding, and transport are tightly coupled.
- Existing addresses are application-specific and are not a GenComm page map.
- Coils are used for commands although GenComm defines functions 03 and 16.
- Telemetry fields are independently randomized and lack current, kVA, and PF.
- Equipment/controller properties are hard-coded and have no provenance.
- Broad exceptions in the update loop hide protocol defects.
- There is no breaker, common bus, grid, PV, synchronization, EMS, scenario,
  persistence, or request-diagnostics model.
- `SimulatorGUI._update_gui` treated status IDs 4 and 5 as running, although
  `STATUS_RUNNING` is 3. This prevented facility load sharing from selecting
  running generators.

## Target dependency direction

The intended dependency direction is UI/transport -> controller/register layer
-> application services -> physical plant model. The physical plant model must
not import DSE or Modbus modules.

```text
simulator_core/       typed domain and protocol-neutral calculations
  electrical.py       RMS three-phase relationships
  profiles.py         equipment/controller schema and loaders
  gencomm.py          pages, codecs, scaling, access and sentinel semantics
config/
  equipment/          provenance-aware generator/alternator/PV profiles
  controllers/        per-model capability and page declarations
simulation/           future generator/grid/PV/bus/breaker/sync/load/EMS models
transports/           future pymodbus TCP and RTU adapters
ui/                   future Tkinter views and view models
tests/                deterministic unit and integration tests
```

## Dependency policy

Keep Python standard-library dataclasses and JSON for the core. Retain
`pymodbus` for TCP and later RTU. Add no schema library until the configuration
surface justifies it; Pydantic would then be appropriate for detailed validation
and user-facing error locations. PyYAML is optional only if YAML authoring is
preferred. Use pytest for fixtures/integration tests when introduced, while the
initial tests remain runnable with `unittest` and no extra dependency.

## Migration plan

1. Establish tested core boundaries, provenance-aware profiles, correct
   electrical calculations, and GenComm codecs while retaining the executable.
2. Move the generator state machine behind a clock-driven domain API and load
   plant/equipment/controller JSON configuration.
3. Build controller-specific register maps and a pymodbus data-block adapter
   that enforces function 03/16 and exceptions; keep an explicit legacy map mode.
4. Add breakers, loads, common bus, grid, PV, synchronization, load sharing,
   EMS, alarms, and fault/scenario services in that order.
5. Convert Tkinter panels into view-model consumers and add the plant overview,
   diagnostics, register inspector, logs, and scenario controls.

Every step keeps the last working executable available and adds tests before the
new path replaces legacy behaviour.

## Implemented modules

- `simulation/plant.py`: generators, breakers, loads, grid, PV, common bus,
  synchronization, alarms, energy and fuel accumulation, and time scaling.
- `simulation/ems.py`: generator scheduling, proportional/priority dispatch,
  fixed/base-load handling, grid import targeting, and PV minimum-load/export
  curtailment.
- `simulation/faults.py` and `simulation/scenarios.py`: manual fault injection
  and reusable run/pause/reset sequences.
- `controllers/dse.py`: per-profile controller emulator and operational GenComm
  pages, including documented complemented system-control keys.
- `transports/modbus.py`: multiple-unit Modbus TCP and optional RTU adapters.
- `runtime.py`: configuration, persistence, logging, endpoint composition, and
  application clock.
- `ui/plant_ui.py`: overview, controls, diagnostics, register inspector, faults,
  scenarios, event display, and simulation-speed controls.

The GenComm map is deliberately an operational subset rather than a claim that
every register applies to every DSE model. Unsupported model features remain
sentinels, and controller profile declarations select the available pages.

## GenComm source decisions

The user-supplied `GenComm.docx` is treated as protocol reference data, not as
instructions. Implemented rules include zero-based address = page * 256 +
offset; functions 03/16 limits; atomic transfer of multi-register values;
most-significant word first for the documented 32-bit representation; scaling
at the register boundary; space-filled strings without null terminators; and
the documented type-specific sentinel values. Controller-profile support is
still provisional until each model is checked against model-specific DSE
documentation.
