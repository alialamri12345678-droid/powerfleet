# Generator Fleet Scheduling & Load-Management Gateway

A resilient middleware gateway and customer-facing web dashboard designed to pair with Deep Sea Electronics (DSE) generator synchronising and load-share modules (**DSE8620 MKII / DSE8610 MKII**).

---

## Safety & Scope Boundary

> [!IMPORTANT]
> **Electrical Safety Precedence**:
> Each DSE panel handles all safety-critical functions internally: bus synchronisation, voltage/frequency matching, load-sharing math, overcurrent, overspeed, reverse power, and engine thermal protections.
>
> **This software only performs high-level supervisory orchestration:**
> 1. Reads live status/telemetry (run state, load %, alarms, accumulated run hours).
> 2. Asserts a small number of control points (Remote Start coil, Remote Stop coil, and optional Fixed-Power setpoint).
>
> If this software stops, crashes, or loses power, the DSE panels latched state remains intact and the panels continue protecting the equipment and managing load-sharing autonomously.

---

## Register Map Configuration

All Modbus addresses are defined in [`backend/register_map.yaml`](backend/register_map.yaml). No register addresses are hardcoded in the application logic.

### Updating from DSE Documentation
When you receive the official Modbus documentation from DSE support for the 8620/8610 MKII:
1. Open `backend/register_map.yaml`.
2. Locate the registers labeled `# PLACEHOLDER — update from DSE docs`.
3. Update the `address` (decimal or hexadecimal `0x...`), `type` (`uint16`, `int16`, `uint32`, `bool`), `scale`, and bit assignments.
4. Restart the gateway service — no Python code changes are required.

---

## Tech Stack

- **Backend**: Python 3.11+, FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2
- **Modbus Driver**: `pymodbus` (supports pluggable Modbus TCP and Modbus RTU over RS485)
- **Scheduler**: APScheduler with retry/backoff and timezone awareness
- **Database**: PostgreSQL (production) / SQLite via `aiosqlite` (local development)
- **Realtime**: WebSockets pushing status diffs to connected clients
- **Frontend**: React 18, Vite, `lucide-react`, Vanilla CSS tokens
- **Packaging**: Docker Compose for single-site industrial PC or Raspberry Pi deployment

---

## System Architecture

```
                       ┌─────────────────────────────────────────┐
                       │           React Web Dashboard           │
                       │             (Customer View)             │
                       └───────────────────▲─────────────────────┘
                                           │ REST + WebSocket
                       ┌───────────────────┴─────────────────────┐
                       │             FastAPI Backend             │
                       │  - Auth & Role Enforcement              │
                       │  - Multi-tenant site_id Scoping         │
                       │  - Append-only Audit Log                │
                       └─────────────▲─────────────▲─────────────┘
                                     │             │
        ┌────────────────────────────┴──┐       ┌──┴──────────────────────────┐
        │        Rules Engine           │       │    Modbus Gateway Service   │
        │  - Weekly Duty Scheduling     │       │  - Command Rate-Limiting    │
        │  - Load-Following Hysteresis  │◀─────▶│  - Startup State Reconcile  │
        │  - Advisory Precedence        │       │  - Configurable Register Map│
        └───────────────────────────────┘       └──────────────▲──────────────┘
                                                               │ Modbus TCP / RTU
                                                ┌──────────────┴──────────────┐
                                                │   DSE 8620 / 8610 MKII      │
                                                │   Generator Controllers     │
                                                └─────────────────────────────┘
```

---

## Quick Start (Development with Simulated Panels)

### 1. Backend Setup
```bash
cd backend
python -m venv venv
venv\Scripts\activate   # Or: source venv/bin/activate on Linux/Mac
pip install -r requirements.txt

# Run migrations and start API server
alembic upgrade head
python -m uvicorn app.main:app --reload --port 8000
```
*Note: In development mode (`MOCK_MODBUS_ENABLED=true`), the backend automatically launches an in-process mock Modbus TCP server simulating 3 DSE panels with realistic telemetry, load variation, and state machines.*

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```
Open [http://localhost:3000](http://localhost:3000) in your browser.

### 3. Demo User Accounts
The system provides demo access:
- **Customer**: `customer@example.com` / `customer123`
  - Unified view with access to generator controls, weekly duty calendar, load threshold sliders, raw diagnostics, manual overrides, and full audit logs.

---

## Production Deployment via Docker Compose

To deploy the entire stack on an on-site industrial PC or Raspberry Pi:

1. Copy `.env.example` to `.env` and configure production secrets:
   ```bash
   cp .env.example .env
   ```
2. For RS485 serial communication, uncomment the device mapping in `docker-compose.yml`:
   ```yaml
   devices:
     - "/dev/ttyUSB0:/dev/ttyUSB0"
   ```
3. Launch the container stack:
   ```bash
   docker compose up -d --build
   ```

---

## Key Operational Rules & Edge Cases

1. **Rule Precedence**: Load safety rules always override convenience schedules. If a weekly schedule calls for a generator to stop, but site load remains above threshold, the shutdown is deferred and an audit event is logged.
2. **Hysteresis & Anti-Hunting**: Backup generators start when load exceeds the start threshold (e.g. 70%) and stop only when load drops below the stop threshold (e.g. 50%) AND a minimum dwell time (default 120s) has elapsed.
3. **Gateway Cooldown Enforcement**: The gateway enforces a minimum 30-second run time after Start and 60-second rest time after Stop per panel, independent of user or schedule commands.
4. **Technician Overrides**: Manual overrides require an explicit expiration duration (max 8 hours). Overrides display a persistent banner on the customer dashboard and automatically release upon expiry.
5. **Gateway Offline Behavior**: If the gateway disconnects, the frontend displays a clear "Gateway Offline" notification. DSE panels maintain their latched run state and continue electrical protection autonomously.
