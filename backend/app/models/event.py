"""Event model — append-only audit log of all commands and status changes."""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base, TenantMixin, generate_uuid


class Event(Base, TenantMixin):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(
        String(36), primary_key=True, default=generate_uuid
    )
    site_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("sites.id", ondelete="CASCADE"),
        index=True, nullable=False,
    )
    panel_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("panels.id", ondelete="SET NULL"),
        index=True, nullable=True,
    )

    # Event classification
    event_type: Mapped[str] = mapped_column(
        String(50), nullable=False, index=True,
        comment="command_sent | alarm_active | alarm_cleared | status_change | override | system",
    )
    command: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="remote_start | remote_stop | set_power | etc.",
    )
    value: Mapped[str | None] = mapped_column(
        String(200), nullable=True,
        comment="Command value or status detail as string",
    )

    # What triggered this event
    triggered_by: Mapped[str] = mapped_column(
        String(50), nullable=False,
        comment="schedule | threshold | manual | override | system",
    )
    reason: Mapped[str | None] = mapped_column(
        Text, nullable=True,
        comment="Human-readable explanation of why this action was taken",
    )

    # Detailed Audit Trail (Phase 3)
    previous_state: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Engine status before the command was sent",
    )
    new_state: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="Target engine status after the command",
    )
    load_kw_at_decision: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Fleet or generator load at the time of the decision",
    )
    capacity_pct_at_decision: Mapped[float | None] = mapped_column(
        nullable=True,
        comment="Fleet capacity percentage at the time of the decision",
    )
    command_result: Mapped[str | None] = mapped_column(
        String(50), nullable=True,
        comment="success | failed | timeout | cooldown_blocked",
    )

    # Who triggered it (null for automated actions)
    user_id: Mapped[str | None] = mapped_column(
        String(36), ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )

    # Immutable timestamp — no updated_at on purpose
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        nullable=False,
        index=True,
    )

    # Relationships
    site = relationship("Site", back_populates="events")

    def __repr__(self) -> str:
        return (
            f"<Event {self.event_type} panel={self.panel_id!r} "
            f"by={self.triggered_by} at={self.timestamp}>"
        )
