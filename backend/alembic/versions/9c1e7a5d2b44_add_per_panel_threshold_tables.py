"""Add per-panel start and release threshold tables.

Revision ID: 9c1e7a5d2b44
Revises: f630909bf7ce
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "9c1e7a5d2b44"
down_revision: Union[str, None] = "f630909bf7ce"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _create_threshold_table(
    table_name: str,
    value_column: str,
    value_default: str,
    value_comment: str,
    priority_comment: str,
) -> None:
    op.create_table(
        table_name,
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("site_id", sa.String(length=36), nullable=False),
        sa.Column("panel_id", sa.String(length=36), nullable=False),
        sa.Column(
            value_column,
            sa.Numeric(precision=5, scale=2),
            nullable=False,
            server_default=value_default,
            comment=value_comment,
        ),
        sa.Column(
            "priority_order",
            sa.Integer(),
            nullable=False,
            server_default="1",
            comment=priority_comment,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["panel_id"], ["panels.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f(f"ix_{table_name}_panel_id"), table_name, ["panel_id"], unique=False
    )
    op.create_index(
        op.f(f"ix_{table_name}_site_id"), table_name, ["site_id"], unique=False
    )


def upgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "release_thresholds" not in existing_tables:
        _create_threshold_table(
            "release_thresholds",
            "release_pct",
            "50.0",
            "Stop this backup when total facility load drops below this %",
            "Release order — higher priority number released first",
        )
    if "start_thresholds" not in existing_tables:
        _create_threshold_table(
            "start_thresholds",
            "start_pct",
            "70.0",
            "Start this backup when total facility load rises above this %",
            "Start order — lower priority number started first",
        )


def downgrade() -> None:
    existing_tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "start_thresholds" in existing_tables:
        op.drop_index(op.f("ix_start_thresholds_site_id"), table_name="start_thresholds")
        op.drop_index(op.f("ix_start_thresholds_panel_id"), table_name="start_thresholds")
        op.drop_table("start_thresholds")
    if "release_thresholds" in existing_tables:
        op.drop_index(op.f("ix_release_thresholds_site_id"), table_name="release_thresholds")
        op.drop_index(op.f("ix_release_thresholds_panel_id"), table_name="release_thresholds")
        op.drop_table("release_thresholds")
