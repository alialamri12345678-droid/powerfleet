# Generator Fleet Gateway

A customer application for monitoring and supervising generator fleets. The current controller target is the Deep Sea Electronics DSE 8620 family; support for other manufacturers requires controller adapters.

The panels perform synchronization, breaker sequencing, load sharing, and electrical protection. The application reads telemetry and requests high-level start/stop actions, schedules, thresholds, and supported power setpoints. Stopping the gateway does not send stop commands to the panels.

At gateway startup, a running unit with no active schedule is adopted by load management. It remains on for the configured dwell period and is then eligible for release when facility load is below its release threshold. Use an expiring override when a manually started unit must remain running independently of load rules.

**The supplied register map still contains placeholder addresses. Real DSE hardware compatibility has not been commissioned.** Match the exact controller variant, firmware, operating mode, register addressing and command semantics before using a hardware connection. See [the architecture review](docs/architecture-review.md).

## Customer access

There is one customer role with full access to all features in an installation:

- Manage sites and generators, including connection settings.
- Monitor telemetry, view diagnostics, reports and audit history.
- Configure schedules, daily priorities, thresholds and power setpoints.
- Issue manual commands and expiring overrides.

Login is required. There is no technician mode or restricted customer view. Existing accounts and passwords are preserved; the migration converts their role to `customer`.

**One deployment currently represents one customer organization.** All authenticated accounts can manage all sites in that deployment. Separate customers require separate deployments until organization ownership and membership are implemented.

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

6. Match `backend/register_map.yaml` to the external simulator's register contract. There is currently one map per gateway process. In a container, `127.0.0.1` refers to that container; use a host or device address reachable from the backend.

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

Migrations run before the backend starts. Use one backend process per installation for now: multiple API workers would each start their own gateway and scheduler. Public hosting also needs TLS and the operational controls described in the architecture review. RS485 deployments need their serial device exposed to the container and a verified serial configuration.

## Structure and validation

- `backend/app/api`: authenticated HTTP endpoints.
- `backend/app/models`, `db`, `alembic`: relational data and schema upgrades.
- `backend/app/modbus`: device transport, map parsing, telemetry and commands.
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
