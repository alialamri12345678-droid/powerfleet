"""Recorded tank refills and transfers for estimated fuel accounting."""
from datetime import datetime
from sqlalchemy import DateTime, Float, ForeignKey, Index, String, Text
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class FuelMovement(Base, TenantMixin, TimestampMixin):
    __tablename__ = "fuel_movements"
    __table_args__ = (Index("ix_fuel_movement_panel_time", "panel_id", "occurred_at"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    panel_id: Mapped[str] = mapped_column(String(36), ForeignKey("panels.id", ondelete="CASCADE"), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    litres: Mapped[float] = mapped_column(Float, nullable=False)
    notes: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"))
