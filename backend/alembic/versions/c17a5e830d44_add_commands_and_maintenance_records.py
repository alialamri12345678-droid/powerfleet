"""add durable commands and maintenance records

Revision ID: c17a5e830d44
Revises: b42d911fe630
"""

from alembic import op
import sqlalchemy as sa

revision = "c17a5e830d44"
down_revision = "b42d911fe630"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("panels") as batch:
        batch.add_column(sa.Column("maintenance_interval_hours", sa.Float(), nullable=False, server_default="250"))
        batch.add_column(sa.Column("maintenance_limits", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table(
        "command_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("panel_id", sa.String(36)),
        sa.Column("command", sa.String(50), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("triggered_by", sa.String(50), nullable=False),
        sa.Column("requested_by", sa.String(36)),
        sa.Column("reason", sa.Text()),
        sa.Column("detail", sa.Text()),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["requested_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_command_records_site_id", "command_records", ["site_id"])
    op.create_index("ix_command_records_panel_id", "command_records", ["panel_id"])
    op.create_index("ix_command_records_status", "command_records", ["status"])
    op.create_index("ix_command_panel_requested", "command_records", ["panel_id", "requested_at"])
    op.create_table(
        "maintenance_records",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("panel_id", sa.String(36), nullable=False),
        sa.Column("service_date", sa.Date(), nullable=False),
        sa.Column("run_hours", sa.Float(), nullable=False),
        sa.Column("service_type", sa.String(100), nullable=False),
        sa.Column("notes", sa.Text()),
        sa.Column("performed_by", sa.String(200)),
        sa.Column("recorded_by", sa.String(36)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recorded_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_maintenance_records_site_id", "maintenance_records", ["site_id"])
    op.create_index("ix_maintenance_records_panel_id", "maintenance_records", ["panel_id"])


def downgrade() -> None:
    op.drop_table("maintenance_records")
    op.drop_table("command_records")
    with op.batch_alter_table("panels") as batch:
        batch.drop_column("maintenance_limits")
        batch.drop_column("maintenance_interval_hours")
