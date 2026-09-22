"""Component service plans, early findings, and engineer verification."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
from zoneinfo import ZoneInfo
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_get, scoped_select
from app.dependencies import get_current_user, get_gateway
from app.models.event import Event
from app.models.maintenance_record import MaintenanceRecord
from app.models.maintenance_task import MaintenanceFindingRecord, MaintenanceTask
from app.models.panel import Panel
from app.models.site import Site
from app.models.telemetry_sample import TelemetrySample
from app.modbus.gateway import ModbusGateway
from app.services.maintenance import evaluate_site_maintenance, site_task_status, task_deadline
from app.services.measurement_quality import metric_value, utc
from app.services.performance import report_window

router = APIRouter(prefix="/reports/maintenance", tags=["Preventive maintenance"])

AR_COMPONENT = {"oil": "زيت المحرك", "oil_filter": "فلتر الزيت", "fuel_filter": "فلتر الوقود",
                "air_filter": "فلتر الهواء", "coolant": "سائل التبريد", "battery": "البطارية",
                "belts": "السيور", "hoses": "الخراطيم", "custom": "مهمة مخصصة"}
AR_STATUS = {"scheduled": "مجدولة", "due_soon": "تستحق قريبًا", "overdue": "متأخرة",
             "configuration_required": "تحتاج إلى إعداد", "insufficient_data": "بيانات غير كافية",
             "open": "مفتوحة", "awaiting_verification": "بانتظار التحقق", "resolved": "تم التحقق والإغلاق",
             "warning": "تحذير", "critical": "حرج", "healthy": "لا يوجد خلل مستمر"}
AR_FINDINGS = {
    "coolant_temperature": ("ارتفاع حرارة سائل التبريد عند حمل مماثل", "افحص سائل التبريد وتدفق الهواء والثرموستات والمروحة."),
    "oil_pressure": ("انخفاض ضغط الزيت عند حمل مماثل", "افحص مستوى الزيت ونوعه والمرشحات والتسربات وتحقق بمقياس معاير."),
    "oil_temperature": ("ارتفاع حرارة الزيت عند حمل مماثل", "افحص نظام التزييت والتبريد أثناء الحمل."),
    "battery_voltage": ("انخفاض جهد بطارية التشغيل", "افحص الشحن والأطراف والبطارية وأداء بدء التشغيل."),
    "fuel_efficiency": ("ازدياد الوقود المستهلك للإنتاج نفسه", "افحص الوقود والمرشحات وتوزيع الحمل وحالة المحرك."),
    "alarms": ("إنذارات وحدة التحكم تستلزم الفحص", "عالج سبب الإنذار أو أعد ضبطه في وحدة التحكم وتحقق منه فنيًا."),
}


@router.get("/status/site")
async def site_status(user: Annotated[User, Depends(get_current_user)],
                      session: Annotated[AsyncSession, Depends(get_session)]):
    statuses = await site_task_status(session, user.site_id)
    return {"overdue": sum(item["status"] == "overdue" for item in statuses),
            "due_soon": sum(item["status"] == "due_soon" for item in statuses),
            "tasks": [item for item in statuses if item["status"] in {"overdue", "due_soon"}]}


class TaskInput(BaseModel):
    component: str = Field(max_length=80)
    name: str = Field(min_length=2, max_length=200)
    interval_hours: float | None = Field(None, gt=0, le=100000)
    interval_days: int | None = Field(None, gt=0, le=36500)
    baseline_date: date | None = None
    baseline_run_hours: float | None = Field(None, ge=0)
    manufacturer_reference: str | None = Field(None, max_length=1000)
    active: bool = True

    @model_validator(mode="after")
    def validate_schedule(self):
        if not self.interval_hours and not self.interval_days:
            raise ValueError("Set a running-hour or calendar interval")
        if self.interval_hours and self.baseline_run_hours is None:
            raise ValueError("Running-hour interval requires a verified baseline")
        if self.interval_days and not self.baseline_date:
            raise ValueError("Calendar interval requires a verified baseline")
        return self


class CompletionInput(BaseModel):
    service_date: date
    run_hours: float = Field(ge=0)
    task_ids: list[str] = Field(min_length=1)
    checklist_confirmed: bool
    service_type: str = Field("Preventive service", min_length=2, max_length=100)
    notes: str | None = Field(None, max_length=2000)
    performed_by: str | None = Field(None, max_length=200)


class FindingAction(BaseModel):
    resolution_note: str = Field(min_length=3, max_length=1000)
    inspection_confirmed: bool = False


async def _panel(session, panel_id, user):
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(404, "Generator not found")
    return panel


async def _site_today(session, user):
    site = await session.get(Site, user.site_id)
    if not site or site.organization_id != user.organization_id:
        raise HTTPException(404, "Facility not found")
    return datetime.now(timezone.utc).astimezone(ZoneInfo(site.timezone)).date()


def _audit(user, panel_id, command, value, reason, before, after):
    return Event(site_id=user.site_id, panel_id=panel_id, event_type="system", command=command,
                 value=value[:200] if value else None, triggered_by="manual", reason=reason,
                 previous_state=before, new_state=after, command_result="success", user_id=user.id)


async def _report(session, panel, user, gateway=None, period="30d", start_date=None, end_date=None):
    site = await session.get(Site, user.site_id)
    if not site or site.organization_id != user.organization_id:
        raise HTTPException(404, "Facility not found")
    try:
        start, end = report_window(period, site.timezone, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    await evaluate_site_maintenance(session, user.site_id, gateway=gateway)
    tasks = (await session.execute(scoped_select(MaintenanceTask, user.site_id).where(
        MaintenanceTask.panel_id == panel.id, MaintenanceTask.active.is_(True),
    ).order_by(MaintenanceTask.name))).scalars().all()
    all_records = (await session.execute(scoped_select(MaintenanceRecord, user.site_id).where(
        MaintenanceRecord.panel_id == panel.id,
    ).order_by(desc(MaintenanceRecord.service_date), desc(MaintenanceRecord.created_at)))).scalars().all()
    findings = (await session.execute(scoped_select(MaintenanceFindingRecord, user.site_id).where(
        MaintenanceFindingRecord.panel_id == panel.id,
    ).order_by(desc(MaintenanceFindingRecord.first_detected_at)))).scalars().all()
    samples_stmt = scoped_select(TelemetrySample, user.site_id).where(
        TelemetrySample.panel_id == panel.id, TelemetrySample.recorded_at < end)
    if start:
        samples_stmt = samples_stmt.where(TelemetrySample.recorded_at >= start)
    samples = (await session.execute(samples_stmt.order_by(TelemetrySample.recorded_at))).scalars().all()
    start_day = start.astimezone(ZoneInfo(site.timezone)).date() if start else None
    local_end = end.astimezone(ZoneInfo(site.timezone))
    end_day = local_end.date() + (timedelta(days=1) if local_end.time() != datetime.min.time() else timedelta())
    records = [row for row in all_records if (start_day is None or row.service_date >= start_day)
               and row.service_date < end_day]
    valid_hours = [(utc(s.recorded_at), metric_value(s, "run_hours")) for s in samples]
    valid_hours = [(timestamp, value) for timestamp, value in valid_hours if value is not None]
    latest_sample = (await session.execute(scoped_select(TelemetrySample, user.site_id).where(
        TelemetrySample.panel_id == panel.id,
    ).order_by(desc(TelemetrySample.recorded_at)).limit(1))).scalars().first()
    current = (metric_value(latest_sample, "run_hours") if latest_sample and
               utc(latest_sample.recorded_at) >= datetime.now(timezone.utc) - timedelta(minutes=10) else None)
    usage = None
    if len(valid_hours) >= 2:
        time_span = (valid_hours[-1][0] - valid_hours[0][0]).total_seconds() / 86400
        if time_span >= 1 and valid_hours[-1][1] >= valid_hours[0][1]:
            usage = (valid_hours[-1][1] - valid_hours[0][1]) / time_span
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(site.timezone)).date()
    # Deadlines use full service history and current telemetry, not the report's
    # selected history window. A historical filter must never reset a task.
    scheduled = [task_deadline(task, all_records, current, today, usage) for task in tasks]
    due_count = sum(t["status"] == "overdue" for t in scheduled)
    configured = [t for t in scheduled if t["status"] not in ("configuration_required", "insufficient_data")]
    compliance = round(100 * (len(configured) - due_count) / len(configured), 1) if configured else None
    monitored = ("coolant_temperature", "oil_pressure", "battery_voltage", "frequency", "load_kw")
    coverage = (round(100 * sum(metric_value(s, key) is not None for s in samples for key in monitored)
                      / (len(samples) * len(monitored)), 1) if samples else 0)
    active = [f for f in findings if f.status != "resolved"]
    history_findings = [f for f in findings if (start is None or utc(f.first_detected_at) >= start)
                        and utc(f.first_detected_at) < end]
    recent_valid = sum(1 for s in samples[-10:] if utc(s.recorded_at) >= datetime.now(timezone.utc) - timedelta(minutes=15)
                       and metric_value(s, "coolant_temperature") is not None and metric_value(s, "oil_pressure") is not None)
    condition = ("insufficient_data" if coverage < 50 or recent_valid < 3 else
                 "critical" if any(f.severity == "critical" for f in active) else
                 "attention" if active else "healthy")
    def record(row):
        return {"id": row.id, "service_date": row.service_date.isoformat(), "run_hours": row.run_hours,
                "service_type": row.service_type, "performed_by": row.performed_by, "notes": row.notes,
                "task_ids": row.task_ids or [], "checklist_confirmed": row.checklist_confirmed}
    def finding(row):
        return {"id": row.id, "metric": row.metric, "severity": row.severity, "title": row.title,
                "detail": row.detail, "recommendation": row.recommendation, "status": row.status,
                "verification_kind": row.verification_kind, "evidence": row.evidence or {},
                "first_detected_at": row.first_detected_at.isoformat(),
                "last_detected_at": row.last_detected_at.isoformat(),
                "work_recorded_at": row.work_recorded_at.isoformat() if row.work_recorded_at else None,
                "resolved_at": row.resolved_at.isoformat() if row.resolved_at else None,
                "resolution_note": row.resolution_note}
    return {"panel_id": panel.id, "generator_name": panel.name,
            "generated_at": datetime.now(timezone.utc).isoformat(), "timezone": site.timezone,
            "period": period, "start_at": start.isoformat() if start else None, "end_at": end.isoformat(),
            "maintenance_compliance_percent": compliance, "monitored_condition": condition,
            "data_coverage_percent": coverage, "sample_count": len(samples), "current_run_hours": current,
            "tasks": scheduled, "findings": [finding(f) for f in active],
            "finding_history": [finding(f) for f in history_findings], "service_history": [record(r) for r in records],
            "limitations": ["Only commissioned, fresh measurements are analyzed; unsupported sensors remain unknown.",
                            "A satisfactory report supports planning but does not certify physical condition."]}


@router.get("/{panel_id}")
async def get_report(panel_id: str, user: Annotated[User, Depends(get_current_user)],
                     session: Annotated[AsyncSession, Depends(get_session)],
                     gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
                     period: Literal["today", "7d", "30d", "all", "custom"] = "30d",
                     start_date: date | None = None, end_date: date | None = None):
    panel = await _panel(session, panel_id, user)
    result = await _report(session, panel, user, gateway, period, start_date, end_date)
    await session.commit()
    return result


@router.post("/{panel_id}/tasks", status_code=201)
async def add_task(panel_id: str, body: TaskInput, user: Annotated[User, Depends(get_current_user)],
                   session: Annotated[AsyncSession, Depends(get_session)]):
    await _panel(session, panel_id, user)
    if body.baseline_date and body.baseline_date > await _site_today(session, user):
        raise HTTPException(422, "Baseline date cannot be in the future")
    task = MaintenanceTask(site_id=user.site_id, panel_id=panel_id, **body.model_dump())
    session.add(task)
    session.add(_audit(user, panel_id, "maintenance_task", body.name, "Configured manufacturer service schedule", None, "active"))
    await session.commit()
    return {"id": task.id}


@router.patch("/{panel_id}/tasks/{task_id}")
async def update_task(panel_id: str, task_id: str, body: TaskInput,
                      user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)]):
    await _panel(session, panel_id, user)
    task = await scoped_get(session, MaintenanceTask, task_id, user.site_id)
    if task is None or task.panel_id != panel_id:
        raise HTTPException(404, "Service task not found")
    if body.baseline_date and body.baseline_date > await _site_today(session, user):
        raise HTTPException(422, "Baseline date cannot be in the future")
    before = "active" if task.active else "archived"
    for key, value in body.model_dump().items():
        setattr(task, key, value)
    session.add(_audit(user, panel_id, "maintenance_task", body.name, "Updated manufacturer service schedule", before,
                       "active" if task.active else "archived"))
    await session.commit()
    return {"id": task.id}


@router.delete("/{panel_id}/tasks/{task_id}")
async def archive_task(panel_id: str, task_id: str, user: Annotated[User, Depends(get_current_user)],
                       session: Annotated[AsyncSession, Depends(get_session)]):
    await _panel(session, panel_id, user)
    task = await scoped_get(session, MaintenanceTask, task_id, user.site_id)
    if not task or task.panel_id != panel_id:
        raise HTTPException(404, "Service task not found")
    task.active = False
    session.add(_audit(user, panel_id, "maintenance_task", task.name, "Archived service task", "active", "archived"))
    await session.commit()
    return {"status": "archived"}


@router.post("/{panel_id}/complete", status_code=201)
async def complete_tasks(panel_id: str, body: CompletionInput, user: Annotated[User, Depends(get_current_user)],
                         session: Annotated[AsyncSession, Depends(get_session)]):
    await _panel(session, panel_id, user)
    selected = set(body.task_ids)
    if not body.checklist_confirmed or len(selected) != len(body.task_ids):
        raise HTTPException(422, "Confirm completed tasks and select each only once")
    tasks = (await session.execute(scoped_select(MaintenanceTask, user.site_id).where(
        MaintenanceTask.panel_id == panel_id, MaintenanceTask.active.is_(True), MaintenanceTask.id.in_(selected),
    ))).scalars().all()
    if len(tasks) != len(selected):
        raise HTTPException(422, "Every selected task must be active for this generator")
    if body.service_date > await _site_today(session, user):
        raise HTTPException(422, "Service date cannot be in the future")
    record = MaintenanceRecord(site_id=user.site_id, panel_id=panel_id, recorded_by=user.id,
                               **body.model_dump())
    session.add(record)
    session.add(_audit(user, panel_id, "maintenance_complete", ", ".join(t.component for t in tasks),
                       body.notes or "Confirmed service checklist", "due", "completed"))
    await session.commit()
    return {"id": record.id, "task_ids": record.task_ids}


@router.post("/{panel_id}/findings/{finding_id}/work")
async def record_work(panel_id: str, finding_id: str, body: FindingAction,
                      user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)],
                      gateway: Annotated[ModbusGateway | None, Depends(get_gateway)]):
    await _panel(session, panel_id, user)
    finding = await scoped_get(session, MaintenanceFindingRecord, finding_id, user.site_id)
    if finding is None or finding.panel_id != panel_id:
        raise HTTPException(404, "Finding not found")
    if finding.status == "resolved":
        raise HTTPException(409, "Finding is already verified")
    before = finding.status
    if finding.verification_kind == "inspection":
        if not body.inspection_confirmed:
            raise HTTPException(422, "Engineer inspection checklist must be confirmed")
    finding.status = "awaiting_verification"
    finding.work_recorded_at = datetime.now(timezone.utc)
    finding.recorded_by = user.id
    finding.resolution_note = body.resolution_note
    session.add(_audit(user, panel_id, "maintenance_work", finding.metric, body.resolution_note,
                       before, finding.status))
    await session.commit()
    return {"status": finding.status, "id": finding.id}


@router.post("/{panel_id}/findings/{finding_id}/verify")
async def verify_inspection(panel_id: str, finding_id: str, body: FindingAction,
                            user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)],
                            gateway: Annotated[ModbusGateway | None, Depends(get_gateway)]):
    await _panel(session, panel_id, user)
    finding = await scoped_get(session, MaintenanceFindingRecord, finding_id, user.site_id)
    if not finding or finding.panel_id != panel_id:
        raise HTTPException(404, "Finding not found")
    if finding.verification_kind != "inspection" or not body.inspection_confirmed or finding.status != "awaiting_verification":
        raise HTTPException(422, "Only confirmed inspection findings can be manually verified")
    if finding.metric == "alarms":
        state = gateway.states.get(panel_id) if gateway and hasattr(gateway, "states") else None
        if state and state.active_alarms:
            raise HTTPException(409, "Controller still reports active alarms")
        latest = (await session.execute(scoped_select(TelemetrySample, user.site_id).where(
            TelemetrySample.panel_id == panel_id,
        ).order_by(desc(TelemetrySample.recorded_at)).limit(1))).scalars().first()
        if (not latest or not latest.is_reachable or latest.active_alarm_count or
                utc(latest.recorded_at) <= utc(finding.work_recorded_at) or
                utc(latest.recorded_at) < datetime.now(timezone.utc) - timedelta(minutes=5)):
            raise HTTPException(409, "A newer, alarm-free controller reading is required")
    finding.status = "resolved"
    finding.resolved_at = datetime.now(timezone.utc)
    finding.resolution_note = body.resolution_note
    finding.recorded_by = user.id
    session.add(_audit(user, panel_id, "maintenance_verify", finding.metric, body.resolution_note,
                       "awaiting_verification", "resolved"))
    await session.commit()
    return {"status": "resolved", "id": finding.id}


@router.get("/{panel_id}/export")
async def export_report(panel_id: str, user: Annotated[User, Depends(get_current_user)],
                        session: Annotated[AsyncSession, Depends(get_session)],
                        gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
                        locale: Literal["en", "ar"] = "en",
                        period: Literal["today", "7d", "30d", "all", "custom"] = "30d",
                        start_date: date | None = None, end_date: date | None = None):
    report = await _report(session, await _panel(session, panel_id, user), user, gateway, period, start_date, end_date)
    out = io.StringIO()
    writer = csv.writer(out)
    ar = locale == "ar"
    writer.writerow(["الصيانة الوقائية" if ar else "Preventive maintenance", report["generator_name"]])
    writer.writerow(["المنطقة الزمنية" if ar else "Timezone", report["timezone"]])
    writer.writerow(["من (UTC)" if ar else "From (UTC)", report["start_at"] or "—"])
    writer.writerow(["إلى (UTC)" if ar else "To (UTC)", report["end_at"]])
    writer.writerow(["الالتزام بالصيانة (%)" if ar else "Maintenance compliance (%)", report["maintenance_compliance_percent"]])
    writer.writerow(["الحالة المرصودة" if ar else "Monitored condition", AR_STATUS.get(report["monitored_condition"], report["monitored_condition"]) if ar else report["monitored_condition"]])
    writer.writerow(["تغطية البيانات (%)" if ar else "Data coverage (%)", report["data_coverage_percent"]])
    writer.writerow([])
    writer.writerow(["مهام الصيانة" if ar else "Service tasks"])
    writer.writerow(["المكوّن", "المهمة", "الحالة", "الفاصل (ساعة)", "الفاصل (يوم)", "موعد التشغيل", "موعد التقويم", "المتبقي (ساعة)", "المتبقي (يوم)", "مرجع الشركة المصنعة"] if ar else
                    ["Component", "Task", "Status", "Interval (hours)", "Interval (days)", "Due at hours", "Due date", "Hours remaining", "Days remaining", "Manufacturer reference"])
    for task in report["tasks"]:
        writer.writerow([AR_COMPONENT.get(task["component"], task["component"]) if ar else task["component"], task["name"],
                         AR_STATUS.get(task["status"], task["status"]) if ar else task["status"],
                         *[task[k] for k in ("interval_hours", "interval_days", "next_due_run_hours", "next_due_date", "remaining_hours", "remaining_days", "manufacturer_reference")]])
    writer.writerow([])
    writer.writerow(["النتائج والمتابعة" if ar else "Condition findings"])
    writer.writerow(["النتيجة", "الخطورة", "الحالة", "الدليل", "الإجراء", "رُصدت أول مرة", "إجراء المهندس"] if ar else
                    ["Finding", "Severity", "Status", "Evidence", "Recommendation", "First detected", "Engineer action"])
    for finding in report["finding_history"]:
        if ar and finding["metric"] in AR_FINDINGS:
            title, recommendation = AR_FINDINGS[finding["metric"]]
            evidence = finding["evidence"]
            detail = (f"تغيرت القراءة من {evidence['baseline']:.2f} إلى {evidence['trigger']:.2f} في ظروف تشغيل مماثلة."
                      if "baseline" in evidence and "trigger" in evidence else "إنذارات نشطة بوحدة التحكم تحتاج للفحص.")
        else:
            title, detail, recommendation = finding["title"], finding["detail"], finding["recommendation"]
        writer.writerow([title, AR_STATUS.get(finding["severity"], finding["severity"]) if ar else finding["severity"],
                         AR_STATUS.get(finding["status"], finding["status"]) if ar else finding["status"],
                         detail, recommendation, finding["first_detected_at"], finding["resolution_note"]])
    writer.writerow([])
    writer.writerow(["سجل الصيانة المنجزة" if ar else "Completed service history"])
    writer.writerow(["التاريخ", "ساعات التشغيل", "النوع", "المنفذ", "الملاحظات", "المهام المرتبطة"] if ar else
                    ["Date", "Run hours", "Type", "Performed by", "Notes", "Linked tasks"])
    for record in report["service_history"]:
        writer.writerow([record["service_date"], record["run_hours"], record["service_type"], record["performed_by"],
                         record["notes"], "; ".join(record["task_ids"])])
    await session.commit()
    return Response(content="\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="preventive_maintenance_{locale}_{panel_id[:8]}.csv"'})
