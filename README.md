# Generator Fleet Gateway

A customer application for monitoring and supervising generator fleets. The current protocol implementation is Deep Sea Electronics GenComm, with selectable profiles for the generator-controller families covered by GenComm 2.236 MF. Other manufacturers can be added through the same profile and adapter boundary.

The panels perform synchronization, breaker sequencing, load sharing, and electrical protection. The application reads telemetry and requests high-level start/stop actions, schedules, thresholds, and supported power setpoints. Stopping the gateway does not send stop commands to the panels.

At gateway startup, a running unit with no active schedule is adopted by load management. It remains on for the configured dwell period and is then eligible for release when facility load is below its release threshold. Use an expiring override when a manually started unit must remain running independently of load rules.

## Optional adaptive dispatch

Site Settings offers three dispatch choices. **Current threshold method** preserves the existing per-generator start/release thresholds and remains the default after upgrade. **Adaptive planning (advisory)** calculates and displays a proposed generator combination without issuing commands. **Adaptive planning (automatic)** follows the same plan after the customer confirms that the site's electrical topology and measurements have been commissioned.

The adaptive planner evaluates generator rated sizes, usable loading limits, customer priority order, maximum parallel units, utility import capacity, measured solar production, a configured solar-loss case, reserve kW, maintenance exclusions, schedules, and active overrides. Capacity, priority, and economy selection policies are available. Economy uses configured manufacturer fuel curves when every candidate has enough curve data. The planner starts one required unit at a time and will not release an existing generator until every target generator has fresh controller data and confirmed breaker feedback. Synchronization, load sharing, breaker sequencing, and electrical protection remain with the configured controllers.

Grid and solar operation requires a commissioned site power meter or external energy controller to submit fresh readings to `POST /api/sites/{site_id}/dispatch/measurement` using an authenticated customer session. A reading contains `measured_at`, facility `load_kw`, `solar_kw`, `grid_connected`, and `bus_energized`. Missing or stale readings suspend adaptive actions. Automatic grid dispatch also requires a verified import capacity. Keep a site in advisory mode until the proposed combinations have been validated against the external simulator and the real electrical arrangement.

The supplied map now uses the zero-based register addresses and scaling in GenComm 2.236 MF (26 May 2022). Remote start/stop uses the required atomic system-control key and one's-complement pair. Model-specific optional points and the actual controller firmware/configuration must still be verified during commissioning. See [the architecture review](docs/architecture-review.md).

## Customer access

There is one customer role with full access to all features in an installation:

- Manage sites and generators, including connection settings.
- Monitor telemetry, view diagnostics, reports and audit history.
- Configure schedules, daily priorities, thresholds and power setpoints.
- Issue manual commands and expiring overrides.

Login is required. There is no technician mode or restricted customer view. Existing accounts and passwords are preserved; the migration converts their role to `customer`.

Customer organizations now isolate sites in a shared database. Every account has full control within its own organization, while site discovery, switching, REST calls and live streams reject another organization's facilities. Site selection is stored in the browser session token, so two sessions can work in different facilities independently.

## Preventive maintenance

The Reports page has separate Preventive, Fuel consumption, and Efficiency tabs. For each generator, configure component service tasks from the manufacturer's schedule (running hours and/or calendar days, whichever comes first) with verified baselines. Engineers select only the tasks actually completed, confirm the checklist and record the service date, hour reading, and notes. Due and overdue tasks appear on the dashboard and are recorded in the audit events. Each task advances independently.

Every report tab supports arbitrary inclusive From/To dates in the site's timezone; the same window is used for on-screen history and CSV exports. In Preventive, date selection filters readings, finding history, and completed services; service deadlines and open findings remain current so a historical date cannot conceal a task due today.

Preventive findings use persistent trends at comparable operating loads and verified measurements, not an isolated low/high sample. The report separately shows service compliance, observed condition, and measurement coverage. Missing, stale, or uncommissioned data is **unknown**, not healthy. Recording work moves a finding to awaiting verification; it clears only after subsequent qualifying measurements (or a new alarm-free inspection for controller alarms). A satisfactory report supports planning but does not certify physical condition or replace manufacturer guidance. The report and completed-service history export in English or Arabic CSV.

Fuel and efficiency reports use matched, quality-checked measurement intervals and explicitly exclude collection gaps, counter resets, and changed measurement sources. Configure the generator's engine model, nominal battery/frequency and fuel measurement source in its generator settings. A cumulative fuel-used register is preferred. A flow meter gives an estimated volume; tank-level consumption requires a calibrated level-to-litres curve and recorded refills/transfers. Energy comes from a cumulative kWh register when available, or is estimated from sampled kW. Conversion efficiency in percent requires a commissioned fuel lower heating value; otherwise kWh/L and L/kWh remain available if the matching fuel and energy measurements are sufficient. The daily, per-generator and fleet totals and bilingual CSV share the same calculations. Historical readings without explicit quality and acquisition timestamps remain unknown; they are not retroactively treated as valid measurements.

Commission the actual controller's optional registers, scaling and update cadence before trusting these reports. Neither generator efficiency nor failure prediction can be inferred from an uninstrumented panel. For long deployments, plan retention/rollups for raw telemetry and validate report latency with the intended fleet size.

## Local setup with an external simulator

The backend contains no mock Modbus server and creates no simulated generators. Run your external simulation application separately.

1. Install the backend dependencies:

   ```powershell
   cd backend
   python -m venv venv
   .\venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   Copy-Item .env.development.example .env
   ```

2. Edit `backend/.env`. For a new database, supply `BOOTSTRAP_ADMIN_EMAIL` and a `BOOTSTRAP_ADMIN_PASSWORD` of at least 12 characters. The legacy environment variable names initialize the first **customer** account. An existing installation continues to use its existing credentials; these variables do not reset passwords.

3. Run migrations, then start the backend:

   ```powershell
   python -m alembic upgrade head
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
   ```

4. In a second terminal, start the frontend:

   ```powershell
   cd frontend
   npm ci
   npm run dev -- --host 127.0.0.1
   ```

5. Open [http://localhost:3000](http://localhost:3000), sign in, and add each generator with your simulator's host, port, unit ID and rated power. Use the simulator's actual endpoint; the app does not assume a particular local port.

6. Configure the external simulator to expose the GenComm 2.236 MF addresses in `backend/register_map.yaml`. Each generator selects its DSE model-family profile; the list is discovered from the backend rather than hard-coded in the UI. In a container, `127.0.0.1` refers to that container; use a host or device address reachable from the backend.

If upgrading an older environment file, remove the retired `MOCK_MODBUS_ENABLED`, `MOCK_MODBUS_HOST`, `MOCK_MODBUS_PORT` and `SEED_DEMO_DATA` entries. No demo accounts are created. The standalone program in `simulator/` remains independent and is never imported or launched by the backend.

## Database upgrades

Back up the database before upgrading, then run `python -m alembic upgrade head` from `backend/`. The customer-access migration:

- Preserves account IDs, email addresses, passwords and audit ownership.
- Converts existing account roles to the single customer role.
- Removes configuration rows pointing to deleted generators.
- Keeps the site-wide threshold defaults and historical events.
- Detaches deleted-generator references from audit events.

The later preventive/performance migration adds equipment analytics settings, reading-quality metadata, component tasks, persistent findings, and fuel-movement records without rewriting historical telemetry. Back up and verify each installation before migrating; commissioning metadata is populated only by new polls.

Generator deletion now removes start/release thresholds, per-generator thresholds, daily priorities, schedules, schedule exceptions, setpoints and overrides. Remaining generator and threshold priorities are compacted, while each day's relative priority order is preserved. SQLite foreign-key enforcement is enabled, matching PostgreSQL's configured cascades. Site deletion preserves customer accounts by moving their active context to a remaining site.

## Deployment

Copy the root `.env.example` to `.env` and supply the PostgreSQL password, a strong JWT secret and the first customer's credentials if needed. Then run:

```sh
docker compose up -d --build
```

Migrations run before services start. The production stack separates horizontally scalable API workers (`RUNTIME_MODE=api`) from the panel-owning site gateway (`RUNTIME_MODE=gateway`). Renewable database leases prevent duplicate site ownership, while queued commands and stored telemetry bridge temporary API/gateway or WAN interruptions. Local development remains `RUNTIME_MODE=combined`.

Terminate TLS at the deployment load balancer or reverse proxy and set `FORCE_HTTPS=true` only when forwarded scheme handling is configured correctly. RS485 deployments need their serial device exposed to the gateway container and a verified serial configuration.

For a verified local SQLite backup:

```powershell
cd backend
python tools/backup_sqlite.py scada.db backups/scada.db
```

The `/health/ready` endpoint supports readiness checks and `/metrics` exposes Prometheus-format gateway measurements. `tools/capacity_probe.py` provides a repeatable API baseline; supported production limits must be set from tests against the real deployment topology.

## Structure and validation

- `backend/app/api`: authenticated HTTP endpoints.
- `backend/app/models`, `db`, `alembic`: relational data and schema upgrades.
- `backend/app/modbus`: device transport, map parsing, telemetry and commands.
- `backend/app/controllers`: vendor-specific controller adapters and capabilities.
- `backend/app/telemetry`, `services`: history capture and maintenance analysis.
- `backend/tools`: backup verification and deployment capacity probes.
- `backend/app/rules`: supervisory scheduling and fleet demand decisions.
- `frontend/src`: React/JavaScript interface, REST client and WebSocket telemetry.
- `backend/tests`: API, migrations, register-map, rules and cooldown tests.

```powershell
cd backend
python -m pytest -q
cd ../frontend
npm run build
```

See [docs/architecture-review.md](docs/architecture-review.md) for the global deployment assessment and recommended next steps.
