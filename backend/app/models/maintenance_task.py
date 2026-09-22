"""Manufacturer maintenance schedules and persistent condition findings."""

from datetime import date, datetime
from sqlalchemy import Boolean, Date, DateTime, Float, ForeignKey, Integer, JSON, String, Text, Index
from sqlalchemy.orm import Mapped, mapped_column
from .base import Base, TenantMixin, TimestampMixin, generate_uuid


class MaintenanceTask(Base, TenantMixin, TimestampMixin):
    __tablename__ = "maintenance_tasks"
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    panel_id: Mapped[str] = mapped_column(String(36), ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    component: Mapped[str] = mapped_column(String(80))
    name: Mapped[str] = mapped_column(String(200))
    interval_hours: Mapped[float | None] = mapped_column(Float)
    interval_days: Mapped[int | None] = mapped_column(Integer)
    baseline_date: Mapped[date | None] = mapped_column(Date)
    baseline_run_hours: Mapped[float | None] = mapped_column(Float)
    manufacturer_reference: Mapped[str | None] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class MaintenanceFindingRecord(Base, TenantMixin, TimestampMixin):
    __tablename__ = "maintenance_findings"
    __table_args__ = (Index("ix_maintenance_finding_panel_status", "panel_id", "status"),)
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    panel_id: Mapped[str] = mapped_column(String(36), ForeignKey("panels.id", ondelete="CASCADE"), index=True)
    metric: Mapped[str] = mapped_column(String(100))
    severity: Mapped[str] = mapped_column(String(20))
    title: Mapped[str] = mapped_column(Text)
    detail: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(30), default="open")
    verification_kind: Mapped[str] = mapped_column(String(20), default="sensor")
    evidence: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    first_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    last_detected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    work_recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    resolution_note: Mapped[str | None] = mapped_column(Text)
    recorded_by: Mapped[str | None] = mapped_column(String(36), ForeignKey("users.id", ondelete="SET NULL"))
