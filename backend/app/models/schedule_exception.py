"""ScheduleException model — date-specific scheduling overrides (holidays, one-off runs)."""

from datetime import date
from sqlalchemy import Boolean, Date, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TimestampMixin, generate_uuid


class ScheduleException(Base, TimestampMixin):
    __tablename__ = "schedule_exceptions"

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

    exception_date: Mapped[date] = mapped_column(
        Date, nullable=False,
        comment="The specific date this exception applies to",
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True,
        comment="If True, forces the generator ON during the times below. If False, forces it OFF for the entire day (holiday).",
    )
    start_time: Mapped[str | None] = mapped_column(
        String(5), nullable=True,
        comment="HH:MM in site-local time (required if is_active=True)",
    )
    end_time: Mapped[str | None] = mapped_column(
        String(5), nullable=True,
        comment="HH:MM in site-local time (required if is_active=True)",
    )

    # Relationships
    panel = relationship("Panel")

    def __repr__(self) -> str:
        return f"<ScheduleException id={self.id!r} date={self.exception_date!r} active={self.is_active!r}>"
