"""User model — authenticated customers with full installation access."""

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class User(Base, TimestampMixin):
    __tablename__ = "users"
    __table_args__ = (CheckConstraint("role = 'customer'", name="ck_users_customer_role"),)

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    email: Mapped[str] = mapped_column(
        String(254), unique=True, nullable=False, index=True,
    )
    password_hash: Mapped[str] = mapped_column(
        String(200), nullable=False,
    )
    full_name: Mapped[str] = mapped_column(
        String(200), nullable=False, default="",
    )

    # A single customer role; every account has the same full controls.
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="customer",
        comment="customer",
    )

    # Active site context within this customer's installation
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} role={self.role!r}>"
