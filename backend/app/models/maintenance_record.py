"""Completed maintenance work recorded against a generator."""

from datetime import date

from sqlalchemy import Date, Float, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class MaintenanceRecord(Base, TenantMixin, TimestampMixin):
    __tablename__ = "maintenance_records"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    panel_id: Mapped[str] = mapped_column(String(36), ForeignKey("panels.id", ondelete="CASCADE"), index=True, nullable=False)
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    run_hours: Mapped[float] = mapped_column(Float, nullable=False)
    service_type: Mapped[str] = mapped_column(String(100), nullable=False, default="Routine service")
    notes: Mapped[str | None] = mapped_column(Text)
    performed_by: Mapped[str | None] = mapped_column(String(200))
    recorded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"))
