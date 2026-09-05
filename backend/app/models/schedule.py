"""Schedule model — weekly repeating duty patterns per panel."""

from sqlalchemy import Boolean, ForeignKey, Integer, String, Time
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class Schedule(Base, TenantMixin, TimestampMixin):
    __tablename__ = "schedules"

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

    # Start and stop times (naive time-of-day in the *site's* local timezone)
    start_time: Mapped[str] = mapped_column(
        String(5), nullable=False, default="06:00",
        comment="HH:MM in site-local time",
    )
    end_time: Mapped[str] = mapped_column(
        String(5), nullable=False, default="18:00",
        comment="HH:MM in site-local time",
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
    )

    # Relationships
    panel = relationship("Panel", back_populates="schedules")

    def __repr__(self) -> str:
        return (
            f"<Schedule panel={self.panel_id!r} day={self.day_of_week} "
            f"{self.start_time}-{self.end_time}>"
        )
