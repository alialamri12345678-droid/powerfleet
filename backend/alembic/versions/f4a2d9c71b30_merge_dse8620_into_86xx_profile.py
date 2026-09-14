"""Merge the redundant DSE8620 MKII profile into DSE 86xx MKII."""

from alembic import op
import sqlalchemy as sa


revision = "f4a2d9c71b30"
down_revision = "e390ab614fc2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        sa.text("UPDATE panels SET controller_profile = 'dse_86xx_mkii' "
                "WHERE controller_profile = 'dse8620_mkii'")
    )
    with op.batch_alter_table("panels") as batch:
        batch.alter_column(
            "controller_profile",
            existing_type=sa.String(length=80),
            nullable=False,
            server_default="dse_86xx_mkii",
        )


def downgrade() -> None:
    op.execute(
        sa.text("UPDATE panels SET controller_profile = 'dse8620_mkii' "
                "WHERE controller_profile = 'dse_86xx_mkii'")
    )
    with op.batch_alter_table("panels") as batch:
        batch.alter_column(
            "controller_profile",
            existing_type=sa.String(length=80),
            nullable=False,
            server_default="dse8620_mkii",
        )
