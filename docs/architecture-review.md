# Architecture review — customer generator fleet platform

Reviewed 12 September 2026 against the current source, SQLite upgrade path, API tests and frontend build.

The application is a useful foundation for a customer installation. It can evolve into a global product, but it is not currently a shared, horizontally scalable cloud platform. No measured fleet-size, concurrent-user or availability limit has been established; tests with a few generators are not capacity evidence.

## Product boundary

The customer has one interface with full supervisory controls. The controller performs synchronization, voltage/frequency matching, breaker sequencing and electrical protection. A controller adapter should express requests supported by that panel and interpret its feedback; the application should not implement synchronization algorithms.

DSE distinguishes the original DSE8620 from the DSE8620 MKII. The MKII is described as synchronizing one genset with utility power, with an option to operate as a DSE8610 MKII for generator-to-generator load sharing. The exact variant and configured topology therefore matter. [DSE8620](https://www.deepseaelectronics.com/genset/load-sharing-synchronising-control-modules/dse8620), [DSE8620 MKII](https://www.deepseaelectronics.com/genset/load-sharing-synchronising-control-modules/dse8620-mkii).

The checked-in map now implements the supplied GenComm 2.236 MF register contract: zero-based page/offset addresses, signed and unsigned word handling, engineering scaling, packed alarm condition codes, and atomic control-key writes. Physical feedback and model-specific optional registers still require validation against the external simulator and commissioned controller firmware.

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
| Multiple panel types | Each generator stores a controller profile. The gateway builds a profile-filtered map and adapter per panel, while the API publishes the profile catalogue to the UI. | The boundary now scales to additional DSE families and future vendors without changing fleet rules. Each new profile still needs a tested map, command encoding and capability declaration. |
| Customer isolation | All users now have full installation access. `api/sites.py` lists all sites; `User.site_id` stores the active site. There is no customer organization or site membership model. | This is appropriate for one customer's deployment. A shared service needs `organization_id` ownership and memberships before unrelated customers share a database. Full customer access must mean access to that customer's assets. |
| Multiple backend workers | `main.py` starts a gateway and APScheduler in every FastAPI lifespan. Gateway state, cooldowns, rules and WebSocket connections live in process memory. | Scaling the API to several workers would create multiple controllers of the same equipment. Separate the web API from site gateway workers and establish exclusive ownership of each gateway/device. |
| Regional connectivity | The API process directly opens TCP/serial connections to every configured panel. | Place device communication and supervisory scheduling in an on-site gateway. Connect it outward to the central service using an authenticated encrypted channel, with local operation during WAN loss and buffered event delivery. |
| Polling capacity | `_poll_loop` gathers all panels in one cycle, waits for the slowest task, then sleeps. Individual status points are read sequentially. YAML poll groups are parsed but not used by the gateway's read loop. RTU clients are created per panel. | Benchmark with representative latency and failures. Use bounded polling, grouped register reads, separate sampling intervals and one serialized connection owner per shared serial bus. |
| Command coordination | Cooldowns and intents are local dictionaries. Reads, manual commands and rule actions share device connections. `_with_retry` retries both reads and writes. | Add per-device command serialization, durable command IDs and explicit requested/acknowledged/confirmed/failed/unknown states. A write timeout requires adapter-specific reconciliation before a retry. |
| Active-site consistency | REST authorization reads the user's mutable database `site_id`; the WebSocket chooses a site from token claims. Switching site updates the user row. | Two browser sessions for the same user can disagree about which site a command targets. Use an explicit request/site context validated against organization membership consistently across REST, refresh and WebSockets. |
| Historical reporting | `api/reports.py` uses live lifetime counters and at most 200 events. Its average/peak load values derive from current telemetry, including a fallback estimate. `rules_reconstruct_threshold_state` also examines only 200 events. | These are not complete period analytics or reliable fleet-wide reconstruction. Store telemetry/counter history, aggregate by site/time, paginate audit reads and persist automation state independently of a short event window. |
| International behavior | Weekly schedules use site timezones, but `_pick_backup` chooses the weekday in UTC. Schedule exceptions build naive server-local datetimes. Frontend day labels use browser time; the site picker has a short timezone list. | Use the site's IANA timezone for all operational calendar decisions and UTC for storage. Add timezone validation, DST/boundary tests, locale formatting, translation and RTL support where needed. |
| Production operation | Compose exposes HTTP services; the WebSocket token is placed in the URL and validated at connection time. There are no capacity tests or central gateway ownership/health services. | Add TLS, short-lived stream credentials, account lifecycle controls, metrics, backup/restore verification and supported deployment targets. Docker execution and PostgreSQL behavior were not exercised in this environment. |

## Implementation progress — 13 September 2026

The first global-readiness foundations are now implemented:

- Each generator selects a controller profile. GenComm profiles cover the DSE families named in the supplied standard, and telemetry is normalized before it reaches fleet rules, reports or the UI.
- The gateway reads every configured read-only measurement, exposes engineering units, honors the register map's sampling groups, and serializes panel I/O so polling cannot overlap a command on the same connection.
- Telemetry history is stored per generator at a configurable retention sampling interval. This replaces live-value estimates for the new preventive-maintenance analysis.
- A per-generator preventive-maintenance report analyzes coolant temperature, oil pressure, battery voltage, fuel, frequency, load, alarms and service-hour proximity. It shows explainable findings and exports separately for each generator.
- Organizations now form the customer data boundary. Site lists, updates, deletion, switching, REST access and WebSocket access are checked against the signed-in customer's organization.
- Active-site selection is session-local rather than a mutable account-wide setting, so two browser sessions can safely work with different sites.
- Daily backup priority, weekly schedule display and schedule exceptions now use the site's IANA timezone.

Still required before calling the product globally deployable:

- Validate the implemented GenComm map and each enabled optional point against the external simulator and actual controller firmware before hardware commissioning.
- Deploy and exercise the separated central API/site-gateway topology over a real WAN. Database-backed telemetry and command buffering are implemented; a future message transport can reduce live-stream latency at very large scale.
- Establish measured supported limits using representative panels, WAN latency and customer concurrency. A repeatable capacity probe is included, but synthetic local results are not a production capacity guarantee.
- Configure TLS termination and perform scheduled PostgreSQL backup/restore drills in the target hosting environment. HTTPS enforcement, security headers, health checks, metrics, and a verified SQLite backup utility are now available.
- Add long-term hourly/daily telemetry rollups if retention beyond the configured raw-history window is required.

The second implementation pass also delivered:

- Separate `api`, `gateway`, and local `combined` runtime modes. Production Compose runs two API workers without device connections and a gateway worker for control.
- Renewable database facility leases, preventing duplicate gateway workers from polling or commanding the same site.
- A durable database command queue and lifecycle states: queued, requested, dispatching, acknowledged, confirmed, rejected, failed and unknown. Start/stop confirmation comes from observed controller state; ambiguous writes are not blindly retried.
- Database-backed live-stream fallback for separated API workers and two-minute WebSocket-only credentials rather than access tokens in URLs.
- Maintenance completion records, per-generator service intervals, and configurable sensor warning limits.
- Period report aggregation from stored telemetry instead of invented load estimates.
- Raw-history retention, Prometheus-format process metrics, readiness checks, security headers, optional HTTPS redirect, English/Arabic navigation and RTL layout support.
- Repeatable SQLite backup verification and an authenticated API capacity probe.

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

Validation is maintained in the automated API, migration, controller-map, rules and cooldown suite. Hardware commissioning and target-environment capacity evidence remain external acceptance activities.
