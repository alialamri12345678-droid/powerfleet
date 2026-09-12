# Architecture review — customer generator fleet platform

Reviewed 12 September 2026 against the current source, SQLite upgrade path, API tests and frontend build.

The application is a useful foundation for a customer installation. It can evolve into a global product, but it is not currently a shared, horizontally scalable cloud platform. No measured fleet-size, concurrent-user or availability limit has been established; tests with a few generators are not capacity evidence.

## Product boundary

The customer has one interface with full supervisory controls. The controller performs synchronization, voltage/frequency matching, breaker sequencing and electrical protection. A controller adapter should express requests supported by that panel and interpret its feedback; the application should not implement synchronization algorithms.

DSE distinguishes the original DSE8620 from the DSE8620 MKII. The MKII is described as synchronizing one genset with utility power, with an option to operate as a DSE8610 MKII for generator-to-generator load sharing. The exact variant and configured topology therefore matter. [DSE8620](https://www.deepseaelectronics.com/genset/load-sharing-synchronising-control-modules/dse8620), [DSE8620 MKII](https://www.deepseaelectronics.com/genset/load-sharing-synchronising-control-modules/dse8620-mkii).

The checked-in register map explicitly labels its addresses as placeholders. Neither a successful build nor the API tests validate those addresses, coil commands, scaling, word order, controller control keys or physical feedback. The external simulator's register contract and the exact DSE communications documentation remain required for commissioning. [DSE technical downloads](https://www.deepseaelectronics.com/genset/load-sharing-synchronising-control-modules/dse8620-mkii/downloads).

## Changes delivered in this update

- Removed the in-process mock Modbus server, its startup/shutdown hooks, simulation configuration and automatic demo fleet creation. The separate simulator application is independent of the backend.
- Unified API permissions and UI access into one customer role, including diagnostics, overrides, generator configuration, setpoints and site management. Existing users and credentials survive migration.
- Fixed deletion of generator configuration and cached control intents. Added SQLite foreign-key enforcement and an upgrade that removes earlier orphan rows while preserving audit events and site defaults.
- Fixed site deletion so it preserves customer accounts and unregisters the site's generators from runtime services.
- Reset page state when switching sites, removed demo sign-in and renamed the former technician pages to feature names.
- Removed the Windows-only Rollup binary as a required application dependency. It remains an optional platform-specific build dependency selected through Rollup.

## Scalability assessment

| Area | Evidence in the current source | Implication and required next step |
| --- | --- | --- |
| Multiple panel types | `modbus/gateway.py` loads one map at construction. `models/panel.py` has connection details but no controller profile. Telemetry and command names are fixed in the gateway. | A map substitution affects every panel. Introduce a versioned controller profile on each panel and adapters with normalized telemetry, capabilities, command encoding and feedback interpretation. Ship and validate DSE8620 first. |
| Customer isolation | All users now have full installation access. `api/sites.py` lists all sites; `User.site_id` stores the active site. There is no customer organization or site membership model. | This is appropriate for one customer's deployment. A shared service needs `organization_id` ownership and memberships before unrelated customers share a database. Full customer access must mean access to that customer's assets. |
| Multiple backend workers | `main.py` starts a gateway and APScheduler in every FastAPI lifespan. Gateway state, cooldowns, rules and WebSocket connections live in process memory. | Scaling the API to several workers would create multiple controllers of the same equipment. Separate the web API from site gateway workers and establish exclusive ownership of each gateway/device. |
| Regional connectivity | The API process directly opens TCP/serial connections to every configured panel. | Place device communication and supervisory scheduling in an on-site gateway. Connect it outward to the central service using an authenticated encrypted channel, with local operation during WAN loss and buffered event delivery. |
| Polling capacity | `_poll_loop` gathers all panels in one cycle, waits for the slowest task, then sleeps. Individual status points are read sequentially. YAML poll groups are parsed but not used by the gateway's read loop. RTU clients are created per panel. | Benchmark with representative latency and failures. Use bounded polling, grouped register reads, separate sampling intervals and one serialized connection owner per shared serial bus. |
| Command coordination | Cooldowns and intents are local dictionaries. Reads, manual commands and rule actions share device connections. `_with_retry` retries both reads and writes. | Add per-device command serialization, durable command IDs and explicit requested/acknowledged/confirmed/failed/unknown states. A write timeout requires adapter-specific reconciliation before a retry. |
| Active-site consistency | REST authorization reads the user's mutable database `site_id`; the WebSocket chooses a site from token claims. Switching site updates the user row. | Two browser sessions for the same user can disagree about which site a command targets. Use an explicit request/site context validated against organization membership consistently across REST, refresh and WebSockets. |
| Historical reporting | `api/reports.py` uses live lifetime counters and at most 200 events. Its average/peak load values derive from current telemetry, including a fallback estimate. `rules_reconstruct_threshold_state` also examines only 200 events. | These are not complete period analytics or reliable fleet-wide reconstruction. Store telemetry/counter history, aggregate by site/time, paginate audit reads and persist automation state independently of a short event window. |
| International behavior | Weekly schedules use site timezones, but `_pick_backup` chooses the weekday in UTC. Schedule exceptions build naive server-local datetimes. Frontend day labels use browser time; the site picker has a short timezone list. | Use the site's IANA timezone for all operational calendar decisions and UTC for storage. Add timezone validation, DST/boundary tests, locale formatting, translation and RTL support where needed. |
| Production operation | Compose exposes HTTP services; the WebSocket token is placed in the URL and validated at connection time. There are no capacity tests or central gateway ownership/health services. | Add TLS, short-lived stream credentials, account lifecycle controls, metrics, backup/restore verification and supported deployment targets. Docker execution and PostgreSQL behavior were not exercised in this environment. |

These are source-backed findings and proposed changes, not features implemented by this update.

## Proposed structure for the next phase

Keep the React customer application and FastAPI API. Introduce an organization/site ownership layer, a command service and a telemetry history service in the central application. Run a separate gateway worker at each facility, responsible for its device connections, local supervisory schedules and durable command outcomes. Each generator selects a controller adapter; the first adapter should cover the exact DSE8620 variant and firmware in use.

The interface between adapters and the rest of the system should describe capabilities explicitly: available measurements, engineering units and quality, start/stop request support, setpoint limits, acknowledgement semantics and communication health. The UI should show only supported controls. A second manufacturer should require a new adapter and profile, without changing fleet scheduling or customer pages.

One customer role can remain throughout this design. Ownership of organizations and sites is a data boundary, not a second operating mode.

## Recommended sequence and acceptance evidence

1. Commission the DSE8620 adapter against the external simulator contract and then the exact panel documentation. Verify measured values and requested/observed command states, disconnection behavior and controller operating modes.
2. Add organization ownership and explicit site context, with tests showing that independent customers cannot read or command each other's equipment and that two sessions can safely use different sites.
3. Separate gateway execution from the API. Demonstrate that adding API replicas does not duplicate panel polling or commands, and that a WAN outage leaves the local gateway and panels operating as designed.
4. Add durable command outcomes, telemetry history and regional calendar handling. Test command timeouts, restarts, clock/timezone boundaries and period report accuracy.
5. Establish deployment capacity with representative panels, polling intervals, WAN latency and concurrent customers. Measure command latency, telemetry age, database growth and recovery behavior. Set supported limits from those results.

Validation for this update: 28 backend tests pass, including the legacy-schema upgrade, customer controls, deletion cascades, cross-site preservation and account preservation. The frontend production build passes. The project SQLite database was backed up, upgraded and checked: integrity is `ok` and foreign-key violations are zero. No connection to the user's external simulator or physical controller was made.
