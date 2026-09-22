"""API regressions for full customer controls and generator lifecycle cleanup."""

from datetime import date, datetime, timedelta, timezone
from unittest.mock import Mock

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select

from app.auth.models import User
from app.auth.service import create_access_token, hash_password
from app.auth.service import decode_token
from app.db.session import async_session_factory, engine
from app.dependencies import get_gateway, get_rules_engine
from app.main import create_app, seed_initial_data
from app.models.base import Base
from app.models.daily_priority import DailyPriority
from app.models.event import Event
from app.models.override import Override
from app.models.organization import Organization
from app.models.panel import Panel
from app.models.power_setpoint import PowerSetpoint
from app.models.release_threshold import ReleaseThreshold
from app.models.schedule import Schedule
from app.models.schedule_exception import ScheduleException
from app.models.site import Site
from app.models.start_threshold import StartThreshold
from app.models.threshold import Threshold
from app.models.telemetry_sample import TelemetrySample
from app.models.maintenance_task import MaintenanceFindingRecord, MaintenanceTask
from app.models.maintenance_record import MaintenanceRecord
from app.services.maintenance import emit_due_events


@pytest.mark.asyncio
async def test_dispatch_choice_defaults_to_legacy_and_measurements_are_scoped(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        current = await ac.get("/sites/site_1/dispatch", headers=headers)
        assert current.status_code == 200
        assert current.json()["config"]["mode"] == "legacy"
        invalid = await ac.patch("/sites/site_1/dispatch", headers=headers,
                                 json={"mode": "automatic", "topology_verified": False})
        assert invalid.status_code == 422
        saved = await ac.patch("/sites/site_1/dispatch", headers=headers,
                               json={"mode": "advisory", "grid_present": True})
        assert saved.status_code == 200, saved.text
        reading = {"measured_at": datetime.now(timezone.utc).isoformat(), "load_kw": 120,
                   "solar_kw": 25, "grid_kw": 95, "grid_connected": True, "bus_energized": True}
        assert (await ac.post("/sites/site_1/dispatch/measurement", headers=headers, json=reading)).status_code == 200
        stored = (await ac.get("/sites/site_1/dispatch", headers=headers)).json()
        assert stored["measurement_fresh"]
        assert stored["measurement"]["grid_kw"] == 95
        assert (await ac.get("/sites/other_customer_site/dispatch", headers=headers)).status_code == 404
from app.modbus.gateway import ModbusGateway
from app.rules.engine import RulesEngine


@pytest.mark.asyncio
async def test_preventive_tasks_complete_independently_and_findings_await_measurement(app, headers):
    today = date.today().isoformat()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for component in ("oil", "fuel_filter"):
            created = await ac.post("/reports/maintenance/p1/tasks", headers=headers, json={
                "component": component, "name": component, "interval_hours": 250,
                "baseline_run_hours": 10, "interval_days": 180, "baseline_date": today,
                "manufacturer_reference": "Engine schedule",
            })
            assert created.status_code == 201, created.text
            if component == "oil":
                oil_id = created.json()["id"]
        before = await ac.get("/reports/maintenance/p1", headers=headers)
        assert before.status_code == 200, before.text
        assert before.json()["maintenance_compliance_percent"] is None
        assert before.json()["monitored_condition"] == "insufficient_data"
        assert (await ac.get("/reports/maintenance/other_panel", headers=headers)).status_code == 404
        completed = await ac.post("/reports/maintenance/p1/complete", headers=headers, json={
            "service_date": today, "run_hours": 20, "task_ids": [oil_id],
            "checklist_confirmed": True, "service_type": "Oil service",
        })
        assert completed.status_code == 201, completed.text
        after = (await ac.get("/reports/maintenance/p1", headers=headers)).json()
        tasks = {task["component"]: task for task in after["tasks"]}
        assert tasks["oil"]["next_due_run_hours"] == 270
        assert tasks["fuel_filter"]["next_due_run_hours"] == 260
        assert after["service_history"][0]["task_ids"] == [oil_id]

    now = datetime.now(timezone.utc)
    async with async_session_factory() as session:
        session.add(MaintenanceFindingRecord(
            id="finding-p1", site_id="site_1", panel_id="p1", metric="oil_pressure",
            severity="warning", title="Oil pressure falling", detail="Sustained decline",
            recommendation="Inspect lubrication", status="open", verification_kind="sensor",
            evidence={"baseline": 4.0, "trigger": 3.0, "direction": "down", "threshold": 0.5},
            first_detected_at=now, last_detected_at=now,
        ))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        work = await ac.post("/reports/maintenance/p1/findings/finding-p1/work", headers=headers,
                             json={"resolution_note": "Inspected and replaced filter"})
        assert work.status_code == 200, work.text
        assert work.json()["status"] == "awaiting_verification"
        assert (await ac.post("/reports/maintenance/p1/findings/finding-p1/verify", headers=headers,
                              json={"resolution_note": "Checked", "inspection_confirmed": True})).status_code == 422
        report = (await ac.get("/reports/maintenance/p1", headers=headers)).json()
        assert report["monitored_condition"] == "insufficient_data"
        assert report["findings"][0]["status"] == "awaiting_verification"


@pytest.mark.asyncio
async def test_due_service_event_is_idempotent_and_realerts_after_schedule_change(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        created = await ac.post("/reports/maintenance/p1/tasks", headers=headers, json={
            "component": "oil", "name": "Oil service", "interval_days": 30,
            "baseline_date": (date.today() - timedelta(days=29)).isoformat(),
        })
        assert created.status_code == 201, created.text
        task_id = created.json()["id"]
    async with async_session_factory() as session:
        await emit_due_events(session, "site_1")
        await session.commit()
        await emit_due_events(session, "site_1")
        await session.commit()
        events = (await session.execute(select(Event).where(
            Event.command == "maintenance_due", Event.value == task_id))).scalars().all()
        assert len(events) == 1
        task = await session.get(MaintenanceTask, task_id)
        task.name = "Oil and filter service"
        await session.commit()
        await emit_due_events(session, "site_1")
        await session.commit()
        events = (await session.execute(select(Event).where(
            Event.command == "maintenance_due", Event.value == task_id))).scalars().all()
        assert len(events) == 2


@pytest.mark.asyncio
async def test_fuel_reports_do_not_turn_missing_history_into_zero_consumption(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        for path in ("/reports/fuel", "/reports/efficiency"):
            response = await ac.get(path, headers=headers)
            assert response.status_code == 200, response.text
            assert response.json()["generators"][0]["fuel_litres"] is None
            assert response.json()["fleet"]["kwh_per_litre"] is None
            assert (await ac.get(path)).status_code == 401
        assert (await ac.get("/reports/fuel?panel_id=other_panel", headers=headers)).status_code == 404
        arabic = await ac.get("/reports/efficiency/export?locale=ar", headers=headers)
        assert arabic.status_code == 200
        assert "كفاءة المولد" in arabic.text


@pytest.mark.asyncio
async def test_fuel_api_and_csv_use_same_measured_values(app, headers):
    now = datetime.now(timezone.utc).replace(microsecond=0) - timedelta(minutes=7)
    async with async_session_factory() as session:
        for index in range(4):
            timestamp = now + timedelta(minutes=2 * index)
            values = {"fuel_used_litres": index * 5, "total_kwh": index * 15,
                      "run_hours": index / 30, "load_kw": 225, "load_kw_percent": 45}
            session.add(TelemetrySample(
                site_id="site_1", panel_id="p1", recorded_at=timestamp, is_reachable=True,
                engine_status="running", readings=values,
                reading_quality={key: "good" for key in values},
                reading_timestamps={key: timestamp.isoformat() for key in values},
                source_identity="commissioned-meter-1",
            ))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        report = await ac.get("/reports/efficiency?period=7d&panel_id=p1", headers=headers)
        assert report.status_code == 200, report.text
        generator = report.json()["generators"][0]
        assert generator["fuel_litres"] == 15
        assert generator["energy_kwh"] == 45
        assert generator["kwh_per_litre"] == 3
        csv_response = await ac.get("/reports/efficiency/export?period=7d&panel_id=p1&locale=en", headers=headers)
        assert csv_response.status_code == 200
        assert "Test Generator 1,15.0,45.0,15.0" in csv_response.text


@pytest.mark.asyncio
async def test_custom_report_dates_filter_overview_maintenance_and_exports(app, headers):
    today = datetime.now(timezone.utc).date()
    inside = today - timedelta(days=4)
    outside = today - timedelta(days=1)
    async with async_session_factory() as session:
        for identifier, day, hours, energy in (("old", inside, 4, 20), ("new", inside, 7, 40),
                                                ("excluded", outside, 20, 100)):
            session.add(TelemetrySample(id=identifier, site_id="site_1", panel_id="p1",
                recorded_at=datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=12),
                is_reachable=True, engine_status="running", run_hours=hours, total_kwh=energy,
                number_of_starts=hours))
        session.add_all([
            Event(id="inside_event", site_id="site_1", panel_id="p1", event_type="command_sent",
                  triggered_by="manual", reason="Inside range", timestamp=datetime.combine(inside, datetime.min.time(), timezone.utc)),
            Event(id="outside_event", site_id="site_1", panel_id="p1", event_type="command_sent",
                  triggered_by="manual", reason="Outside range", timestamp=datetime.combine(outside, datetime.min.time(), timezone.utc)),
            MaintenanceRecord(id="inside_service", site_id="site_1", panel_id="p1", service_date=inside,
                              run_hours=7, service_type="Oil service"),
            MaintenanceRecord(id="outside_service", site_id="site_1", panel_id="p1", service_date=outside,
                              run_hours=20, service_type="Filter service"),
        ])
        await session.commit()
    params = f"period=custom&start_date={inside.isoformat()}&end_date={inside.isoformat()}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        overview = await ac.get(f"/reports/summary?{params}", headers=headers)
        assert overview.status_code == 200, overview.text
        assert overview.json()["generators"][0]["run_hours"] == 3
        assert overview.json()["generators"][0]["total_kwh"] == 20
        assert [row["id"] for row in overview.json()["recent_sessions"]] == ["inside_event"]
        exported = await ac.get(f"/reports/export?{params}&locale=ar", headers=headers)
        assert exported.status_code == 200, exported.text
        assert "Inside range" in exported.text and "Outside range" not in exported.text
        assert "Test Generator 1,TCP" in exported.text
        maintenance = await ac.get(f"/reports/maintenance/p1?{params}", headers=headers)
        assert maintenance.status_code == 200, maintenance.text
        assert [row["id"] for row in maintenance.json()["service_history"]] == ["inside_service"]
        history_csv = await ac.get(f"/reports/preventive-maintenance/p1/records/export?{params}", headers=headers)
        assert "Oil service" in history_csv.text and "Filter service" not in history_csv.text
        assert (await ac.get("/reports/summary?period=custom", headers=headers)).status_code == 422


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    async with async_session_factory() as session:
        session.add_all([
            Organization(id="org_1", name="Test Customer"),
            Organization(id="org_2", name="Other Customer"),
        ])
        await session.flush()
        session.add_all([
            Site(id="site_1", organization_id="org_1", name="Test Facility", timezone="UTC", max_parallel_units=3),
            Site(id="site_2", organization_id="org_1", name="Second Facility", timezone="Asia/Riyadh"),
            Site(id="other_customer_site", organization_id="org_2", name="Private Facility", timezone="UTC"),
        ])
        await session.flush()
        session.add(User(
            id="user_customer", email="customer@test.com",
            password_hash=hash_password("pass123"), full_name="Test Customer",
            role="customer", site_id="site_1",
            organization_id="org_1",
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
        stream = await ac.get("/auth/stream-token", headers={"Authorization": f"Bearer {refresh.json()['access_token']}"})
        assert stream.status_code == 200
        assert decode_token(stream.json()["token"])["type"] == "stream"


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
        # The original browser session remains on its original site.
        assert [p["id"] for p in (await ac.get("/panels", headers=headers)).json()] == ["p1"]
        assert (await ac.delete(f"/sites/{site_id}", headers=new_headers)).status_code == 204


@pytest.mark.asyncio
async def test_customer_cannot_discover_or_switch_to_another_organization(app, headers):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        visible = await ac.get("/sites", headers=headers)
        assert {site["id"] for site in visible.json()} == {"site_1", "site_2"}
        assert (await ac.post("/sites/switch/other_customer_site", headers=headers)).status_code == 404
        invalid_tz = await ac.post("/sites", headers=headers, json={"name": "Bad timezone", "timezone": "Mars/Olympus"})
        assert invalid_tz.status_code == 422


@pytest.mark.asyncio
async def test_delete_site_preserves_all_customer_accounts_and_unregisters_generators(app, headers):
    async with async_session_factory() as session:
        session.add(User(id="colleague", email="colleague@test.com", password_hash="unchanged",
                         full_name="Colleague", role="customer", site_id="site_1", organization_id="org_1"))
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
        arabic_export = await ac.get("/reports/export?period=30d&locale=ar", headers=headers)
        assert arabic_export.status_code == 200
        assert arabic_export.content.startswith(b"\xef\xbb\xbf")
        assert "تقرير عمل أسطول المولدات" in arabic_export.text
        assert "ملخص أداء وعمل المولدات" in arabic_export.text
        assert "سجل نشاط العمل والمناوبة التشغيلية" in arabic_export.text


@pytest.mark.asyncio
async def test_audit_log_csv_export_and_filtered_clear_are_site_scoped(app, headers):
    async with async_session_factory() as session:
        session.add_all([
            Event(id="event_command", site_id="site_1", panel_id="p1", event_type="command_sent",
                  command="remote_start", value="ON", triggered_by="manual", reason="Test start"),
            Event(id="event_alarm", site_id="site_1", panel_id="p1", event_type="alarm_active",
                  value="low_oil_pressure", triggered_by="system", reason="Test alarm"),
            Event(id="event_other_site", site_id="site_2", panel_id="other_panel", event_type="command_sent",
                  command="remote_stop", value="ON", triggered_by="manual", reason="Private event"),
        ])
        await session.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        exported = await ac.get("/events/export?event_type=command_sent", headers=headers)
        assert exported.status_code == 200
        assert "Applied Filters" in exported.text
        assert "Event Type,command_sent" in exported.text
        assert "Generator,All Units" in exported.text
        assert "Test Generator 1" in exported.text
        assert "Test start" in exported.text
        assert "Private event" not in exported.text

        arabic_export = await ac.get("/events/export?panel_id=p1&event_type=command_sent&locale=ar", headers=headers)
        assert arabic_export.status_code == 200
        assert "عوامل التصفية المطبقة" in arabic_export.text
        assert "المولد,Test Generator 1" in arabic_export.text
        assert "نوع الحدث,تم إرسال أمر" in arabic_export.text
        assert "تشغيل عن بُعد" in arabic_export.text

        cleared = await ac.delete("/events?event_type=command_sent", headers=headers)
        assert cleared.status_code == 200
        assert cleared.json()["deleted_count"] == 1
        remaining = await ac.get("/events", headers=headers)
        assert [event["id"] for event in remaining.json()] == ["event_alarm"]

    async with async_session_factory() as session:
        assert await session.get(Event, "event_other_site") is not None


@pytest.mark.asyncio
async def test_preventive_maintenance_report_is_per_generator_and_exportable(app, headers):
    async with async_session_factory() as session:
        session.add_all([
            TelemetrySample(
                id="sample_1", site_id="site_1", panel_id="p1", is_reachable=True,
                engine_status="running", load_kw=475, load_kw_percent=95,
                coolant_temperature=102, oil_pressure=1.5, battery_voltage=12.7,
                fuel_level_percent=15, frequency=50, run_hours=249,
                number_of_starts=80, active_alarm_count=0,
                readings={"coolant_temperature": 102, "fuel_level_percent": 15},
            ),
            Event(
                id="maintenance_alarm", site_id="site_1", panel_id="p1",
                event_type="alarm_active", value="low_oil_pressure:warning",
                triggered_by="system", reason="Alarm activated",
            ),
        ])
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/reports/preventive-maintenance/p1?period=30d", headers=headers)
        assert response.status_code == 200
        body = response.json()
        assert body["generator_name"] == "Test Generator 1"
        assert body["sample_count"] == 1
        assert body["condition_score"] < 100
        assert {f["metric"] for f in body["findings"]} >= {
            "coolant_temperature", "oil_pressure", "fuel_level_percent", "alarms",
        }
        exported = await ac.get("/reports/preventive-maintenance/p1/export?period=30d", headers=headers)
        assert exported.status_code == 200
        assert "PREVENTIVE MAINTENANCE REPORT" in exported.text
        assert "Test Generator 1" in exported.text
        arabic_export = await ac.get(
            "/reports/preventive-maintenance/p1/export?period=30d&locale=ar", headers=headers
        )
        assert arabic_export.status_code == 200
        assert arabic_export.content.startswith(b"\xef\xbb\xbf")
        assert "تقرير الصيانة الوقائية" in arabic_export.text
        assert "قراءات وحدة التحكم الحالية" in arabic_export.text
        assert "درجة حرارة سائل التبريد" in arabic_export.text
        assert "النتائج والتوصيات" in arabic_export.text
        assert "افحص مستوى سائل التبريد" in arabic_export.text

        cleared = await ac.post(
            "/reports/preventive-maintenance/p1/alarms/clear",
            headers=headers,
            json={"resolution_note": "Engineer inspected oil system and verified normal pressure"},
        )
        assert cleared.status_code == 200
        assert cleared.json() == {"status": "cleared", "cleared_count": 1}
        cleared_report = (
            await ac.get("/reports/preventive-maintenance/p1?period=30d", headers=headers)
        ).json()
        assert "alarms" not in {finding["metric"] for finding in cleared_report["findings"]}
        audit_events = (await ac.get("/events?event_type=alarm_cleared", headers=headers)).json()
        assert audit_events[0]["command"] == "maintenance_clear"
        assert "Engineer inspected oil system" in audit_events[0]["reason"]

        for finding in cleared_report["findings"]:
            resolved = await ac.post(
                f"/reports/preventive-maintenance/p1/findings/{finding['metric']}/clear?period=30d",
                headers=headers,
                json={"resolution_note": f"Engineer checked and resolved {finding['metric']}"},
            )
            assert resolved.status_code == 200
            assert resolved.json()["metric"] == finding["metric"]
        healthy_report = (
            await ac.get("/reports/preventive-maintenance/p1?period=30d", headers=headers)
        ).json()
        assert healthy_report["findings"] == []
        assert healthy_report["condition_score"] == 100
        assert healthy_report["condition"] == "No condition warning detected"
        finding_clear_events = (await ac.get(
            "/events?event_type=alarm_cleared&limit=100", headers=headers
        )).json()
        assert sum(event["command"] == "maintenance_finding_clear" for event in finding_clear_events) == len(cleared_report["findings"])

        recorded = await ac.post("/reports/preventive-maintenance/p1/records", headers=headers, json={
            "service_date": date.today().isoformat(), "run_hours": 249,
            "service_type": "250-hour service", "performed_by": "Service Team",
            "notes": "Changed oil and filters",
        })
        assert recorded.status_code == 201
        refreshed = (await ac.get("/reports/preventive-maintenance/p1?period=30d", headers=headers)).json()
        assert refreshed["service"]["next_service_hours"] == 499

        service_export = await ac.get(
            "/reports/preventive-maintenance/p1/records/export", headers=headers
        )
        assert service_export.status_code == 200
        assert service_export.content.startswith(b"\xef\xbb\xbf")
        assert "COMPLETED SERVICE HISTORY" in service_export.text
        assert "250-hour service" in service_export.text
        assert "Changed oil and filters" in service_export.text

        arabic_service_export = await ac.get(
            "/reports/preventive-maintenance/p1/records/export?locale=ar", headers=headers
        )
        assert arabic_service_export.status_code == 200
        assert "سجل الصيانة المكتملة" in arabic_service_export.text
        assert "صيانة 250 ساعة" in arabic_service_export.text
        assert "نفذت بواسطة" in arabic_service_export.text


@pytest.mark.asyncio
async def test_maintenance_alarm_clear_rejects_live_controller_fault(app, headers):
    gateway = app.dependency_overrides[get_gateway]()
    gateway.states["p1"] = Mock(active_alarms=["low_oil_pressure:shutdown"])
    async with async_session_factory() as session:
        session.add(Event(
            id="live_alarm", site_id="site_1", panel_id="p1", event_type="alarm_active",
            value="low_oil_pressure:shutdown", triggered_by="system",
        ))
        await session.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.post(
            "/reports/preventive-maintenance/p1/alarms/clear",
            headers=headers,
            json={"resolution_note": "Checked by engineer"},
        )
        assert response.status_code == 409
        assert "controller still reports active alarms" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_only_mode_queues_durable_commands(app, headers):
    app.dependency_overrides[get_gateway] = lambda: None
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        queued = await ac.post("/panels/p1/start", headers=headers, json={"reason": "Remote request"})
        assert queued.status_code == 200
        assert queued.json()["status"] == "queued"
        command_id = queued.json()["command_id"]
        status_response = await ac.get(f"/panels/commands/{command_id}", headers=headers)
        assert status_response.status_code == 200
        assert status_response.json()["status"] == "queued"
