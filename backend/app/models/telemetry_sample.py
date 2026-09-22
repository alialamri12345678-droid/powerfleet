"""Durable, per-generator telemetry used for trends and maintenance reports."""

from datetime import datetime, timezone
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, JSON, String
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base, TenantMixin, generate_uuid


class TelemetrySample(Base, TenantMixin):
    __tablename__ = "telemetry_samples"
    __table_args__ = (
        Index("ix_telemetry_panel_recorded", "panel_id", "recorded_at"),
    )

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=generate_uuid)
    panel_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("panels.id", ondelete="CASCADE"), index=True, nullable=False
    )
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(timezone.utc), index=True, nullable=False
    )
    is_reachable: Mapped[bool] = mapped_column(nullable=False, default=True)
    engine_status: Mapped[str] = mapped_column(String(30), nullable=False, default="unknown")
    load_kw: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    load_kw_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    coolant_temperature: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    oil_pressure: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    battery_voltage: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    fuel_level_percent: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    frequency: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    run_hours: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    total_kwh: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    number_of_starts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    active_alarm_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    readings: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    fuel_used_litres: Mapped[float | None] = mapped_column(Float, nullable=True)
    reading_quality: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    reading_units: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    reading_timestamps: Mapped[dict[str, str]] = mapped_column(JSON, nullable=False, default=dict)
    source_identity: Mapped[str | None] = mapped_column(String(255), nullable=True)
