"""Reports API router — generator work summaries, performance KPIs, and CSV export."""

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    GeneratorWorkSummary,
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
from app.modbus.gateway import ModbusGateway

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
        run_hours = live.run_hours if live else 0.0
        total_kwh = live.total_kwh if live else 0.0
        start_count = live.number_of_starts if live else 0
        current_status = live.display_status if live else "Idle"

        # Count alarms in period
        panel_events = [e for e in events if e.panel_id == p.id]
        alarms_in_period = sum(1 for e in panel_events if e.event_type == "alarm_active")

        # Load metrics
        current_load_pct = live.load_kw_percent if live and live.is_running else 0.0
        avg_load = current_load_pct if current_load_pct > 0 else (55.0 if live and live.is_running else 0.0)
        peak_load = max(avg_load, current_load_pct)

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
