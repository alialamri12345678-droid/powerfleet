# Generator Fleet Gateway

A customer application for monitoring and supervising generator fleets. The current protocol implementation is Deep Sea Electronics GenComm, with selectable profiles for the generator-controller families covered by GenComm 2.236 MF. Other manufacturers can be added through the same profile and adapter boundary.

The panels perform synchronization, breaker sequencing, load sharing, and electrical protection. The application reads telemetry and requests high-level start/stop actions, schedules, thresholds, and supported power setpoints. Stopping the gateway does not send stop commands to the panels.

At gateway startup, a running unit with no active schedule is adopted by load management. It remains on for the configured dwell period and is then eligible for release when facility load is below its release threshold. Use an expiring override when a manually started unit must remain running independently of load rules.

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

The gateway stores rate-limited telemetry history for each generator and uses it to produce an explainable preventive-maintenance report. The report covers available engine health, fuel, electrical, loading, alarm and lifetime-counter data, gives condition findings and recommended follow-up actions, and exports separately for each generator. It supports maintenance planning; commissioned sensor scaling, physical inspection and the manufacturer's maintenance schedule remain authoritative.

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
