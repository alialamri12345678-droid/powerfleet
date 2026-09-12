"""Reserved threshold compatibility revision.

Revision ID: e84a2c6f9d30
Revises: c7d92f8b4e61
"""

revision = "e84a2c6f9d30"
down_revision = "c7d92f8b4e61"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Kept as a no-op so installations that already recorded this revision
    # remain migration-compatible. Per-generator start and release thresholds
    # are intentionally independent and may overlap.
    pass


def downgrade() -> None:
    pass
