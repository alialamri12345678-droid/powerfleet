"""Reports API router — generator work summaries, performance KPIs, and CSV export."""

import csv
import io
import re
from datetime import datetime, timedelta, timezone
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import case, desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    GeneratorWorkSummary,
    MaintenanceAlarmClearRequest,
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

ARABIC_CODES = {
    "command_sent": "تم إرسال أمر", "alarm_active": "إنذار نشط",
    "alarm_cleared": "تم مسح الإنذار", "status_change": "تغير الحالة",
    "override": "تجاوز", "system": "النظام", "remote_start": "تشغيل عن بُعد",
    "remote_stop": "إيقاف عن بُعد", "force_start": "فرض التشغيل",
    "force_stop": "فرض الإيقاف", "manual": "يدوي", "automatic": "آلي",
    "schedule": "الجدول", "threshold": "حد الحمل", "dispatcher": "موزع الأحمال الآلي",
    "running": "يعمل", "stopped": "متوقف", "idle": "خامل", "on": "تشغيل",
    "off": "إيقاف", "success": "نجاح", "failed": "فشل", "critical": "حرج",
    "warning": "تحذير", "information": "معلومات",
    "emergency_stop": "إيقاف طارئ", "low_oil_pressure": "انخفاض ضغط الزيت",
    "high_coolant_temperature": "ارتفاع حرارة سائل التبريد",
    "high_coolant_temp": "ارتفاع حرارة سائل التبريد", "high_oil_temperature": "ارتفاع حرارة الزيت",
    "underspeed": "انخفاض السرعة", "overspeed": "ارتفاع السرعة",
    "fail_to_start": "فشل التشغيل", "fail_to_stop": "فشل الإيقاف",
    "loss_of_speed_sensing": "فقدان إشارة السرعة", "loss_of_speed_signal": "فقدان إشارة السرعة",
    "generator_low_voltage": "انخفاض جهد المولد", "generator_under_voltage": "انخفاض جهد المولد",
    "generator_high_voltage": "ارتفاع جهد المولد", "generator_over_voltage": "ارتفاع جهد المولد",
    "generator_low_frequency": "انخفاض تردد المولد", "generator_under_frequency": "انخفاض تردد المولد",
    "generator_high_frequency": "ارتفاع تردد المولد", "generator_over_frequency": "ارتفاع تردد المولد",
    "generator_high_current": "ارتفاع تيار المولد", "generator_earth_fault": "تسرب أرضي في المولد",
    "generator_reverse_power": "قدرة عكسية للمولد", "air_flap": "بوابة الهواء",
    "oil_pressure_sender_fault": "عطل حساس ضغط الزيت",
    "coolant_temperature_sender_fault": "عطل حساس حرارة سائل التبريد",
    "oil_temperature_sender_fault": "عطل حساس حرارة الزيت",
    "fuel_level_sender_fault": "عطل حساس مستوى الوقود", "magnetic_pickup_fault": "عطل الحساس المغناطيسي",
    "loss_of_ac_speed_signal": "فقدان إشارة سرعة التيار المتردد",
    "charge_alternator_failure": "فشل مولد الشحن", "charge_alternator_fail": "فشل مولد الشحن",
    "low_battery_voltage": "انخفاض جهد البطارية", "battery_under_voltage": "انخفاض جهد البطارية",
    "high_battery_voltage": "ارتفاع جهد البطارية", "battery_over_voltage": "ارتفاع جهد البطارية",
    "low_fuel_level": "انخفاض مستوى الوقود", "fuel_level_low": "انخفاض مستوى الوقود",
    "high_fuel_level": "ارتفاع مستوى الوقود", "fuel_level_high": "ارتفاع مستوى الوقود",
    "generator_failed_to_close": "فشل إغلاق قاطع المولد", "mains_failed_to_close": "فشل إغلاق قاطع الشبكة",
    "generator_failed_to_open": "فشل فتح قاطع المولد", "mains_failed_to_open": "فشل فتح قاطع الشبكة",
}

ARABIC_METRICS = {
    "manufacturer_code": "رمز الشركة المصنعة", "model_number": "رقم الطراز",
    "control_mode": "وضع التحكم", "controller_status": "حالة وحدة التحكم",
    "generator_state": "حالة المولد", "oil_pressure": "ضغط الزيت",
    "coolant_temperature": "درجة حرارة سائل التبريد", "oil_temperature": "درجة حرارة الزيت",
    "fuel_level_percent": "مستوى الوقود", "charge_alternator_voltage": "جهد مولد الشحن",
    "battery_voltage": "جهد بطارية التشغيل", "engine_speed": "سرعة المحرك",
    "frequency": "تردد المولد", "voltage_l1_n": "جهد L1-N",
    "voltage_l2_n": "جهد L2-N", "voltage_l3_n": "جهد L3-N",
    "voltage_l1_l2": "جهد L1-L2", "voltage_l2_l3": "جهد L2-L3",
    "voltage_l3_l1": "جهد L3-L1", "current_l1": "تيار L1",
    "current_l2": "تيار L2", "current_l3": "تيار L3",
    "power_l1_kw": "قدرة L1", "power_l2_kw": "قدرة L2", "power_l3_kw": "قدرة L3",
    "load_kw": "الحمل الفعلي", "load_kva": "الحمل الظاهري", "load_kvar": "الحمل غير الفعال",
    "power_factor": "معامل القدرة", "load_kw_percent": "نسبة حمل المولد",
    "load_kvar_percent": "نسبة الحمل غير الفعال", "run_hours": "ساعات التشغيل",
    "total_kwh": "إجمالي الطاقة", "number_of_starts": "عدد مرات التشغيل",
    "fuel_used_litres": "الوقود المستهلك", "active_alarm_count": "عدد الإنذارات النشطة",
    "alarms": "الإنذارات",
}

ARABIC_MAINTENANCE_TEXT = {
    "Attention required": "تتطلب الحالة اهتمامًا",
    "Plan maintenance": "خطط للصيانة",
    "No condition warning detected": "لم يتم اكتشاف تحذير في الحالة",
    "Routine service interval is approaching": "موعد الصيانة الدورية يقترب",
    "Routine service interval reached": "حان موعد الصيانة الدورية",
    "Inspect coolant level, radiator airflow, hoses and thermostat before the next loaded run.": "افحص مستوى سائل التبريد وتدفق هواء المشع والخراطيم ومنظم الحرارة قبل التشغيل التالي تحت الحمل.",
    "Verify oil level and grade, inspect for leaks, and confirm pressure with a calibrated instrument.": "تحقق من مستوى الزيت ودرجته وافحص التسربات وأكد الضغط باستخدام أداة معايرة.",
    "Inspect terminals and charging system, then load-test the starter battery.": "افحص أقطاب البطارية ونظام الشحن ثم اختبر بطارية التشغيل تحت الحمل.",
    "Refuel and inspect the tank, transfer pump, filters and level sender.": "أعد التزود بالوقود وافحص الخزان ومضخة النقل والمرشحات وحساس المستوى.",
    "Check speed control/governor behavior and confirm the configured nominal frequency.": "افحص سلوك منظم السرعة وتأكد من التردد الاسمي المهيأ.",
    "Review load sharing and capacity; inspect the unit if overload occurred.": "راجع تقاسم الحمل والقدرة وافحص الوحدة إذا حدث حمل زائد.",
    "Review the alarm history and close out the underlying causes before relying on the unit.": "راجع سجل الإنذارات وعالج أسبابها الأساسية قبل الاعتماد على الوحدة.",
    "Plan the manufacturer-prescribed service and record completion in the maintenance system.": "خطط للصيانة المقررة من الشركة المصنعة وسجّل اكتمالها في نظام الصيانة.",
    "This report supports preventive maintenance planning; it does not replace inspection or the engine manufacturer's service schedule.": "يدعم هذا التقرير تخطيط الصيانة الوقائية ولا يغني عن الفحص أو جدول صيانة المحرك الخاص بالشركة المصنعة.",
    "Accuracy depends on commissioned controller addresses, scaling and sensor calibration.": "تعتمد الدقة على صحة عناوين وحدة التحكم ومعاملات التحويل ومعايرة الحساسات عند التشغيل.",
    "No configured limit was exceeded in available data.": "لم تتجاوز البيانات المتاحة أي حد مهيأ.",
    "Continue routine inspection and servicing.": "استمر في الفحص والصيانة الدورية.",
}

ARABIC_SERVICE_KEYS = {
    "current_run_hours": "ساعات التشغيل الحالية", "service_interval_hours": "فاصل الصيانة بالساعات",
    "next_service_hours": "موعد الصيانة التالي بالساعات", "hours_remaining": "الساعات المتبقية",
    "last_service_hours": "ساعات التشغيل عند آخر صيانة",
}


def _localize_code(value: str | None, locale: str) -> str:
    if not value:
        return ""
    return ARABIC_CODES.get(value.lower(), value) if locale == "ar" else value


def _localize_period(period: str, locale: str) -> str:
    if locale != "ar":
        return period.upper()
    return {"today": "اليوم", "7d": "آخر 7 أيام", "30d": "آخر 30 يومًا", "all": "كل المدة"}[period]


def _localize_metric(key: str, locale: str) -> str:
    if locale == "ar":
        return ARABIC_METRICS.get(key, key.replace("_", " "))
    return key.replace("_", " ").title()


def _localize_service_type(value: str, locale: str) -> str:
    if locale != "ar":
        return value
    if value == "Routine service":
        return "صيانة دورية"
    match = re.match(r"^(\d+)-hour service$", value, re.IGNORECASE)
    return f"صيانة {match.group(1)} ساعة" if match else value


def _localize_maintenance_text(value: str, locale: str) -> str:
    if locale != "ar":
        return value
    if value in ARABIC_MAINTENANCE_TEXT:
        return ARABIC_MAINTENANCE_TEXT[value]
    match = re.match(r"^(.+) requires attention$", value)
    if match:
        labels = {
            "Coolant temperature": "درجة حرارة سائل التبريد", "Oil pressure": "ضغط الزيت",
            "Starter battery voltage": "جهد بطارية التشغيل", "Fuel level": "مستوى الوقود",
            "Generator frequency": "تردد المولد", "Generator load": "حمل المولد",
        }
        return f"{labels.get(match.group(1), match.group(1))} يتطلب الاهتمام"
    match = re.match(r"^(Maximum|Minimum) (.+) (reached|was) ([\d.]+) (.+)\.$", value)
    if match:
        labels = {
            "coolant temperature": "درجة حرارة سائل التبريد", "oil pressure": "ضغط الزيت",
            "starter battery voltage": "جهد بطارية التشغيل", "fuel level": "مستوى الوقود",
            "generator frequency": "تردد المولد", "generator load": "حمل المولد",
        }
        extreme = "أقصى" if match.group(1) == "Maximum" else "أدنى"
        verb = "بلغ" if match.group(3) == "reached" else "كان"
        return f"{extreme} {labels.get(match.group(2), match.group(2))} {verb} {match.group(4)} {match.group(5)}."
    match = re.match(r"^(\d+) alarm occurrence\(s\) recorded$", value)
    if match:
        return f"تم تسجيل {match.group(1)} حالة إنذار"
    match = re.match(r"^Approximately ([\d.]+) running hours remain to the ([\d.]+)-hour interval\.$", value)
    if match:
        return f"يتبقى نحو {match.group(1)} ساعة تشغيل حتى موعد الصيانة عند {match.group(2)} ساعة."
    original_parts = value.split(", ")
    alarm_parts = [_localize_code(part, locale) for part in original_parts]
    if alarm_parts != original_parts:
        return "، ".join(alarm_parts)
    return value


def _csv_response(output: io.StringIO, filename: str) -> Response:
    return Response(
        content=output.getvalue().encode("utf-8-sig"),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _calculate_cutoff(period: str) -> datetime | None:
    now = datetime.now(timezone.utc)
    if period == "today":
        return now.replace(hour=0, minute=0, second=0, microsecond=0)
    elif period == "7d":
        return now - timedelta(days=7)
    elif period == "30d":
        return now - timedelta(days=30)
    return None  # all time


def _unresolved_alarm_events(events: list[Event]) -> list[Event]:
    """Pair alarm activations with controller or engineer clearance events."""
    unresolved: dict[str, Event] = {}
    for event in events:
        if event.event_type == "alarm_active":
            unresolved[event.value or event.id] = event
        elif event.event_type == "alarm_cleared" and event.command == "maintenance_clear":
            unresolved.clear()
        elif event.event_type == "alarm_cleared" and event.value:
            unresolved.pop(event.value, None)
    return list(unresolved.values())


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
        Event.panel_id == panel_id, Event.event_type.in_(["alarm_active", "alarm_cleared"])
    )
    if cutoff:
        sample_stmt = sample_stmt.where(TelemetrySample.recorded_at >= cutoff)
        event_stmt = event_stmt.where(Event.timestamp >= cutoff)
    samples = (await session.execute(sample_stmt.order_by(TelemetrySample.recorded_at))).scalars().all()
    alarm_events = (await session.execute(event_stmt.order_by(Event.timestamp))).scalars().all()
    alarms = _unresolved_alarm_events(list(alarm_events))
    clear_stmt = scoped_select(Event, user.site_id).where(
        Event.panel_id == panel_id,
        Event.event_type == "alarm_cleared",
        Event.command.in_(["maintenance_clear", "maintenance_finding_clear"]),
    ).order_by(Event.timestamp)
    clear_events = (await session.execute(clear_stmt)).scalars().all()
    cleared_findings: dict[str, datetime] = {}
    for clear_event in clear_events:
        metric = "alarms" if clear_event.command == "maintenance_clear" else clear_event.value
        if metric:
            cleared_findings[metric] = clear_event.timestamp
    maintenance_stmt = scoped_select(MaintenanceRecord, user.site_id).where(
        MaintenanceRecord.panel_id == panel_id
    ).order_by(desc(MaintenanceRecord.service_date), desc(MaintenanceRecord.created_at)).limit(1)
    last_service = (await session.execute(maintenance_stmt)).scalars().first()
    live = gateway.states.get(panel_id) if gateway and hasattr(gateway, "states") else None
    report = analyze_generator(
        panel, list(samples), list(alarms), live, last_service, cleared_findings
    )
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


@router.post("/preventive-maintenance/{panel_id}/alarms/clear")
async def clear_maintenance_alarms(
    panel_id: str,
    body: MaintenanceAlarmClearRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
) -> dict[str, int | str]:
    """Close resolved alarms in maintenance analysis while preserving the audit trail."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Generator not found")

    state = gateway.states.get(panel_id) if gateway and hasattr(gateway, "states") else None
    active_controller_alarms = list(getattr(state, "active_alarms", []) or [])
    if active_controller_alarms:
        raise HTTPException(
            status_code=409,
            detail="The controller still reports active alarms. Resolve or reset them at the controller before clearing the maintenance finding.",
        )

    alarm_stmt = scoped_select(Event, user.site_id).where(
        Event.panel_id == panel_id,
        Event.event_type.in_(["alarm_active", "alarm_cleared"]),
    ).order_by(Event.timestamp)
    alarm_events = (await session.execute(alarm_stmt)).scalars().all()
    unresolved = _unresolved_alarm_events(list(alarm_events))
    if not unresolved:
        return {"status": "no_active_alarms", "cleared_count": 0}

    session.add(Event(
        site_id=user.site_id,
        panel_id=panel_id,
        event_type="alarm_cleared",
        command="maintenance_clear",
        value="all",
        triggered_by="manual",
        reason=body.resolution_note.strip(),
        previous_state="alarm_active",
        new_state="engineer_checked",
        command_result="success",
        user_id=user.id,
    ))
    await session.commit()
    return {"status": "cleared", "cleared_count": len(unresolved)}


@router.post("/preventive-maintenance/{panel_id}/findings/{metric}/clear")
async def clear_maintenance_finding(
    panel_id: str,
    metric: str,
    body: MaintenanceAlarmClearRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
    period: Literal["all", "30d", "7d", "today"] = Query("30d"),
) -> dict[str, str]:
    """Resolve one engineer-checked maintenance finding and retain an audit event."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Generator not found")

    report = await _build_maintenance_report(panel_id, period, user, session, gateway)
    finding = next((item for item in report.findings if item.metric == metric), None)
    if finding is None:
        return {"status": "already_clear", "metric": metric}

    if metric == "alarms":
        state = gateway.states.get(panel_id) if gateway and hasattr(gateway, "states") else None
        if list(getattr(state, "active_alarms", []) or []):
            raise HTTPException(
                status_code=409,
                detail="The controller still reports active alarms. Resolve or reset them at the controller before clearing the maintenance finding.",
            )

    session.add(Event(
        site_id=user.site_id,
        panel_id=panel_id,
        event_type="alarm_cleared",
        command="maintenance_finding_clear",
        value=metric,
        triggered_by="manual",
        reason=body.resolution_note.strip(),
        previous_state=finding.severity,
        new_state="engineer_checked",
        command_result="success",
        user_id=user.id,
    ))
    await session.commit()
    return {"status": "cleared", "metric": metric}


@router.get("/preventive-maintenance/{panel_id}/records/export")
async def export_maintenance_records_csv(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    locale: Literal["en", "ar"] = Query("en"),
) -> Response:
    """Export completed service history for one generator as localized CSV."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Generator not found")
    stmt = scoped_select(MaintenanceRecord, user.site_id).where(
        MaintenanceRecord.panel_id == panel_id
    ).order_by(desc(MaintenanceRecord.service_date), desc(MaintenanceRecord.created_at))
    records = (await session.execute(stmt)).scalars().all()

    output = io.StringIO(newline="")
    writer = csv.writer(output)
    if locale == "ar":
        writer.writerow(["سجل الصيانة المكتملة"])
        writer.writerow(["المولد", panel.name])
        writer.writerow(["وقت التصدير (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["عدد السجلات", len(records)])
        writer.writerow([])
        writer.writerow([
            "تاريخ الصيانة", "ساعات التشغيل", "نوع الصيانة", "نفذت بواسطة",
            "الملاحظات", "وقت التسجيل (UTC)", "معرّف السجل", "معرّف المستخدم المسجل",
        ])
    else:
        writer.writerow(["COMPLETED SERVICE HISTORY"])
        writer.writerow(["Generator", panel.name])
        writer.writerow(["Exported At (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Record Count", len(records)])
        writer.writerow([])
        writer.writerow([
            "Service Date", "Running Hours", "Service Type", "Performed By",
            "Notes", "Recorded At (UTC)", "Record ID", "Recorded By User ID",
        ])
    for record in records:
        writer.writerow([
            record.service_date.isoformat(), record.run_hours,
            _localize_service_type(record.service_type, locale), record.performed_by or "",
            record.notes or "", record.created_at.strftime("%Y-%m-%d %H:%M:%S"),
            record.id, record.recorded_by or "",
        ])

    filename = f"completed_services_{locale}_{panel_id[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return _csv_response(output, filename)


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
    locale: Literal["en", "ar"] = Query("en"),
):
    """Export a complete, per-generator preventive-maintenance CSV."""
    report = await _build_maintenance_report(panel_id, period, user, session, gateway)
    output = io.StringIO()
    writer = csv.writer(output)
    if locale == "ar":
        writer.writerow(["تقرير الصيانة الوقائية"])
        writer.writerow(["المولد", report.generator_name])
        writer.writerow(["ملف وحدة التحكم", report.controller_profile])
        writer.writerow(["الفترة", _localize_period(report.period, locale)])
        writer.writerow(["وقت الإنشاء (UTC)", report.generated_at.strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["الحالة", _localize_maintenance_text(report.condition, locale)])
        writer.writerow(["مؤشر الحالة", f"{report.condition_score}/100"])
        writer.writerow(["عدد القراءات التاريخية", report.sample_count])
    else:
        writer.writerow(["PREVENTIVE MAINTENANCE REPORT"])
        writer.writerow(["Generator", report.generator_name])
        writer.writerow(["Controller Profile", report.controller_profile])
        writer.writerow(["Period", _localize_period(report.period, locale)])
        writer.writerow(["Generated At (UTC)", report.generated_at.strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Condition", report.condition])
        writer.writerow(["Condition Score", f"{report.condition_score}/100"])
        writer.writerow(["History Samples", report.sample_count])
    writer.writerow([])
    writer.writerow(["تخطيط الصيانة" if locale == "ar" else "SERVICE PLANNING"])
    for key, value in report.service.items():
        writer.writerow([ARABIC_SERVICE_KEYS.get(key, key.replace("_", " ")) if locale == "ar" else key.replace("_", " ").title(), value])
    writer.writerow([])
    writer.writerow(["قراءات وحدة التحكم الحالية" if locale == "ar" else "CURRENT CONTROLLER READINGS"])
    writer.writerow(["المعامل", "القيمة", "الوحدة"] if locale == "ar" else ["Parameter", "Value", "Unit"])
    for key, value in sorted(report.current_readings.items()):
        writer.writerow([_localize_metric(key, locale), _localize_code(str(value), locale), report.reading_units.get(key, "")])
    writer.writerow([])
    writer.writerow(["اتجاهات الفترة" if locale == "ar" else "PERIOD TRENDS"])
    writer.writerow(["المعامل", "الحد الأدنى", "المتوسط", "الحد الأقصى"] if locale == "ar" else ["Parameter", "Minimum", "Average", "Maximum"])
    for key, values in sorted(report.trends.items()):
        writer.writerow([_localize_metric(key, locale), values["minimum"], values["average"], values["maximum"]])
    writer.writerow([])
    writer.writerow(["النتائج والتوصيات" if locale == "ar" else "FINDINGS AND RECOMMENDATIONS"])
    writer.writerow(["الخطورة", "النتيجة", "الدليل", "الإجراء الموصى به"] if locale == "ar" else ["Severity", "Finding", "Evidence", "Recommended Action"])
    if report.findings:
        for finding in report.findings:
            writer.writerow([
                _localize_code(finding.severity, locale).upper(),
                _localize_maintenance_text(finding.title, locale),
                _localize_maintenance_text(finding.detail, locale),
                _localize_maintenance_text(finding.recommendation, locale),
            ])
    else:
        empty_finding = ["INFORMATION", "No condition warning detected", "No configured limit was exceeded in available data.", "Continue routine inspection and servicing."]
        writer.writerow([_localize_maintenance_text(value, locale) if index else _localize_code(value, locale) for index, value in enumerate(empty_finding)])
    writer.writerow([])
    writer.writerow(["القيود" if locale == "ar" else "LIMITATIONS"])
    for note in report.limitations:
        writer.writerow([_localize_maintenance_text(note, locale)])
    filename = f"preventive_maintenance_{locale}_{panel_id[:8]}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return _csv_response(output, filename)


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
    locale: Literal["en", "ar"] = Query("en"),
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
    if locale == "ar":
        writer.writerow(["تقرير عمل أسطول المولدات"])
        writer.writerow(["الموقع", site.name])
        writer.writerow(["فترة التقرير", _localize_period(period, locale)])
        writer.writerow(["وقت الإنشاء (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["طلب بواسطة", user.full_name or user.email])
    else:
        writer.writerow(["GENERATOR FLEET WORK REPORT"])
        writer.writerow(["Facility Site", site.name])
        writer.writerow(["Reporting Period", _localize_period(period, locale)])
        writer.writerow(["Generated At (UTC)", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")])
        writer.writerow(["Requested By", user.full_name or user.email])
    writer.writerow([])

    # ── Section 2: Fleet Work Summary ────────────────────────────────────
    writer.writerow(["ملخص أداء وعمل المولدات" if locale == "ar" else "GENERATOR PERFORMANCE & WORK SUMMARY"])
    writer.writerow(
        ["اسم المولد", "الاتصال / العنوان", "معرّف الوحدة", "القدرة الاسمية (kW)", "ساعات التشغيل المتراكمة", "إجمالي الطاقة (kWh)", "دورات التشغيل", "الحالة", "إنذارات الفترة"]
        if locale == "ar" else
        ["Generator Name", "Transport / Address", "Unit ID", "Rated kW", "Accumulated Run Hours", "Total Energy (kWh)", "Start Cycles", "Status", "Alarms in Period"]
    )

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
            _localize_code(status_word, locale),
            alarm_count,
        ])

    writer.writerow([])

    # ── Section 3: Operational Activity Log ──────────────────────────────
    writer.writerow(["سجل نشاط العمل والمناوبة التشغيلية" if locale == "ar" else "OPERATIONAL WORK & DUTY ACTIVITY LOG"])
    writer.writerow(
        ["الوقت (UTC)", "المولد", "نوع الحدث", "الأمر", "القيمة / الحالة", "تم بواسطة", "السبب / الملاحظة"]
        if locale == "ar" else
        ["Timestamp (UTC)", "Generator", "Event Type", "Command", "Value / State", "Triggered By", "Reason / Note"]
    )

    panel_name_map = {p.id: p.name for p in panels}
    for e in events:
        writer.writerow([
            e.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
            panel_name_map.get(e.panel_id, "مستوى الموقع" if locale == "ar" else "Site Level") if e.panel_id else ("مستوى الموقع" if locale == "ar" else "Site Level"),
            _localize_code(e.event_type, locale),
            _localize_code(e.command, locale) or "—",
            _localize_code(e.value, locale) or "—",
            _localize_code(e.triggered_by, locale),
            e.reason or "—",
        ])

    site_slug = site.name.lower().replace(" ", "_")[:20]
    filename = f"generator_work_report_{locale}_{site_slug}_{period}_{datetime.now(timezone.utc).strftime('%Y%m%d')}.csv"
    return _csv_response(output, filename)
