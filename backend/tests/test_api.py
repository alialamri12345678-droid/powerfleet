"""Integration tests for FastAPI endpoints, role enforcement, and validation."""

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.auth.models import User
from app.auth.service import create_access_token, hash_password
from app.db.session import async_session_factory, engine
from app.main import create_app
from app.models.base import Base
from app.models.panel import Panel
from app.models.site import Site


@pytest_asyncio.fixture(autouse=True)
async def setup_db():
    """Create all tables and seed test users before running tests."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        # Check if site exists
        site = await session.get(Site, "site_1")
        if not site:
            site = Site(
                id="site_1",
                name="Test Facility",
                timezone="UTC",
                max_parallel_units=2,
            )
            session.add(site)

            customer = User(
                id="user_customer",
                email="customer@test.com",
                password_hash=hash_password("pass123"),
                full_name="Test Customer",
                role="customer",
                site_id="site_1",
            )
            technician = User(
                id="user_tech",
                email="tech@test.com",
                password_hash=hash_password("pass123"),
                full_name="Test Tech",
                role="technician",
                site_id="site_1",
            )
            panel = Panel(
                id="p1",
                site_id="site_1",
                name="Test Generator 1",
                transport_type="tcp",
                address="127.0.0.1:5020",
                unit_id=1,
                rated_kw=500.0,
                rated_kvar=150.0,
                priority=1,
            )
            session.add_all([customer, technician, panel])
            await session.commit()

    yield


@pytest.fixture
def app():
    return create_app()


@pytest.mark.asyncio
async def test_health_check(app):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


@pytest.mark.asyncio
async def test_role_enforcement_customer_denied_diagnostics(app):
    # Customer token
    token = create_access_token({
        "sub": "user_customer",
        "role": "customer",
        "site_id": "site_1",
    })

    headers = {"Authorization": f"Bearer {token}"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/diagnostics/panels/p1/raw", headers=headers)
        # Customer should be 403 Forbidden
        assert response.status_code == 403
        assert "technician role only" in response.json()["detail"]


@pytest.mark.asyncio
async def test_threshold_validation_rejects_inverted_hysteresis(app):
    token = create_access_token({
        "sub": "user_customer",
        "role": "customer",
        "site_id": "site_1",
    })

    headers = {"Authorization": f"Bearer {token}"}
    # Inverted: stop_pct (80) >= start_pct (70)
    payload = {
        "start_pct": 70,
        "stop_pct": 80,
        "dwell_seconds": 120,
    }
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.put("/thresholds", json=payload, headers=headers)
        assert response.status_code == 422  # Unprocessable Entity


@pytest.mark.asyncio
async def test_create_site_and_switch(app):
    tech_token = create_access_token({
        "sub": "user_tech",
        "role": "technician",
        "site_id": "site_1",
    })
    headers = {"Authorization": f"Bearer {tech_token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Create new site
        res = await ac.post(
            "/sites",
            json={"name": "Secondary Facility - Bldg B", "timezone": "UTC", "max_parallel_units": 2},
            headers=headers,
        )
        assert res.status_code == 201
        site_data = res.json()
        new_site_id = site_data["id"]
        assert site_data["name"] == "Secondary Facility - Bldg B"

        # List sites
        res_list = await ac.get("/sites", headers=headers)
        assert res_list.status_code == 200
        assert len(res_list.json()) >= 2

        # Switch to new site
        res_switch = await ac.post(f"/sites/switch/{new_site_id}", headers=headers)
        assert res_switch.status_code == 200
        assert res_switch.json()["id"] == new_site_id


@pytest.mark.asyncio
async def test_add_and_delete_generator(app):
    tech_token = create_access_token({
        "sub": "user_tech",
        "role": "technician",
        "site_id": "site_1",
    })
    headers = {"Authorization": f"Bearer {tech_token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Add new generator
        res = await ac.post(
            "/panels",
            json={
                "name": "Generator 4 (Expansion)",
                "transport_type": "tcp",
                "address": "127.0.0.1:5020",
                "unit_id": 4,
                "rated_kw": 600.0,
                "rated_kvar": 180.0,
                "priority": 4,
            },
            headers=headers,
        )
        assert res.status_code == 201
        gen_data = res.json()
        gen_id = gen_data["id"]
        assert gen_data["name"] == "Generator 4 (Expansion)"

        # Verify listed
        res_list = await ac.get("/panels", headers=headers)
        assert any(p["id"] == gen_id for p in res_list.json())

        # Delete generator
        res_del = await ac.delete(f"/panels/{gen_id}", headers=headers)
        assert res_del.status_code == 204

        # Verify removed
        res_list_after = await ac.get("/panels", headers=headers)
        assert not any(p["id"] == gen_id for p in res_list_after.json())


@pytest.mark.asyncio
async def test_reports_summary_and_csv_export(app):
    cust_token = create_access_token({
        "sub": "user_customer",
        "role": "customer",
        "site_id": "site_1",
    })
    headers = {"Authorization": f"Bearer {cust_token}"}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        # Get report summary
        res = await ac.get("/reports/summary?period=30d", headers=headers)
        assert res.status_code == 200
        data = res.json()
        assert "generators" in data
        assert "total_fleet_hours" in data
        assert len(data["generators"]) >= 1

        # Export CSV
        res_csv = await ac.get("/reports/export?period=30d", headers=headers)
        assert res_csv.status_code == 200
        assert res_csv.headers["content-type"].startswith("text/csv")
        assert "GENERATOR FLEET WORK REPORT" in res_csv.text
        assert "GENERATOR PERFORMANCE & WORK SUMMARY" in res_csv.text
        assert "Test Generator 1" in res_csv.text

