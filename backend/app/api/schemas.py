"""Pydantic schemas for API request validation and response formatting."""

from datetime import datetime, date
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator


# ── Site Schemas ────────────────────────────────────────────────────────
class SiteBase(BaseModel):
    name: str = Field(..., max_length=200)
    address: str | None = None
    timezone: str = "UTC"
    max_parallel_units: int | None = Field(None, ge=1, le=16)


class SiteCreate(SiteBase):
    pass


class SiteResponse(SiteBase):
    id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class SiteUpdate(BaseModel):
    name: str | None = None
    address: str | None = None
    timezone: str | None = None
    max_parallel_units: int | None = Field(None, ge=1, le=16)


# ── Panel Schemas ───────────────────────────────────────────────────────
class PanelBase(BaseModel):
    name: str = Field(..., max_length=200)
    transport_type: Literal["tcp", "rtu"] = "tcp"
    address: str = Field(..., max_length=200)
    unit_id: int = Field(1, ge=1, le=255)
    rated_kw: float = Field(..., ge=0)
    rated_kvar: float = Field(0.0, ge=0)
    priority: int | None = Field(None, ge=1, le=1000)


class PanelCreate(PanelBase):
    pass


class PanelUpdate(BaseModel):
    name: str | None = None
    transport_type: Literal["tcp", "rtu"] | None = None
    address: str | None = None
    unit_id: int | None = Field(None, ge=1, le=255)
    rated_kw: float | None = Field(None, ge=0)
    rated_kvar: float | None = Field(None, ge=0)
    priority: int | None = Field(None, ge=1, le=1000)


class PanelResponse(PanelBase):
    id: str
    site_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class ManualCommandRequest(BaseModel):
    reason: str = Field("Manual command initiated by user", max_length=200)


# ── Schedule Schemas ────────────────────────────────────────────────────
class ScheduleItem(BaseModel):
    panel_id: str
    day_of_week: int = Field(..., ge=0, le=6, description="0=Mon, 6=Sun")
    start_time: str = Field("06:00", pattern=r"^\d{2}:\d{2}$")
    end_time: str = Field("18:00", pattern=r"^\d{2}:\d{2}$")
    is_active: bool = True

    @field_validator("start_time", "end_time")
    @classmethod
    def validate_time(cls, v: str) -> str:
        parts = v.split(":")
        h, m = int(parts[0]), int(parts[1])
        if not (0 <= h <= 23 and 0 <= m <= 59):
            raise ValueError(f"Invalid time format: {v}")
        return v


class ScheduleCreate(ScheduleItem):
    pass


class ScheduleUpdate(BaseModel):
    day_of_week: int | None = Field(None, ge=0, le=6)
    start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    is_active: bool | None = None


class ScheduleResponse(ScheduleItem):
    id: str
    site_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BulkScheduleUpdate(BaseModel):
    """Payload to update weekly assignments all at once."""
    schedules: list[ScheduleItem]


class DailyPriorityItem(BaseModel):
    panel_id: str
    day_of_week: int = Field(..., ge=0, le=6)
    priority: int = Field(..., ge=1)


class DailyPriorityResponse(DailyPriorityItem):
    id: str
    site_id: str
    created_at: datetime

    class Config:
        from_attributes = True


class BulkDailyPriorityUpdate(BaseModel):
    """Payload to update backup priorities for all days at once."""
    priorities: list[DailyPriorityItem]


class ScheduleExceptionBase(BaseModel):
    panel_id: str
    exception_date: date
    is_active: bool = True
    start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")


class ScheduleExceptionCreate(ScheduleExceptionBase):
    pass


class ScheduleExceptionUpdate(BaseModel):
    is_active: bool | None = None
    start_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")
    end_time: str | None = Field(None, pattern=r"^\d{2}:\d{2}$")


class ScheduleExceptionResponse(ScheduleExceptionBase):
    id: str
    site_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Threshold Schemas ───────────────────────────────────────────────────
class ThresholdBase(BaseModel):
    panel_id: str | None = None
    start_pct: float = Field(..., ge=10, le=100, description="Start backup when load >= start_pct")
    stop_pct: float = Field(..., ge=0, le=95, description="Stop backup when load <= stop_pct")
    dwell_seconds: int = Field(120, ge=30, le=3600, description="Min seconds before auto-stop")

    @field_validator("stop_pct")
    @classmethod
    def validate_hysteresis(cls, v: float, info) -> float:
        start_pct = info.data.get("start_pct")
        if start_pct is not None and v >= start_pct:
            raise ValueError(
                f"stop_pct ({v}%) must be strictly lower than start_pct ({start_pct}%) to prevent cycling"
            )
        return v


class ThresholdCreate(ThresholdBase):
    pass


class ThresholdUpdate(BaseModel):
    start_pct: float | None = Field(None, ge=10, le=100)
    stop_pct: float | None = Field(None, ge=0, le=95)
    dwell_seconds: int | None = Field(None, ge=30, le=3600)


class ThresholdResponse(ThresholdBase):
    id: str
    site_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Release Threshold Schemas (per-backup-unit) ────────────────────────
class ReleaseThresholdItem(BaseModel):
    panel_id: str
    release_pct: float = Field(..., ge=0, le=100, description="Total facility load % below which this backup releases")
    priority_order: int = Field(..., ge=1, description="Release order — higher priority number released first")


class ReleaseThresholdResponse(ReleaseThresholdItem):
    id: str
    site_id: str
    panel_name: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BulkReleaseThresholdUpdate(BaseModel):
    """Bulk update release thresholds for all backup units in the site."""
    thresholds: list[ReleaseThresholdItem]


# ── Start Threshold Schemas (per-backup-unit, facility load based) ──────
class StartThresholdItem(BaseModel):
    panel_id: str
    start_pct: float = Field(..., ge=0, le=100, description="Total facility load % above which this backup starts")
    priority_order: int = Field(..., ge=1, description="Start order — lower priority number started first")


class StartThresholdResponse(StartThresholdItem):
    id: str
    site_id: str
    panel_name: str | None = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class BulkStartThresholdUpdate(BaseModel):
    """Bulk update start thresholds for all backup units in the site."""
    thresholds: list[StartThresholdItem]


# ── Power Setpoint Schemas ──────────────────────────────────────────────
class PowerSetpointBase(BaseModel):
    panel_id: str
    target_kw_pct: float = Field(..., ge=0, le=100)
    target_kvar_pct: float = Field(0.0, ge=0, le=100)
    is_active: bool = False


class PowerSetpointCreate(PowerSetpointBase):
    pass


class PowerSetpointUpdate(BaseModel):
    target_kw_pct: float | None = Field(None, ge=0, le=100)
    target_kvar_pct: float | None = Field(None, ge=0, le=100)
    is_active: bool | None = None


class PowerSetpointResponse(PowerSetpointBase):
    id: str
    site_id: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


# ── Event Schemas ───────────────────────────────────────────────────────
class EventResponse(BaseModel):
    id: str
    site_id: str
    panel_id: str | None
    event_type: str
    command: str | None
    value: str | None
    triggered_by: str
    reason: str | None
    previous_state: str | None = None
    new_state: str | None = None
    load_kw_at_decision: float | None = None
    capacity_pct_at_decision: float | None = None
    command_result: str | None = None
    user_id: str | None
    timestamp: datetime

    class Config:
        from_attributes = True


# ── Override Schemas ────────────────────────────────────────────────────
class OverrideRequest(BaseModel):
    panel_id: str
    override_type: Literal["force_start", "force_stop"]
    duration_minutes: int = Field(60, ge=5, le=1440, description="Override duration (max 24h)")
    reason: str | None = None


class OverrideResponse(BaseModel):
    id: str
    site_id: str
    panel_id: str
    override_type: str
    created_by: str | None
    expires_at: datetime
    is_active: bool
    reason: str | None
    created_at: datetime

    class Config:
        from_attributes = True


# ── Presets ─────────────────────────────────────────────────────────────
class PresetApplyRequest(BaseModel):
    preset_name: Literal["daily_rotation", "load_following_only", "manual_only"]
    primary_panel_id: str | None = None


# ── Report Schemas ──────────────────────────────────────────────────────
class GeneratorWorkSummary(BaseModel):
    panel_id: str
    name: str
    rated_kw: float
    run_hours: float
    total_kwh: float
    number_of_starts: int
    current_status: str
    avg_load_pct: float
    peak_load_pct: float
    alarm_count: int


class ReportSessionItem(BaseModel):
    id: str
    panel_id: str | None
    panel_name: str
    event_type: str
    command: str | None
    value: str | None
    triggered_by: str
    reason: str | None
    timestamp: datetime


class ReportResponse(BaseModel):
    site_id: str
    site_name: str
    period: str
    total_fleet_hours: float
    total_fleet_kwh: float
    total_fleet_starts: int
    fleet_availability_pct: float
    generators: list[GeneratorWorkSummary]
    recent_sessions: list[ReportSessionItem]

