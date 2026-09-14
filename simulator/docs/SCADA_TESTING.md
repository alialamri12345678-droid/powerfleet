# SCADA connection and acceptance checks

## Demo endpoints

Run `python plant_simulator.py --config config/plant.demo.json`.

The demo listens on `0.0.0.0:5021` and exposes generator controller unit IDs
10, 11, and 12 plus mains controller unit ID 20. Addresses are zero-based.

Useful checks:

| Page | Offset | Address | Type | Meaning |
| ---: | ---: | ---: | --- | --- |
| 0 | 9 | 9 | uint16 | GenComm version |
| 1 | 0 | 256 | uint16 | Current slave address |
| 3 | 18 | 786 | uint16 | Generator state |
| 4 | 0 | 1024 | uint16 | Oil pressure kPa |
| 4 | 1 | 1025 | int16 | Coolant temperature C |
| 4 | 6 | 1030 | uint16 | Engine speed RPM |
| 4 | 7 | 1031 | uint16 x 0.1 | Generator frequency Hz |
| 4 | 14 | 1038 | uint32 x 0.1 | Generator L1-L2 voltage V |
| 4 | 20 | 1044 | uint32 x 0.1 | Generator L1 current A |
| 6 | 0 | 1536 | int32 | Generator total watts |
| 6 | 16 | 1552 | int32 | Generator total var |
| 7 | 8 | 1800 | uint32 x 0.1 | Positive generator kWh |
| 8 | 1 | 2049 | bit fields | Named alarm conditions |
| 16 | 8 | 4104 | uint16 write | System control key |
| 16 | 9 | 4105 | uint16 write | Bitwise complement of key |

For a telemetry start in auto, write function 16 to address 4104 with the two
words `35732` and `(~35732) & 0xFFFF` in one request. The two-register atomic
write is intentional. Function 03 reads are limited to 125 registers and
function 16 writes to 123 registers.

## Data status

The supplied GenComm document defines protocol fields across many controller
families. This simulator implements the operational subset backed by the plant
model. Defined but unavailable measurements use documented sentinels rather
than invented values. Demo equipment values are explicitly classified as
simulation parameters or unknown; replace them with sourced manufacturer data
before tests that depend on a particular engine or alternator response.

## RTU

Set `modbus_rtu.enabled` to true and provide an existing serial or paired virtual
COM port. Install dependencies from `requirements.txt`, which includes the
pymodbus serial extra. The configured data bits, parity, stop bits, baud rate,
and unit IDs are passed to the RTU server.
