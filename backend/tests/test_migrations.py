"""Exercise the real upgrade path from the previous two-role schema."""

from datetime import datetime
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
import sqlalchemy as sa

from app.config import settings


def test_upgrade_preserves_accounts_and_removes_old_threshold_orphans(tmp_path, monkeypatch):
    database = tmp_path / "upgrade.db"
    monkeypatch.setattr(settings, "database_url", f"sqlite+aiosqlite:///{database.as_posix()}")
    backend = Path(__file__).resolve().parents[1]
    config = Config(str(backend / "alembic.ini"))
    config.set_main_option("script_location", str(backend / "alembic"))
    command.upgrade(config, "9c1e7a5d2b44")

    engine = sa.create_engine(f"sqlite:///{database.as_posix()}")
    metadata = sa.MetaData()
    metadata.reflect(engine)
    now = datetime.now()
    times = {"created_at": now, "updated_at": now}
    with engine.begin() as connection:
        connection.execute(metadata.tables["sites"].insert(), {
            "id": "site", "name": "Existing Site", "timezone": "UTC", **times,
        })
        for user_id, role in (("old_customer", "customer"), ("old_technician", "technician")):
            connection.execute(metadata.tables["users"].insert(), {
                "id": user_id, "email": f"{user_id}@example.com", "password_hash": f"hash-{user_id}",
                "full_name": user_id, "role": role, "site_id": "site", **times,
            })
        connection.execute(metadata.tables["panels"].insert(), {
            "id": "kept", "site_id": "site", "name": "Retained Generator", "transport_type": "tcp",
            "address": "127.0.0.1:15020", "unit_id": 1, "rated_kw": 500, "rated_kvar": 150,
            "priority": 1, "lead_rotation_order": 1, "maintenance_mode": False, **times,
        })
        for name, value_column in (("start_thresholds", "start_pct"), ("release_thresholds", "release_pct")):
            for panel_id in ("kept", "already_deleted"):
                connection.execute(metadata.tables[name].insert(), {
                    "id": f"{name}-{panel_id}", "site_id": "site", "panel_id": panel_id,
                    value_column: 65, "priority_order": 1, **times,
                })
        for row_id, panel_id in (("site_default", None), ("orphan", "already_deleted")):
            connection.execute(metadata.tables["thresholds"].insert(), {
                "id": row_id, "site_id": "site", "panel_id": panel_id,
                "start_pct": 70, "stop_pct": 50, "dwell_seconds": 120, **times,
            })
        connection.execute(metadata.tables["events"].insert(), {
            "id": "audit", "site_id": "site", "panel_id": "already_deleted",
            "user_id": "old_technician", "event_type": "command_sent",
            "triggered_by": "manual", "timestamp": now,
        })

    command.upgrade(config, "head")
    command.check(config)
    with engine.connect() as connection:
        users = connection.execute(sa.text("SELECT id, role, password_hash FROM users ORDER BY id")).all()
        assert users == [
            ("old_customer", "customer", "hash-old_customer"),
            ("old_technician", "customer", "hash-old_technician"),
        ]
        for name in ("start_thresholds", "release_thresholds"):
            assert connection.execute(sa.select(metadata.tables[name].c.panel_id)).scalars().all() == ["kept"]
        assert connection.execute(sa.text("SELECT id FROM thresholds")).scalars().all() == ["site_default"]
        assert connection.execute(sa.text("SELECT panel_id, user_id FROM events")).one() == (None, "old_technician")
        assert connection.execute(sa.text("PRAGMA foreign_key_check")).all() == []
        with pytest.raises(sa.exc.IntegrityError):
            connection.execute(sa.text("UPDATE users SET role = 'technician'"))
    engine.dispose()
