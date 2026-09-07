"""FastAPI Application Factory, Lifespan Handler, and Service Orchestration."""

import asyncio
from contextlib import asynccontextmanager
import logging
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select

from app.api.diagnostics import router as diagnostics_router
from app.api.events import router as events_router
from app.api.panels import router as panels_router
from app.api.reports import router as reports_router
from app.api.schedules import router as schedules_router
from app.api.setpoints import router as setpoints_router
from app.api.sites import router as sites_router
from app.api.thresholds import router as thresholds_router
from app.api.ws import router as ws_router, ws_manager
from app.auth.models import User
from app.auth.router import router as auth_router
from app.auth.service import hash_password
from app.config import settings
from app.db.session import async_session_factory, engine
from app.models.base import Base
from app.models.event import Event
from app.models.override import Override
from app.models.panel import Panel
from app.models.schedule import Schedule
from app.models.site import Site
from app.models.threshold import Threshold
from app.modbus.gateway import ModbusGateway
from app.modbus.panel_state import PanelState
from app.rules.engine import RulesEngine

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("scada")

# Global singletons
gateway_instance: ModbusGateway | None = None
rules_engine_instance: RulesEngine | None = None


async def seed_initial_data():
    """Seed a default site, panels, and initial user accounts if database is empty."""
    async with async_session_factory() as session:
        # Check if site exists
        site_res = await session.execute(select(Site))
        site = site_res.scalars().first()

        if not site:
            logger.info("Database empty — seeding demo site, panels, and users...")
            site = Site(
                name="Main Facility - Building A",
                address="100 Industrial Parkway, Sector 4",
                timezone="UTC",
                max_parallel_units=3,
            )
            session.add(site)
            await session.flush()

            # Seed Customer user (single unified view with full control)
            customer = User(
                email="customer@example.com",
                password_hash=hash_password("customer123"),
                full_name="Facility Manager",
                role="technician",
                site_id=site.id,
            )
            # Seed Technician user
            technician = User(
                email="tech@example.com",
                password_hash=hash_password("tech123"),
                full_name="Lead Power Engineer",
                role="technician",
                site_id=site.id,
            )
            session.add_all([customer, technician])

            # Seed Panels corresponding to the mock Modbus server
            p1 = Panel(
                site_id=site.id,
                name="Generator 1 (Base Load)",
                transport_type="tcp",
                address=f"{settings.mock_modbus_host}:{settings.mock_modbus_port}",
                unit_id=1,
                rated_kw=500.0,
                rated_kvar=150.0,
                priority=1,
            )
            p2 = Panel(
                site_id=site.id,
                name="Generator 2 (Secondary)",
                transport_type="tcp",
                address=f"{settings.mock_modbus_host}:{settings.mock_modbus_port}",
                unit_id=2,
                rated_kw=750.0,
                rated_kvar=225.0,
                priority=2,
            )
            p3 = Panel(
                site_id=site.id,
                name="Generator 3 (Standby)",
                transport_type="tcp",
                address=f"{settings.mock_modbus_host}:{settings.mock_modbus_port}",
                unit_id=3,
                rated_kw=500.0,
                rated_kvar=150.0,
                priority=3,
            )
            session.add_all([p1, p2, p3])
            await session.flush()

            # Seed default threshold
            thresh = Threshold(
                site_id=site.id,
                panel_id=None,
                start_pct=70.0,
                stop_pct=50.0,
                dwell_seconds=120,
            )
            session.add(thresh)

            # Seed initial schedule (Gen 1 on duty Mon-Fri)
            for day in range(5):
                sched = Schedule(
                    site_id=site.id,
                    panel_id=p1.id,
                    day_of_week=day,
                    start_time="07:00",
                    end_time="19:00",
                    is_active=True,
                )
                session.add(sched)

            await session.commit()
            logger.info("Seed complete. Credentials: customer@example.com / customer123, tech@example.com / tech123")


async def log_event_to_db(
    panel_id: str | None = None,
    event_type: str = "system",
    command: str | None = None,
    value: str | None = None,
    triggered_by: str = "system",
    reason: str | None = None,
    previous_state: str | None = None,
    new_state: str | None = None,
    load_kw_at_decision: float | None = None,
    capacity_pct_at_decision: float | None = None,
    command_result: str | None = None,
    user_id: str | None = None,
):
    """Callback passed to ModbusGateway to record events to the database."""
    try:
        async with async_session_factory() as session:
            # Determine site_id from panel if panel_id is given
            site_id = None
            if panel_id:
                p = await session.get(Panel, panel_id)
                if p:
                    site_id = p.site_id
            if not site_id:
                s_res = await session.execute(select(Site))
                s = s_res.scalars().first()
                if s:
                    site_id = s.id

            if not site_id:
                return

            evt = Event(
                site_id=site_id,
                panel_id=panel_id,
                event_type=event_type,
                command=command,
                value=value,
                triggered_by=triggered_by,
                reason=reason,
                previous_state=previous_state,
                new_state=new_state,
                load_kw_at_decision=load_kw_at_decision,
                capacity_pct_at_decision=capacity_pct_at_decision,
                command_result=command_result,
                user_id=user_id,
                timestamp=datetime.now(timezone.utc),
            )
            session.add(evt)
            await session.commit()
    except Exception as exc:
        logger.error("Failed to log event to DB: %s", exc)


def handle_panel_state_update(panel_id: str, state: PanelState):
    """Callback fired on every gateway poll — broadcasts telemetry via WebSocket."""
    asyncio.create_task(broadcast_state_update(panel_id, state))


async def broadcast_state_update(panel_id: str, state: PanelState):
    """Find site_id for panel and push to active WebSocket connections."""
    try:
        from app.api.ws import ws_manager
        site_id = state.site_id
        if site_id:
            await ws_manager.broadcast_to_site(
                site_id,
                {
                    "type": "panel_update",
                    "panel_id": panel_id,
                    "state": state.to_dict(),
                    "timestamp": datetime.now(timezone.utc).isoformat(),
                },
            )
    except Exception as exc:
        logger.error("Error in broadcast_state_update: %s", exc)


# ── Rules Engine Data Accessors ──────────────────────────────────────────
async def rules_get_schedules():
    async with async_session_factory() as session:
        stmt = (
            select(Schedule, Site.timezone)
            .join(Site, Schedule.site_id == Site.id)
            .where(Schedule.is_active.is_(True))
        )
        res = await session.execute(stmt)
        rows = res.all()
        return [
            {
                "id": s.id,
                "site_id": s.site_id,
                "panel_id": s.panel_id,
                "day_of_week": s.day_of_week,
                "start_time": s.start_time,
                "end_time": s.end_time,
                "is_active": s.is_active,
                "timezone": tz or "UTC",
            }
            for s, tz in rows
        ]


async def rules_get_schedule_exceptions():
    async with async_session_factory() as session:
        from app.models.schedule_exception import ScheduleException
        res = await session.execute(select(ScheduleException))
        exceptions = res.scalars().all()
        return [
            {
                "id": e.id,
                "panel_id": e.panel_id,
                "exception_date": e.exception_date,
                "is_active": e.is_active,
                "start_time": e.start_time,
                "end_time": e.end_time,
            }
            for e in exceptions
        ]


async def rules_get_daily_priorities():
    async with async_session_factory() as session:
        from app.models.daily_priority import DailyPriority
        res = await session.execute(select(DailyPriority))
        priorities = res.scalars().all()
        return [
            {
                "panel_id": p.panel_id,
                "day_of_week": p.day_of_week,
                "priority": p.priority,
            }
            for p in priorities
        ]


async def rules_get_start_thresholds(site_id: str = None):
    """Get per-backup start thresholds, optionally filtered by site_id."""
    async with async_session_factory() as session:
        from app.models.start_threshold import StartThreshold
        stmt = select(StartThreshold)
        if site_id:
            stmt = stmt.where(StartThreshold.site_id == site_id)
        res = await session.execute(stmt)
        sts = res.scalars().all()
        return [
            {
                "panel_id": st.panel_id,
                "site_id": st.site_id,
                "start_pct": st.start_pct,
                "priority_order": st.priority_order,
            }
            for st in sts
        ]
async def rules_get_release_thresholds(site_id: str = None):
    """Get per-backup release thresholds, optionally filtered by site_id."""
    async with async_session_factory() as session:
        from app.models.release_threshold import ReleaseThreshold
        stmt = select(ReleaseThreshold)
        if site_id:
            stmt = stmt.where(ReleaseThreshold.site_id == site_id)
        res = await session.execute(stmt)
        rts = res.scalars().all()
        return [
            {
                "panel_id": rt.panel_id,
                "site_id": rt.site_id,
                "release_pct": rt.release_pct,
                "priority_order": rt.priority_order,
            }
            for rt in rts
        ]

async def rules_get_thresholds():
    async with async_session_factory() as session:
        res = await session.execute(select(Threshold))
        thresholds = res.scalars().all()
        return [
            {
                "id": t.id,
                "site_id": t.site_id,
                "panel_id": t.panel_id,
                "start_pct": t.start_pct,
                "stop_pct": t.stop_pct,
                "dwell_seconds": t.dwell_seconds,
            }
            for t in thresholds
        ]


async def rules_get_overrides(panel_id: str):
    async with async_session_factory() as session:
        res = await session.execute(
            select(Override).where(
                Override.panel_id == panel_id,
                Override.is_active.is_(True),
            )
        )
        overrides = res.scalars().all()
        return [
            {
                "id": o.id,
                "is_active": o.is_active,
                "expires_at": o.expires_at,
                "override_type": o.override_type,
            }
            for o in overrides
        ]


async def rules_get_site(site_id: str):
    async with async_session_factory() as session:
        site = await session.get(Site, site_id)
        if site:
            return {
                "id": site.id,
                "name": site.name,
                "timezone": site.timezone,
                "max_parallel_units": site.max_parallel_units,
            }
        return None


async def rules_get_panel(panel_id: str):
    async with async_session_factory() as session:
        panel = await session.get(Panel, panel_id)
        if panel:
            return {
                "id": panel.id,
                "priority": panel.priority,
                "rated_kw": panel.rated_kw,
                "maintenance_mode": panel.maintenance_mode,
                "lead_rotation_order": panel.lead_rotation_order,
            }
        return None


async def rules_reconstruct_threshold_state():
    """Return dict of panel_id -> datetime for panels currently started by threshold rules."""
    async with async_session_factory() as session:
        # Get the latest command event for each panel
        # A bit complex in SQL, but we can just fetch the last 100 events and figure it out
        from sqlalchemy import desc
        res = await session.execute(
            select(Event).where(Event.event_type == "command_sent").order_by(desc(Event.timestamp)).limit(200)
        )
        events = res.scalars().all()
        
        latest_commands = {}
        for evt in events:
            if evt.panel_id and evt.panel_id not in latest_commands:
                latest_commands[evt.panel_id] = evt
                
        threshold_started = {}
        for panel_id, evt in latest_commands.items():
            # If the last command was a start triggered by threshold or dispatcher
            if evt.command == "remote_start" and evt.triggered_by in ("threshold", "dispatcher"):
                threshold_started[panel_id] = evt.timestamp
                
        return threshold_started


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan: database setup, background services, graceful shutdown."""
    global gateway_instance, rules_engine_instance

    logger.info("Initializing SCADA Gateway Backend...")

    # 1. Initialize tables (dev auto-creation)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # 2. Seed default data if needed
    await seed_initial_data()

    # 3. Initialize Modbus Gateway
    gateway_instance = ModbusGateway()
    gateway_instance.set_event_logger(log_event_to_db)
    gateway_instance.on_state_update(handle_panel_state_update)

    # Load panels from DB into gateway
    async with async_session_factory() as session:
        res = await session.execute(select(Panel))
        panels = res.scalars().all()
        for p in panels:
            gateway_instance.add_panel(
                panel_id=p.id,
                site_id=p.site_id,
                name=p.name,
                transport_type=p.transport_type,
                address=p.address,
                unit_id=p.unit_id,
            )

    # 4. Initialize Rules Engine
    rules_engine_instance = RulesEngine(gateway_instance)
    rules_engine_instance.set_data_accessors(
        get_schedules=rules_get_schedules,
        get_schedule_exceptions=rules_get_schedule_exceptions,
        get_thresholds=rules_get_thresholds,
        get_overrides=rules_get_overrides,
        get_site=rules_get_site,
        get_threshold_state=rules_reconstruct_threshold_state,
        get_panel=rules_get_panel,
        get_release_thresholds=rules_get_release_thresholds,
        get_start_thresholds=rules_get_start_thresholds,
    )
    rules_engine_instance._get_daily_priorities = rules_get_daily_priorities

    # Reconcile actual panel states before starting rules
    await gateway_instance.reconcile_panel_states()

    # Load initial schedules into rules engine
    initial_scheds = await rules_get_schedules()
    await rules_engine_instance.load_schedules(initial_scheds)

    # Start gateway poll loop & rules engine scheduler
    await gateway_instance.start()
    await rules_engine_instance.start()

    logger.info("SCADA Gateway Backend is online and running.")

    try:
        yield
    finally:
        logger.info("Shutting down SCADA Gateway Backend...")
        if rules_engine_instance:
            await rules_engine_instance.stop()
        if gateway_instance:
            await gateway_instance.stop()
        await engine.dispose()
        logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="DSE Generator Fleet Gateway",
        description="Middleware gateway and load-management orchestration for DSE generator panels",
        version="1.0.0",
        lifespan=lifespan,
    )

    # CORS configuration for frontend
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Include Routers
    app.include_router(auth_router)
    app.include_router(sites_router)
    app.include_router(panels_router)
    app.include_router(schedules_router)
    app.include_router(thresholds_router)
    app.include_router(setpoints_router)
    app.include_router(events_router)
    app.include_router(diagnostics_router)
    app.include_router(reports_router)
    app.include_router(ws_router)

    @app.get("/health")
    async def health_check():
        return {
            "status": "healthy",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "gateway_running": gateway_instance._running if gateway_instance else False,
            "connected_panels": len(gateway_instance.states) if gateway_instance else 0,
        }

    return app


app = create_app()
