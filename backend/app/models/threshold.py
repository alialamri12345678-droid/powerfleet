"""Threshold model — load-based triggers for starting/stopping backup panels."""

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class Threshold(Base, TenantMixin, TimestampMixin):
    __tablename__ = "thresholds"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )

    # Optional: scope to a specific panel (null = site-wide default)
    panel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("panels.id", ondelete="CASCADE"),
        nullable=True,
    )

    # Hysteresis: start_pct > stop_pct to avoid hunting
    start_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=70,
        comment="Start backup when site load exceeds this %",
    )
    stop_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=50,
        comment="Stop backup when site load drops below this %",
    )

    # Minimum time a backup must run before it can be stopped
    dwell_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, default=120,
        comment="Min seconds backup runs before auto-stop is allowed",
    )

    # Relationships
    site = relationship("Site", back_populates="thresholds")

    def __repr__(self) -> str:
        return (
            f"<Threshold site={self.site_id!r} start={self.start_pct}% "
            f"stop={self.stop_pct}% dwell={self.dwell_seconds}s>"
        )
