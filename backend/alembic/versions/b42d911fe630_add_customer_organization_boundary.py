"""add customer organization boundary

Revision ID: b42d911fe630
Revises: a91f28c40b77
"""

from alembic import op
import sqlalchemy as sa

revision = "b42d911fe630"
down_revision = "a91f28c40b77"
branch_labels = None
depends_on = None

DEFAULT_ORG_ID = "default-customer-organization"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "organizations" not in inspector.get_table_names():
        op.create_table(
            "organizations",
            sa.Column("id", sa.String(36), primary_key=True),
            sa.Column("name", sa.String(200), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
    organizations = sa.table("organizations", sa.column("id"), sa.column("name"), sa.column("created_at"), sa.column("updated_at"))
    if bind.execute(sa.select(organizations.c.id).where(organizations.c.id == DEFAULT_ORG_ID)).first() is None:
        op.execute(sa.text(
            "INSERT INTO organizations (id, name, created_at, updated_at) "
            "VALUES (:id, :name, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ).bindparams(id=DEFAULT_ORG_ID, name="Existing Customer Organization"))
    site_columns = {column["name"] for column in inspector.get_columns("sites")}
    if "organization_id" not in site_columns:
        with op.batch_alter_table("sites") as batch:
            batch.add_column(sa.Column("organization_id", sa.String(36), nullable=True))
    user_columns = {column["name"] for column in inspector.get_columns("users")}
    if "organization_id" not in user_columns:
        with op.batch_alter_table("users") as batch:
            batch.add_column(sa.Column("organization_id", sa.String(36), nullable=True))
    op.execute(sa.text("UPDATE sites SET organization_id = :id").bindparams(id=DEFAULT_ORG_ID))
    op.execute(sa.text("UPDATE users SET organization_id = :id").bindparams(id=DEFAULT_ORG_ID))
    with op.batch_alter_table("sites") as batch:
        batch.alter_column("organization_id", existing_type=sa.String(36), nullable=False)
    with op.batch_alter_table("users") as batch:
        batch.alter_column("organization_id", existing_type=sa.String(36), nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("users") as batch:
        batch.drop_column("organization_id")
    with op.batch_alter_table("sites") as batch:
        batch.drop_column("organization_id")
    op.drop_table("organizations")
