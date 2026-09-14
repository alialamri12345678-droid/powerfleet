"""Reports API router — generator work summaries, performance KPIs, and CSV export."""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    GeneratorWorkSummary,
    PreventiveMaintenanceReport,
    MaintenanceRecordCreate,
    MaintenanceRecordResponse,
    ReportResponse,
    ReportSessionItem,
)
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_select
from app.dependencies import get_current_user, get_gateway
from app.models.event import Event
from app.models.panel import Panel
from app.models.site import Site
from app.models.telemetry_sample import TelemetrySample
from app.models.maintenance_record import MaintenanceRecord
from app.modbus.gateway import ModbusGateway
from app.services.preventive_maintenance import analyze_generator
from app.db.tenant import scoped_get

router = APIRouter(prefix="/reports", tags=["Reports"])


def _calculate_cutoff(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        return now - timedelta(days=7)
    elif period == "30d":
        return now - timedelta(days=30)
    return None  # all time


async def _build_maintenance_report(
    panel_id: str,
    period: str,
    user: User,
    session: AsyncSession,
    gateway: ModbusGateway | None,
) -> PreventiveMaintenanceReport:
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Generator not found")
    cutoff = _calculate_cutoff(period)
    sample_stmt = scoped_select(TelemetrySample, user.site_id).where(TelemetrySample.panel_id == panel_id)
    event_stmt = scoped_select(Event, user.site_id).where(
        Event.panel_id == panel_id, Event.event_type == "alarm_active"
    )
    if cutoff:
        sample_stmt = sample_stmt.where(TelemetrySample.recorded_at >= cutoff)
        event_stmt = event_stmt.where(Event.timestamp >= cutoff)
    samples = (await session.execute(sample_stmt.order_by(TelemetrySample.recorded_at))).scalars().all()
    alarms = (await session.execute(event_stmt.order_by(Event.timestamp))).scalars().all()
    maintenance_stmt = scoped_select(MaintenanceRecord, user.site_id).where(
        MaintenanceRecord.panel_id == panel_id
    ).order_by(desc(MaintenanceRecord.service_date), desc(MaintenanceRecord.created_at)).limit(1)
    last_service = (await session.execute(maintenance_stmt)).scalars().first()
    live = gateway.states.get(panel_id) if gateway and hasattr(gateway, "states") else None
    report = analyze_generator(panel, list(samples), list(alarms), live, last_service)
    report.update({
        "period": period,
        "generated_at": datetime.now(timezone.utc),
    })
    return PreventiveMaintenanceReport(**report)


@router.get("/preventive-maintenance/{panel_id}/records", response_model=list[MaintenanceRecordResponse])
async def list_maintenance_records(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Generator not found")
    stmt = scoped_select(MaintenanceRecord, user.site_id).where(
        MaintenanceRecord.panel_id == panel_id
    ).order_by(desc(MaintenanceRecord.service_date))
    return (await session.execute(stmt)).scalars().all()


@router.post("/preventive-maintenance/{panel_id}/records", response_model=MaintenanceRecordResponse, status_code=201)
async def record_completed_maintenance(
    panel_id: str,
    body: MaintenanceRecordCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Generator not found")
    record = MaintenanceRecord(
        site_id=user.site_id, panel_id=panel_id, recorded_by=user.id,
        **body.model_dump(),
    )
    session.add(record)
    await session.commit()
    await session.refresh(record)
    return record


@router.get("/preventive-maintenance/{panel_id}", response_model=PreventiveMaintenanceReport)
async def get_preventive_maintenance_report(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
    period: Literal["all", "30d", "7d", "today"] = Query("30d"),
) -> PreventiveMaintenanceReport:
    """Analyze stored readings and alarm history for one generator."""
    return await _build_maintenance_report(panel_id, period, user, session, gateway)


@router.get("/preventive-maintenance/{panel_id}/export")
async def export_preventive_maintenance_report(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
    period: Literal["all", "30d", "7d", "today"] = Query("30d"),
):
    """Export a complete, per-generator preventive-maintenance CSV."""
    report = await _build_maintenance_report(panel_id, period, user, session, gateway)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["PREVENTIVE MAINTENANCE REPORT"])
    writer.writerow(["Generator", report.generator_name])
    writer.writerow(["Controller Profile", report.controller_profile])
    writer.writerow(["Period", report.period.upper()])
    writer.writerow(["Generated At (UTC)", report.generated_at.strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["Condition", report.condition])
    writer.writerow(["Condition Score", f"{report.condition_score}/100"])
    writer.writerow(["History Samples", report.sample_count])
    writer.writerow([])
    writer.writerow(["SERVICE PLANNING"])
    for key, value in report.service.items():
        writer.writerow([key.replace("_", " ").title(), value])
    writer.writerow([])
    writer.writerow(["CURRENT CONTROLLER READINGS"])
    writer.writerow(["Parameter", "Value", "Unit"])
    for key, value in sorted(report.current_readings.items()):
        writer.writerow([key.replace("_", " ").title(), value, report.reading_units.get(key, "")])
    writer.writerow([])
    writer.writerow(["PERIOD TRENDS"])
    writer.writerow(["Parameter", "Minimum", "Average", "Maximum"])
    for key, values in sorted(report.trends.items()):
        writer.writerow([key.replace("_", " ").title(), values["minimum"], values["average"], values["maximum"]])
    writer.writerow([])
    writer.writerow(["FINDINGS AND RECOMMENDATIONS"])
    writer.writerow(["Severity", "Finding", "Evidence", "Recommended Action"])
    if report.findings:
        for finding in report.findings:
            writer.writerow([finding.severity.upper(), finding.title, finding.detail, finding.recommendation])
    else:
        writer.writerow(["INFORMATION", "No condition warning detected", "No configured limit was exceeded in available data.", "Continue routine inspection and servicing."])
    writer.writerow([])
    writer.writerow(["LIMITATIONS"])
    for note in report.limitations:
        writer.writerow([note])
    filename = f"preventive_maintenance_{panel_id[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return Response(
        content=output.getvalue(), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/summary", response_model=ReportResponse)
async def get_report_summary(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
    period: Literal["all", "30d", "7d", "today"] = Query("30d"),
) -> ReportResponse:
    """Generate operational work report summary and fleet KPIs for the active site."""
    site = await session.get(Site, user.site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    # Fetch panels
    p_stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority, Panel.name)
    p_res = await session.execute(p_stmt)
    panels = p_res.scalars().all()

    # Fetch events in period
    cutoff = _calculate_cutoff(period)
    e_stmt = scoped_select(Event, user.site_id)
    if cutoff:
        e_stmt = e_stmt.where(Event.timestamp >= cutoff)
    e_stmt = e_stmt.order_by(desc(Event.timestamp)).limit(200)
    e_res = await session.execute(e_stmt)
    events = e_res.scalars().all()

    telemetry_stmt = select(
        TelemetrySample.panel_id,
        func.min(TelemetrySample.run_hours), func.max(TelemetrySample.run_hours),
        func.min(TelemetrySample.total_kwh), func.max(TelemetrySample.total_kwh),
        func.min(TelemetrySample.number_of_starts), func.max(TelemetrySample.number_of_starts),
        func.avg(case((TelemetrySample.engine_status == "running", TelemetrySample.load_kw_percent), else_=None)),
        func.max(case((TelemetrySample.engine_status == "running", TelemetrySample.load_kw_percent), else_=None)),
    ).where(TelemetrySample.site_id == user.site_id)
    if cutoff:
        telemetry_stmt = telemetry_stmt.where(TelemetrySample.recorded_at >= cutoff)
    telemetry_rows = (await session.execute(telemetry_stmt.group_by(TelemetrySample.panel_id))).all()
    history = {row[0]: row for row in telemetry_rows}

    # Map panel names
    panel_name_map = {p.id: p.name for p in panels}

    # Calculate per-generator metrics
    gen_summaries: list[GeneratorWorkSummary] = []
    total_fleet_hours = 0.0
    total_fleet_kwh = 0.0
    total_fleet_starts = 0
    healthy_count = 0

    for p in panels:
        live = gateway.states.get(p.id) if (gateway and hasattr(gateway, "states")) else None
        row = history.get(p.id)
        run_hours = max(0.0, float(row[2] - row[1])) if row and row[1] is not None else 0.0
        total_kwh = max(0.0, float(row[4] - row[3])) if row and row[3] is not None else 0.0
        start_count = max(0, int(row[6] - row[5])) if row and row[5] is not None else 0
        current_status = live.display_status if live else "Idle"

        # Count alarms in period
        panel_events = [e for e in events if e.panel_id == p.id]
        alarms_in_period = sum(1 for e in panel_events if e.event_type == "alarm_active")

        # Load metrics
        avg_load = float(row[7] or 0.0) if row else 0.0
        peak_load = float(row[8] or 0.0) if row else 0.0

        total_fleet_hours += run_hours
        total_fleet_kwh += total_kwh
        total_fleet_starts += start_count

        if live and live.is_reachable and not live.active_alarms:
            healthy_count += 1

        gen_summaries.append(
            GeneratorWorkSummary(
                panel_id=p.id,
                name=p.name,
                rated_kw=float(p.rated_kw),
                run_hours=round(run_hours, 1),
                total_kwh=round(total_kwh, 1),
                number_of_starts=start_count,
                current_status=current_status,
                avg_load_pct=round(avg_load, 1),
                peak_load_pct=round(peak_load, 1),
                alarm_count=alarms_in_period,
            )
        )

    fleet_availability = (healthy_count / len(panels) * 100.0) if panels else 100.0

    recent_sessions = [
        ReportSessionItem(
            id=e.id,
            panel_id=e.panel_id,
            panel_name=panel_name_map.get(e.panel_id, "Site Level") if e.panel_id else "Site Level",
            event_type=e.event_type,
            command=e.command,
            value=e.value,
            triggered_by=e.triggered_by,
            reason=e.reason,
            timestamp=e.timestamp,
        )
        for e in events[:50]
    ]

    return ReportResponse(
        site_id=site.id,
        site_name=site.name,
        period=period,
        total_fleet_hours=round(total_fleet_hours, 1),
        total_fleet_kwh=round(total_fleet_kwh, 1),
        total_fleet_starts=total_fleet_starts,
        fleet_availability_pct=round(fleet_availability, 1),
        generators=gen_summaries,
        recent_sessions=recent_sessions,
    )


@router.get("/export")
async def export_generator_work_csv(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
    period: Literal["all", "30d", "7d", "today"] = Query("30d"),
):
    """Export generator work report as a downloadable CSV spreadsheet."""
    site = await session.get(Site, user.site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    p_stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority, Panel.name)
    p_res = await session.execute(p_stmt)
    panels = p_res.scalars().all()

    cutoff = _calculate_cutoff(period)
    e_stmt = scoped_select(Event, user.site_id)
    if cutoff:
        e_stmt = e_stmt.where(Event.timestamp >= cutoff)
    e_stmt = e_stmt.order_by(desc(Event.timestamp))
    e_res = await session.execute(e_stmt)
    events = e_res.scalars().all()

    output = io.StringIO()
    writer = csv.writer(output)

    # ── Section 1: Header & Metadata ─────────────────────────────────────
    writer.writerow(["GENERATOR FLEET WORK REPORT"])
    writer.writerow(["Facility Site", site.name])
    writer.writerow(["Reporting Period", period.upper()])
    writer.writerow(["Generated At (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")])
    writer.writerow(["Requested By", user.full_name or user.email])
    writer.writerow([])

    # ── Section 2: Fleet Work Summary ────────────────────────────────────
    writer.writerow(["GENERATOR PERFORMANCE & WORK SUMMARY"])
    writer.writerow([
        "Generator Name",
        "Transport / Address",
        "Unit ID",
        "Rated kW",
        "Accumulated Run Hours",
        "Total Energy (kWh)",
        "Start Cycles",
        "Status",
        "Alarms in Period",
    ])

    for p in panels:
        live = gateway.states.get(p.id) if (gateway and hasattr(gateway, "states")) else None
        run_hours = round(live.run_hours, 1) if live else 0.0
        total_kwh = round(live.total_kwh, 1) if live else 0.0
        start_count = live.number_of_starts if live else 0
        status_word = live.display_status if live else "Idle"
        alarm_count = sum(1 for e in events if e.panel_id == p.id and e.event_type == "alarm_active")

        writer.writerow([
            p.name,
            f"{p.transport_type.upper()} ({p.address})",
            p.unit_id,
            float(p.rated_kw),
            run_hours,
            total_kwh,
            start_count,
            status_word,
            alarm_count,
        ])

    writer.writerow([])

    # ── Section 3: Operational Activity Log ──────────────────────────────
    writer.writerow(["OPERATIONAL WORK & DUTY ACTIVITY LOG"])
    writer.writerow([
        "Timestamp (UTC)",
        "Generator",
        "Event Type",
        "Command",
        "Value / State",
        "Triggered By",
        "Reason / Note",
    ])

    panel_name_map = {p.id: p.name for p in panels}
    for e in events:
        writer.writerow([
            e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            panel_name_map.get(e.panel_id, "Site Level") if e.panel_id else "Site Level",
            e.event_type,
            e.command or "—",
            e.value or "—",
            e.triggered_by,
            e.reason or "—",
        ])

    csv_content = output.getvalue()
    site_slug = site.name.lower().replace(" ", "_")[:20]
    filename = f"generator_work_report_{site_slug}_{period}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"

    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={
            "Content-Disposition": f'attachment; filename="{filename}"',
        },
    )
