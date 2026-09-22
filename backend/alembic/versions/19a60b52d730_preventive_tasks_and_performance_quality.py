"""Component schedules, verified findings and fuel measurement provenance."""

from alembic import op
import sqlalchemy as sa

revision = "19a60b52d730"
down_revision = "f4a2d9c71b30"
branch_labels = None
depends_on = None


def timestamps():
    return [sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False)]


def upgrade():
    op.add_column("panels", sa.Column("analytics_config", sa.JSON(), nullable=False, server_default="{}"))
    op.add_column("telemetry_samples", sa.Column("fuel_used_litres", sa.Float(), nullable=True))
    op.add_column("telemetry_samples", sa.Column("source_identity", sa.String(255), nullable=True))
    for name in ("reading_quality", "reading_units", "reading_timestamps"):
        op.add_column("telemetry_samples", sa.Column(name, sa.JSON(), nullable=False, server_default="{}"))
    # Old telemetry is deliberately not promoted to verified data. Fuel already
    # in readings JSON remains available with legacy/unknown provenance.
    op.add_column("maintenance_records", sa.Column("task_ids", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("maintenance_records", sa.Column("checklist_confirmed", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.create_table("maintenance_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("panel_id", sa.String(36), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("component", sa.String(80), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("interval_hours", sa.Float(), nullable=True),
        sa.Column("interval_days", sa.Integer(), nullable=True),
        sa.Column("baseline_date", sa.Date(), nullable=True),
        sa.Column("baseline_run_hours", sa.Float(), nullable=True),
        sa.Column("manufacturer_reference", sa.Text(), nullable=True),
        sa.Column("active", sa.Boolean(), nullable=False),
        *timestamps(),
    )
    op.create_index("ix_maintenance_tasks_site_id", "maintenance_tasks", ["site_id"])
    op.create_index("ix_maintenance_tasks_panel_id", "maintenance_tasks", ["panel_id"])
    op.create_table("maintenance_findings",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("panel_id", sa.String(36), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric", sa.String(100), nullable=False),
        sa.Column("severity", sa.String(20), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("verification_kind", sa.String(20), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=False),
        sa.Column("first_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_detected_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("work_recorded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolution_note", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_maintenance_findings_site_id", "maintenance_findings", ["site_id"])
    op.create_index("ix_maintenance_findings_panel_id", "maintenance_findings", ["panel_id"])
    op.create_index("ix_maintenance_finding_panel_status", "maintenance_findings", ["panel_id", "status"])
    op.create_table("fuel_movements",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("site_id", sa.String(36), nullable=False),
        sa.Column("panel_id", sa.String(36), sa.ForeignKey("panels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("litres", sa.Float(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("recorded_by", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        *timestamps(),
    )
    op.create_index("ix_fuel_movements_site_id", "fuel_movements", ["site_id"])
    op.create_index("ix_fuel_movement_panel_time", "fuel_movements", ["panel_id", "occurred_at"])


def downgrade():
    op.drop_table("fuel_movements")
    op.drop_table("maintenance_findings")
    op.drop_table("maintenance_tasks")
    with op.batch_alter_table("maintenance_records") as batch:
        batch.drop_column("checklist_confirmed")
        batch.drop_column("task_ids")
    with op.batch_alter_table("telemetry_samples") as batch:
        for name in ("fuel_used_litres", "source_identity", "reading_quality", "reading_units", "reading_timestamps"):
            batch.drop_column(name)
    with op.batch_alter_table("panels") as batch:
        batch.drop_column("analytics_config")
