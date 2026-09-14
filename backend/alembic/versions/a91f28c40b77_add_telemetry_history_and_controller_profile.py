"""add telemetry history and controller profile

Revision ID: a91f28c40b77
Revises: e84a2c6f9d30
"""

from alembic import op
import sqlalchemy as sa

revision = "a91f28c40b77"
down_revision = "e84a2c6f9d30"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    panel_columns = {column["name"] for column in inspector.get_columns("panels")}
    if "controller_profile" not in panel_columns:
        with op.batch_alter_table("panels") as batch:
            batch.add_column(sa.Column("controller_profile", sa.String(80), nullable=False, server_default="dse8620_mkii"))
    if "telemetry_samples" in inspector.get_table_names():
        return
    op.create_table(
        "telemetry_samples",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("panel_id", sa.String(36), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("is_reachable", sa.Boolean(), nullable=False),
        sa.Column("engine_status", sa.String(30), nullable=False),
        sa.Column("load_kw", sa.Float(), nullable=False),
        sa.Column("load_kw_percent", sa.Float(), nullable=False),
        sa.Column("coolant_temperature", sa.Float(), nullable=False),
        sa.Column("oil_pressure", sa.Float(), nullable=False),
        sa.Column("battery_voltage", sa.Float(), nullable=False),
        sa.Column("fuel_level_percent", sa.Float(), nullable=False),
        sa.Column("frequency", sa.Float(), nullable=False),
        sa.Column("run_hours", sa.Float(), nullable=False),
        sa.Column("number_of_starts", sa.Integer(), nullable=False),
        sa.Column("active_alarm_count", sa.Integer(), nullable=False),
        sa.Column("readings", sa.JSON(), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_telemetry_samples_site_id", "telemetry_samples", ["site_id"])
    op.create_index("ix_telemetry_samples_panel_id", "telemetry_samples", ["panel_id"])
    op.create_index("ix_telemetry_samples_recorded_at", "telemetry_samples", ["recorded_at"])
    op.create_index("ix_telemetry_panel_recorded", "telemetry_samples", ["panel_id", "recorded_at"])


def downgrade() -> None:
    op.drop_table("telemetry_samples")
    with op.batch_alter_table("panels") as batch:
        batch.drop_column("controller_profile")
