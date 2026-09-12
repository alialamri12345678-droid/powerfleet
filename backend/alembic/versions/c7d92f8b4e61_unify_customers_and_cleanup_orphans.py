"""Unify customer access and remove orphaned generator configuration.

Revision ID: c7d92f8b4e61
Revises: 9c1e7a5d2b44
"""

from alembic import op
import sqlalchemy as sa

revision = "c7d92f8b4e61"
down_revision = "9c1e7a5d2b44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Preserve all existing accounts, passwords and audit ownership.
    op.execute("UPDATE users SET role = 'customer'")
    with op.batch_alter_table("users") as batch_op:
        batch_op.create_check_constraint("ck_users_customer_role", "role = 'customer'")

    panels = sa.table("panels", sa.column("id"), sa.column("site_id"))
    # Old SQLite installs did not enforce cascades, leaving settings for deleted
    # generators. NULL panel_id in thresholds is the valid site-wide default.
    for name in (
        "start_thresholds", "release_thresholds", "thresholds", "daily_priorities",
        "schedule_exceptions", "schedules", "power_setpoints", "overrides",
    ):
        table = sa.table(name, sa.column("panel_id"), sa.column("site_id"))
        valid_panel = sa.exists(sa.select(panels.c.id).where(
            panels.c.id == table.c.panel_id, panels.c.site_id == table.c.site_id,
        ))
        op.execute(table.delete().where(table.c.panel_id.is_not(None), ~valid_panel))

    events = sa.table("events", sa.column("panel_id"))
    op.execute(events.update().where(
        events.c.panel_id.is_not(None),
        ~sa.exists(sa.select(panels.c.id).where(panels.c.id == events.c.panel_id)),
    ).values(panel_id=None))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_constraint("ck_users_customer_role", type_="check")
    # Deleted orphan settings and former role assignments cannot be recovered.
