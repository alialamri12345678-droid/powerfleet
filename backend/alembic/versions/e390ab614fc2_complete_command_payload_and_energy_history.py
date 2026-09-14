"""complete command payload and energy history

Revision ID: e390ab614fc2
Revises: d6087bf23915
"""

from alembic import op
import sqlalchemy as sa

revision = "e390ab614fc2"
down_revision = "d6087bf23915"
branch_labels = None
depends_on = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    telemetry_columns = {column["name"] for column in inspector.get_columns("telemetry_samples")}
    command_columns = {column["name"] for column in inspector.get_columns("command_records")}
    if "total_kwh" not in telemetry_columns:
        with op.batch_alter_table("telemetry_samples") as batch:
            batch.add_column(sa.Column("total_kwh", sa.Float(), nullable=False, server_default="0"))
    if "payload" not in command_columns:
        with op.batch_alter_table("command_records") as batch:
            batch.add_column(sa.Column("payload", sa.JSON(), nullable=False, server_default="{}"))


def downgrade() -> None:
    with op.batch_alter_table("command_records") as batch:
        batch.drop_column("payload")
    with op.batch_alter_table("telemetry_samples") as batch:
        batch.drop_column("total_kwh")
