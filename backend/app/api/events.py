"""Events API router — site-scoped audit trail access and retention controls."""

import csv
import io
from datetime import datetime, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import delete, desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import EventResponse
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_select
from app.dependencies import get_current_user
from app.models.event import Event
from app.models.panel import Panel
from app.models.site import Site

router = APIRouter(prefix="/events", tags=["Events"])

ARABIC_CODES = {
    "all": "الكل", "command_sent": "تم إرسال أمر", "alarm_active": "إنذار نشط",
    "alarm_cleared": "تم مسح الإنذار", "override": "تجاوز", "system": "النظام / تنبيه",
    "remote_start": "تشغيل عن بُعد", "remote_stop": "إيقاف عن بُعد",
    "force_start": "فرض التشغيل", "force_stop": "فرض الإيقاف",
    "manual": "يدوي", "automatic": "آلي", "schedule": "الجدول",
    "threshold": "حد الحمل", "dispatcher": "موزع الأحمال الآلي", "customer": "العميل",
    "running": "يعمل", "stopped": "متوقف", "unknown": "غير معروف",
    "success": "نجاح", "failed": "فشل", "rejected": "مرفوض",
    "confirmed": "مؤكد", "acknowledged": "تم الاستلام", "on": "تشغيل", "off": "إيقاف",
}


def _localize_code(value: str | None, locale: str) -> str:
    if not value:
        return ""
    if locale == "ar":
        return ARABIC_CODES.get(value.lower(), value)
    return value


def _filtered_events(site_id: str, panel_id: str | None, event_type: str | None):
    stmt = scoped_select(Event, site_id)
    if panel_id:
        stmt = stmt.where(Event.panel_id == panel_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)
    return stmt


@router.get("", response_model=list[EventResponse])
async def list_events(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    panel_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[EventResponse]:
    """Retrieve immutable audit log events scoped to the site."""
    stmt = _filtered_events(user.site_id, panel_id, event_type)
    stmt = stmt.order_by(desc(Event.timestamp)).limit(limit).offset(offset)
    result = await session.execute(stmt)
    events = result.scalars().all()

    return [EventResponse.model_validate(e) for e in events]


@router.get("/export")
async def export_events_csv(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    panel_id: str | None = None,
    event_type: str | None = None,
    locale: Literal["en", "ar"] = "en",
) -> Response:
    """Export every audit event matching the current site and filters."""
    events = (await session.execute(
        _filtered_events(user.site_id, panel_id, event_type).order_by(desc(Event.timestamp))
    )).scalars().all()
    panels = (await session.execute(scoped_select(Panel, user.site_id))).scalars().all()
    panel_names = {panel.id: panel.name for panel in panels}
    site = await session.get(Site, user.site_id)
    selected_panel = panel_names.get(panel_id) if panel_id else None
    exported_at = datetime.now(timezone.utc)

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if locale == "ar":
        writer.writerow(["عوامل التصفية المطبقة"])
        writer.writerow(["الموقع", site.name if site else user.site_id])
        writer.writerow(["المولد", selected_panel or ("مولد محذوف" if panel_id else "كل الوحدات")])
        writer.writerow(["نوع الحدث", _localize_code(event_type, locale) if event_type else "كل الأحداث"])
        writer.writerow(["وقت التصدير (UTC)", exported_at.isoformat()])
        writer.writerow(["عدد السجلات", len(events)])
        writer.writerow([])
        writer.writerow([
            "الوقت (UTC)", "المولد", "معرّف اللوحة", "نوع الحدث", "الأمر",
            "القيمة", "تم بواسطة", "السبب", "الحالة السابقة", "الحالة الجديدة",
            "الحمل عند القرار (kW)", "نسبة القدرة عند القرار (%)", "نتيجة الأمر", "معرّف المستخدم",
        ])
    else:
        writer.writerow(["Applied Filters"])
        writer.writerow(["Site", site.name if site else user.site_id])
        writer.writerow(["Generator", selected_panel or ("Deleted generator" if panel_id else "All Units")])
        writer.writerow(["Event Type", event_type or "All Events"])
        writer.writerow(["Exported At (UTC)", exported_at.isoformat()])
        writer.writerow(["Record Count", len(events)])
        writer.writerow([])
        writer.writerow([
            "Timestamp (UTC)", "Generator", "Panel ID", "Event Type", "Command",
            "Value", "Triggered By", "Reason", "Previous State", "New State",
            "Load kW at Decision", "Capacity % at Decision", "Command Result", "User ID",
        ])
    for event in events:
        timestamp = event.timestamp
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        writer.writerow([
            timestamp.astimezone(timezone.utc).isoformat(),
            panel_names.get(event.panel_id, ("الموقع / النظام" if locale == "ar" else "Site / System") if not event.panel_id else ("مولد محذوف" if locale == "ar" else "Deleted generator")),
            event.panel_id or "", _localize_code(event.event_type, locale),
            _localize_code(event.command, locale), _localize_code(event.value, locale),
            _localize_code(event.triggered_by, locale), event.reason or "",
            _localize_code(event.previous_state, locale), _localize_code(event.new_state, locale),
            event.load_kw_at_decision if event.load_kw_at_decision is not None else "",
            event.capacity_pct_at_decision if event.capacity_pct_at_decision is not None else "",
            _localize_code(event.command_result, locale), event.user_id or "",
        ])

    filename = f"audit_log_{locale}_{exported_at.date().isoformat()}.csv"
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.delete("")
async def clear_events(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    panel_id: str | None = None,
    event_type: str | None = None,
) -> dict[str, int]:
    """Permanently clear audit events matching the current site and filters."""
    criteria = [Event.site_id == user.site_id]
    if panel_id:
        criteria.append(Event.panel_id == panel_id)
    if event_type:
        criteria.append(Event.event_type == event_type)
    result = await session.execute(delete(Event).where(*criteria))
    await session.commit()
    return {"deleted_count": result.rowcount or 0}
