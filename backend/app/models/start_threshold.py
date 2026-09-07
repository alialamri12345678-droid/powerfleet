"""Start Threshold model — per-backup-unit start thresholds based on total facility load."""

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class StartThreshold(Base, TenantMixin, TimestampMixin):
    __tablename__ = "start_thresholds"

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

    # Total facility load % above which this backup should be started
    start_pct: Mapped[float] = mapped_column(
        Numeric(5, 2), nullable=False, default=70.0,
        comment="Start this backup when total facility load rises above this %",
    )

    # Mirrors the panel's backup priority (auto-maintained)
    priority_order: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1,
        comment="Start order — lower priority number started first",
    )

    # Relationships
    site = relationship("Site")
    panel = relationship("Panel")

    def __repr__(self) -> str:
        return (
            f"<StartThreshold site={self.site_id!r} panel={self.panel_id!r} "
            f"start={self.start_pct}% order={self.priority_order}>"
        )
