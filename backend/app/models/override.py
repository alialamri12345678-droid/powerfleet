"""Override model — technician manual overrides with mandatory expiry."""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class Override(Base, TenantMixin, TimestampMixin):
    __tablename__ = "overrides"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    panel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("panels.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )

    # What the override forces
    override_type: Mapped[str] = mapped_column(
        String(20), nullable=False,
        comment="force_start | force_stop",
    )

    # Who created it
    created_by: Mapped[str] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # When it expires (mandatory — no indefinite overrides)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Optional note from the technician",
    )

    # Relationships
    panel = relationship("Panel", back_populates="overrides")

    @property
    def is_expired(self) -> bool:
        return datetime.now(timezone.utc) >= self.expires_at

    def __repr__(self) -> str:
        return (
            f"<Override {self.override_type} panel={self.panel_id!r} "
            f"expires={self.expires_at} active={self.is_active}>"
        )
