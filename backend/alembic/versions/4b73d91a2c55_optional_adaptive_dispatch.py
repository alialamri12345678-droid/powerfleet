"""Optional site power planning; existing threshold dispatch remains default."""
from alembic import op
import sqlalchemy as sa

revision = "4b73d91a2c55"
down_revision = "19a60b52d730"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("sites", sa.Column("dispatch_config", sa.JSON(), nullable=False, server_default="{}"))
    op.create_table("site_supply",
        sa.Column("site_id", sa.String(36), sa.ForeignKey("sites.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("measured_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("reading", sa.JSON(), nullable=False),
        sa.Column("plan", sa.JSON(), nullable=True),
        sa.Column("planned_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade():
    op.drop_table("site_supply")
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("dispatch_config")
