"""User model — authentication and role-based access."""

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin, generate_uuid


class User(Base, TimestampMixin):
    __tablename__ = "users"

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

    # Role: 'customer' or 'technician'
    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default="customer",
        comment="customer | technician",
    )

    # Every user belongs to exactly one site
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )

    def __repr__(self) -> str:
        return f"<User id={self.id!r} email={self.email!r} role={self.role!r}>"
