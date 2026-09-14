# Modular DSE and plant simulator

This repository contains a modular electrical-plant and DSE GenComm simulator.
The original `dse_simulator.py` remains available as a compatibility executable;
the new application entry point is `plant_simulator.py`.

## Run the modular simulator

```powershell
python -m pip install -r requirements.txt
python plant_simulator.py --config config/plant.demo.json
```

The demo exposes GEN1/GEN2/GEN3 on TCP port 5021 with unit IDs 10, 11,
and 12. Use `--no-modbus` for UI-only development. Edit or copy
`config/plant.demo.json` to add generators (the architecture is intended for
0-20 units), loads, grid, solar, endpoint, controller, and timing settings.

The UI provides a common-bus overview, source/breaker controls, live electrical
measurements, simulation speeds 1x/2x/5x/10x and pause, fault injection,
scenarios, communication-fault controls, controller diagnostics, and a GenComm
register inspector. The Plant configuration tab can create, clone, select, and
delete sites; add, edit, and remove generators; select generator equipment and
DSE panel profiles; override generator kW size; and configure TCP host, port,
and unit ID. Grid, solar, mains-controller model/endpoint, nominal voltage, and
nominal frequency are editable there as well. **Save and apply to all tabs**
performs a controlled application restart so the overview, faults, scenarios,
diagnostics, register inspector, and TCP listeners all use exactly the same
new topology. **Open site now** does the same when switching sites.

Every generator on the plant overview has an independent 0-to-rated-kW load
slider. Moving it selects manual fixed-kW mode; **Auto** returns the generator
to proportional load sharing. A generator can only deliver that requested load
after its breaker is closed. Engine starting and breaker closing are separate
by default. Enable **Automatically synchronize/close ready generator breakers**
only when testing automatic plant-controller behavior.

Use **Parameters ▼** on a generator row to add direct SCADA telemetry
overrides for fuel level, temperatures, pressures, speed, frequency, aggregate
and per-phase electrical measurements, counters, and controller/status codes.
Overrides are isolated and persisted with that site's runtime state. **Clear
selected** or **Clear all** returns values to the calculated physical model.
Direct phase overrides are intentionally allowed to create abnormal/unbalanced
readings for SCADA alarm testing. Fuel level (page 4 offset 3) and oil
temperature (page 4 offset 2) are implemented values rather than `0xFFFF`
unimplemented sentinels.

Each site has an isolated `config/site_data/<site-id>/` directory containing
its runtime counters and rotating logs. Deleting a user-created site moves its
configuration and isolated data to `config/trash/` for recovery. The profile
selectors include a catalog of 30 current/common DSE models and adjustable
templates for 10 major generator/engine suppliers. Manufacturer identity and
source URLs are separate from assumed simulation values; an adjustable template
is never represented as a verified model datasheet.

## Modbus and GenComm

TCP endpoints support multiple unit IDs and zero-based GenComm addresses.
Function 03 reads holding registers and function 16 writes command/configuration
registers. The initial DSE controller map implements the operational subset of
pages 0, 1, 3-8, 11-14, 16-18, 20, and 24 needed by the included plant model;
defined-but-unimplemented values return type-appropriate sentinels. The register
map is transport-independent so additional registers/pages require no Modbus
server changes.

RTU is available when `modbus_rtu.enabled` is true and `serial_port` names an
existing physical or paired virtual serial port. Creating the operating-system
virtual COM-port pair is intentionally outside this application.

## Legacy compatibility

```powershell
python dse_simulator.py --host 127.0.0.1 --port 5020 --units 3
```

The controls and values are simulated only. Profile values classified as
`simulation_parameter` are assumptions for testing and are not manufacturer
specifications or approved protection settings.

## Run tests

```powershell
python -m unittest discover -s tests -v
```

See `docs/architecture.md` for the inspected original design, retained modules,
dependency direction, configuration policy, and migration decisions.
