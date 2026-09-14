"""add gateway ownership leases

Revision ID: d6087bf23915
Revises: c17a5e830d44
"""

from alembic import op
import sqlalchemy as sa

revision = "d6087bf23915"
down_revision = "c17a5e830d44"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "gateway_leases" in sa.inspect(op.get_bind()).get_table_names():
        return
    op.create_table(
        "gateway_leases",
        sa.Column("site_id", sa.String(36), primary_key=True),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["site_id"], ["sites.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_gateway_leases_owner_id", "gateway_leases", ["owner_id"])
    op.create_index("ix_gateway_leases_expires_at", "gateway_leases", ["expires_at"])


def downgrade() -> None:
    op.drop_table("gateway_leases")
