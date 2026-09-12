"""API regressions for full customer controls and generator lifecycle cleanup."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.auth.models import User
from app.auth.service import create_access_token, hash_password
from app.db.session import async_session_factory, engine
from app.dependencies import get_gateway, get_rules_engine
from app.main import create_app, seed_initial_data
from app.models.base import Base
from app.models.daily_priority import DailyPriority
from app.models.event import Event
from app.models.override import Override
from app.models.panel import Panel
from app.models.power_setpoint import PowerSetpoint
from app.models.release_threshold import ReleaseThreshold
from app.models.schedule import Schedule
from app.models.schedule_exception import ScheduleException
from app.models.site import Site
from app.models.start_threshold import StartThreshold
from app.models.threshold import Threshold
from app.modbus.gateway import ModbusGateway
from app.rules.engine import RulesEngine


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        session.add_all([
            Site(id="site_1", name="Test Facility", timezone="UTC", max_parallel_units=3),
            Site(id="site_2", name="Second Facility", timezone="Asia/Riyadh"),
        ])
        await session.flush()
        session.add(User(
            id="user_customer", email="customer@test.com",
            password_hash=hash_password("pass123"), full_name="Test Customer",
            role="customer", site_id="site_1",
        ))
        session.add_all([
            Panel(id="p1", site_id="site_1", name="Test Generator 1",
                  transport_type="tcp", address="127.0.0.1:15020", unit_id=1,
                  rated_kw=500, rated_kvar=150, priority=1),
            Panel(id="other_panel", site_id="site_2", name="Other Generator",
                  transport_type="tcp", address="127.0.0.1:15021", unit_id=1,
                  rated_kw=500, rated_kvar=150, priority=1),
        ])
        await session.commit()
    yield


@pytest.fixture
def app():
    application = create_app()
    gateway = Mock(spec=ModbusGateway)
    gateway.states = {}
    gateway.read_all_registers.return_value = {"engine_status": 3}
    gateway.send_remote_start.return_value = (True, "Start requested")
    gateway.send_remote_stop.return_value = (True, "Stop requested")
    gateway.write_power_setpoint.return_value = (True, "Setpoint requested")
    rules = Mock(spec=RulesEngine)
    application.dependency_overrides[get_gateway] = lambda: gateway
    application.dependency_overrides[get_rules_engine] = lambda: rules
    return application


@pytest.fixture
def headers():
    token = create_access_token({"sub": "user_customer", "role": "customer", "site_id": "site_1"})
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.asyncio
async def test_customer_can_login_refresh_and_read_profile(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        login = await ac.post("/auth/login", json={"email": "customer@test.com", "password": "pass123"})
        assert login.status_code == 200
        assert login.json()["role"] == "customer"
        refresh = await ac.post("/auth/refresh", json={"refresh_token": login.json()["refresh_token"]})
        assert refresh.status_code == 200
        assert refresh.json()["role"] == "customer"
        profile = await ac.get("/auth/me", headers={"Authorization": f"Bearer {refresh.json()['access_token']}"})
        assert profile.status_code == 200
        assert profile.json()["role"] == "customer"


@pytest.mark.asyncio
async def test_customer_has_diagnostics_overrides_and_setpoints(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        diagnostic = await ac.get("/diagnostics/panels/p1/raw", headers=headers)
        assert diagnostic.status_code == 200
        assert diagnostic.json()["registers"] == {"engine_status": 3}
        override = await ac.post("/diagnostics/panels/p1/override", headers=headers, json={
            "panel_id": "p1", "override_type": "force_start", "duration_minutes": 5,
        })
        assert override.status_code == 200
        assert (await ac.delete("/diagnostics/panels/p1/override", headers=headers)).status_code == 200
        setpoint = await ac.put("/setpoints/p1", headers=headers, json={
            "panel_id": "p1", "target_kw_pct": 60, "target_kvar_pct": 0, "is_active": True,
        })
        assert setpoint.status_code == 200
        assert (await ac.patch("/panels/p1", headers=headers, json={"name": "Renamed"})).status_code == 200


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/panels", "/sites", "/diagnostics/panels/p1/raw", "/thresholds/start", "/setpoints/p1"])
async def test_login_is_still_required(app, path):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        assert (await ac.get(path)).status_code == 401


@pytest.mark.asyncio
async def test_customer_can_manage_and_switch_installation_sites(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        created = await ac.post("/sites", headers=headers, json={"name": "New Facility"})
        assert created.status_code == 201
        site_id = created.json()["id"]
        assert len((await ac.get("/sites", headers=headers)).json()) == 3
        assert (await ac.patch(f"/sites/{site_id}", headers=headers, json={"timezone": "Asia/Riyadh"})).status_code == 200
        # Generator endpoints are scoped to the selected site even though the
        # same customer can deliberately switch to any installation site.
        assert (await ac.delete("/panels/other_panel", headers=headers)).status_code == 404
        switched = await ac.post("/sites/switch/site_2", headers=headers)
        assert switched.status_code == 200
        new_headers = {"Authorization": f"Bearer {switched.json()['access_token']}"}
        assert [p["id"] for p in (await ac.get("/panels", headers=new_headers)).json()] == ["other_panel"]
        assert (await ac.delete(f"/sites/{site_id}", headers=new_headers)).status_code == 204


@pytest.mark.asyncio
async def test_delete_site_preserves_all_customer_accounts_and_unregisters_generators(app, headers):
    async with async_session_factory() as session:
        session.add(User(id="colleague", email="colleague@test.com", password_hash="unchanged",
                         full_name="Colleague", role="customer", site_id="site_1"))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.get("/thresholds/start", headers=headers)
        await ac.get("/thresholds/release", headers=headers)
        assert (await ac.delete("/sites/site_1", headers=headers)).status_code == 204
        assert (await ac.delete("/sites/site_2", headers=headers)).status_code == 400
    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        assert len(users) == 2
        assert all(user.site_id == "site_2" for user in users)
        assert await session.get(Panel, "p1") is None
        assert (await session.execute(select(StartThreshold))).scalars().all() == []
        assert (await session.execute(select(ReleaseThreshold))).scalars().all() == []
    app.dependency_overrides[get_gateway]().remove_panel.assert_called_once_with("p1")


@pytest.mark.asyncio
async def test_threshold_validation_rejects_inverted_hysteresis(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.put("/thresholds", headers=headers, json={
            "start_pct": 70, "stop_pct": 80, "dwell_seconds": 120,
        })
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_per_generator_thresholds_allow_customer_ordered_overlap(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.get("/thresholds/start", headers=headers)
        await ac.get("/thresholds/release", headers=headers)

        overlapping_start = await ac.put("/thresholds/start", headers=headers, json={
            "thresholds": [{"panel_id": "p1", "start_pct": 50, "priority_order": 1}],
        })
        assert overlapping_start.status_code == 200
        assert overlapping_start.json()[0]["start_pct"] == 50

        overlapping_release = await ac.put("/thresholds/release", headers=headers, json={
            "thresholds": [{"panel_id": "p1", "release_pct": 70, "priority_order": 1}],
        })
        assert overlapping_release.status_code == 200
        assert overlapping_release.json()[0]["release_pct"] == 70


@pytest.mark.asyncio
async def test_delete_generator_removes_all_settings_and_preserves_other_site(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        ids = []
        for number in (2, 3):
            response = await ac.post("/panels", headers=headers, json={
                "name": f"Generator {number}", "transport_type": "tcp",
                "address": "127.0.0.1:15020", "unit_id": number, "rated_kw": 500,
            })
            assert response.status_code == 201
            ids.append(response.json()["id"])
        deleted_id, survivor_id = ids
        # Seed defaults also for the original generator.
        assert (await ac.get("/thresholds", headers=headers)).status_code == 200
        assert len((await ac.get("/thresholds/start", headers=headers)).json()) == 3
        assert len((await ac.get("/thresholds/release", headers=headers)).json()) == 3

        async with async_session_factory() as session:
            session.add_all([
                Schedule(site_id="site_1", panel_id=deleted_id, day_of_week=0, start_time="07:00", end_time="18:00"),
                ScheduleException(site_id="site_1", panel_id=deleted_id, exception_date=date.today(), is_active=False),
                Threshold(site_id="site_1", panel_id=deleted_id, start_pct=80, stop_pct=40, dwell_seconds=120),
                PowerSetpoint(site_id="site_1", panel_id=deleted_id, target_kw_pct=60),
                Override(site_id="site_1", panel_id=deleted_id, override_type="force_start",
                         created_by="user_customer", expires_at=datetime.now(timezone.utc) + timedelta(hours=1)),
                Event(id="audit_1", site_id="site_1", panel_id=deleted_id, event_type="command_sent",
                      triggered_by="manual", user_id="user_customer"),
                StartThreshold(id="other_start", site_id="site_2", panel_id="other_panel", start_pct=85),
                ReleaseThreshold(id="other_release", site_id="site_2", panel_id="other_panel", release_pct=35),
            ])
            await session.commit()

        assert (await ac.delete(f"/panels/{deleted_id}", headers=headers)).status_code == 204
        assert (await ac.delete(f"/panels/{deleted_id}", headers=headers)).status_code == 404
        for endpoint in ("/thresholds/start", "/thresholds/release"):
            rows = (await ac.get(endpoint, headers=headers)).json()
            assert {r["panel_id"] for r in rows} == {"p1", survivor_id}
            assert {r["panel_id"]: r["priority_order"] for r in rows} == {"p1": 1, survivor_id: 2}
        # Old installations may lack rows for the original generator. Complete
        # each day while compacting to avoid duplicate fallback priorities.
        daily = (await ac.get("/panels/priorities/daily", headers=headers)).json()
        assert len(daily) == 14
        for day in range(7):
            assert {r["panel_id"]: r["priority"] for r in daily if r["day_of_week"] == day} == {
                "p1": 1, survivor_id: 2,
            }

        async with async_session_factory() as session:
            for model in (StartThreshold, ReleaseThreshold, Threshold, Schedule, ScheduleException,
                          DailyPriority, PowerSetpoint, Override):
                assert (await session.execute(select(model).where(model.panel_id == deleted_id))).scalars().all() == []
            assert (await session.get(Event, "audit_1")).panel_id is None
            assert (await session.get(Event, "audit_1")).user_id == "user_customer"
            assert (await session.get(StartThreshold, "other_start")).start_pct == 85
            assert (await session.get(ReleaseThreshold, "other_release")).release_pct == 35
            assert (await session.execute(select(Threshold).where(Threshold.panel_id.is_(None)))).scalars().one()

        # Removing the final generators must leave no phantom threshold controls.
        for panel_id in ("p1", survivor_id):
            assert (await ac.delete(f"/panels/{panel_id}", headers=headers)).status_code == 204
        assert (await ac.get("/thresholds/start", headers=headers)).json() == []
        assert (await ac.get("/thresholds/release", headers=headers)).json() == []


@pytest.mark.asyncio
async def test_sqlite_foreign_keys_cascade_without_api_cleanup(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        await ac.get("/thresholds/start", headers=headers)
        await ac.get("/thresholds/release", headers=headers)
    async with async_session_factory() as session:
        await session.execute(delete(Panel).where(Panel.id == "p1"))
        await session.commit()
        for model in (StartThreshold, ReleaseThreshold):
            assert (await session.execute(select(model).where(model.panel_id == "p1"))).scalars().all() == []


@pytest.mark.asyncio
async def test_bootstrap_creates_one_customer_and_no_simulated_generators(monkeypatch):
    from app.config import settings
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    monkeypatch.setattr(settings, "bootstrap_admin_email", "owner@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", "long-bootstrap-password")
    await seed_initial_data()
    await seed_initial_data()
    async with async_session_factory() as session:
        users = (await session.execute(select(User))).scalars().all()
        assert len(users) == 1 and users[0].role == "customer"
        assert (await session.execute(select(Panel))).scalars().all() == []
        assert (await session.execute(select(Schedule))).scalars().all() == []


@pytest.mark.asyncio
async def test_reports_summary_and_csv_export(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        summary = await ac.get("/reports/summary?period=30d", headers=headers)
        assert summary.status_code == 200
        assert len(summary.json()["generators"]) == 1
        exported = await ac.get("/reports/export?period=30d", headers=headers)
        assert exported.status_code == 200
        assert "Test Generator 1" in exported.text
