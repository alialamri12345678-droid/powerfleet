"""Release Threshold model — per-backup-unit release thresholds based on total facility load."""

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class ReleaseThreshold(Base, TenantMixin, TimestampMixin):
    __tablename__ = "release_thresholds"

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

    # Total facility load % below which this backup should be released
    release_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=50.0,
        comment="Stop this backup when total facility load drops below this %",
    )

    # Mirrors the panel's backup priority (auto-maintained)
    priority_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Release order — higher priority number released first",
    )

    # Relationships
    site = relationship("Site")
    panel = relationship("Panel")

    def __repr__(self) -> str:
        return (
            f"<ReleaseThreshold site={self.site_id!r} panel={self.panel_id!r} "
            f"release={self.release_pct}% order={self.priority_order}>"
        )
