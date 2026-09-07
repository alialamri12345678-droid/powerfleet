"""Daily Priority model — defines backup generator order per day."""

from sqlalchemy import ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class DailyPriority(Base, TenantMixin, TimestampMixin):
    __tablename__ = "daily_priorities"

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

    # Day of the week: 0 = Monday, 6 = Sunday (ISO 8601)
    day_of_week: Mapped[int] = mapped_column(
        Integer, nullable=False,
        comment="0=Mon, 1=Tue, 2=Wed, 3=Thu, 4=Fri, 5=Sat, 6=Sun",
    )

    # Priority ranking for the backup dispatch (1 is first backup, 2 is second, etc.)
    priority: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1
    )

    def __repr__(self) -> str:
        return f"<DailyPriority site={self.site_id!r} panel={self.panel_id!r} day={self.day_of_week} pri={self.priority}>"
