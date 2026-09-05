"""SQLAlchemy declarative base and shared mixins."""

import uuid
from datetime import datetime, timezone

from sqlalchemy import DateTime, String
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """Application-wide declarative base."""
    pass


class TimestampMixin:
    """Adds created_at / updated_at columns (UTC)."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        nullable=False,
    )


class TenantMixin:
    """Adds a mandatory site_id foreign key for multi-tenant scoping.

    Every tenant-scoped model inherits this mixin so that the
    ``scoped_query`` helper can enforce site isolation automatically.
    """

    site_id: Mapped[str] = mapped_column(
        String(36),
        index=True,
        nullable=False,
    )


def generate_uuid() -> str:
    """Return a new UUID4 string for use as a primary key default."""
    return str(uuid.uuid4())
