"""Quality-aware fuel and generator efficiency reports."""

from datetime import date, datetime, timedelta, timezone
from typing import Annotated, Literal
import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_get, scoped_select
from app.dependencies import get_current_user
from app.models.fuel_movement import FuelMovement
from app.models.panel import Panel
from app.models.site import Site
from app.models.telemetry_sample import TelemetrySample
from app.services.performance import ISSUES, daily_summaries, generator_report, report_window, summarize

router = APIRouter(prefix="/reports", tags=["Reports"])
Period = Literal["today", "7d", "30d", "all", "custom"]


class MovementInput(BaseModel):
    occurred_at: datetime
    litres: float = Field(gt=-10000000, lt=10000000)
    notes: str | None = Field(None, max_length=1000)


async def _report(kind: str, period: Period, panel_id: str | None, start_date: date | None,
                  end_date: date | None, user: User, session: AsyncSession):
    site = await scoped_get(session, Site, user.site_id, user.site_id)
    # Site itself is not tenant-scoped, so also verify its organization.
    if site is None or site.organization_id != user.organization_id:
        raise HTTPException(404, "Site not found")
    try:
        start, end = report_window(period, site.timezone, start_date, end_date)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    panels_stmt = scoped_select(Panel, user.site_id).order_by(Panel.name, Panel.id)
    if panel_id:
        panels_stmt = panels_stmt.where(Panel.id == panel_id)
    panels = (await session.execute(panels_stmt)).scalars().all()
    if panel_id and not panels:
        raise HTTPException(404, "Generator not found")
    generators, combined, all_issues = [], [], set()
    for panel in panels:
        query = scoped_select(TelemetrySample, user.site_id).where(TelemetrySample.panel_id == panel.id)
        if start:
            # Include exactly one sample preceding the window to bound the first
            # interval. Without it we silently lose measured boundary fuel.
            prior = (await session.execute(query.where(TelemetrySample.recorded_at < start)
                     .order_by(desc(TelemetrySample.recorded_at)).limit(1))).scalars().first()
            query = query.where(TelemetrySample.recorded_at >= start)
        else:
            prior = None
        samples = (await session.execute(query.where(TelemetrySample.recorded_at <= end)
                   .order_by(TelemetrySample.recorded_at))).scalars().all()
        if prior:
            samples.insert(0, prior)
        movements = (await session.execute(scoped_select(FuelMovement, user.site_id).where(
            FuelMovement.panel_id == panel.id, FuelMovement.occurred_at <= end,
            FuelMovement.occurred_at >= ((prior.recorded_at if prior else start) or datetime.min.replace(tzinfo=timezone.utc)),
        ))).scalars().all()
        earliest = start or (samples[0].recorded_at if samples else end)
        generated, intervals = generator_report(panel, samples, earliest, end, site.timezone, movements)
        generators.append(generated)
        combined.extend(intervals)
        all_issues.update(generated["issues"])
    effective_start = start or min((i["start"] for i in combined), default=end)
    seconds = max(0, (end - effective_start).total_seconds())
    fleet = summarize(combined, seconds * len(panels), all_issues)
    fleet.update({"panel_id": None, "name": site.name,
                  "daily": daily_summaries(combined, effective_start, end, site.timezone, max(1, len(panels)))})
    return {"report_type": kind, "period": period, "timezone": site.timezone,
            "start_at": effective_start.isoformat(), "end_at": end.isoformat(),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "fleet": fleet, "generators": generators,
            "issue_labels": {key: ISSUES[key][0] for key in sorted(all_issues) if key in ISSUES}}


def _localized_csv(report: dict, kind: str, locale: str):
    arabic = locale == "ar"
    labels = (
        ["المولد", "الوقود (لتر)", "الطاقة (ك.و.س)", "الوقود المطابق (لتر)", "ساعات التشغيل", "لتر/ساعة",
         "ك.و.س/لتر", "لتر/ك.و.س", "متوسط القدرة (ك.و)", "كفاءة التحويل (%)", "تغطية الوقود (%)", "تغطية القياسات المطابقة (%)", "تقديري", "المصدر", "ملاحظات الجودة"]
        if arabic else
        ["Generator", "Fuel consumed (L)", "Energy (kWh)", "Matched fuel (L)", "Run hours", "L/hour",
         "kWh/L", "L/kWh", "Average output (kW)", "Conversion efficiency (%)", "Fuel coverage (%)", "Matched coverage (%)", "Estimated", "Source", "Quality notes"]
    )
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(["نوع التقرير" if arabic else "Report", "استهلاك الوقود" if arabic and kind == "fuel" else "كفاءة المولد" if arabic else kind])
    writer.writerow(["الفترة" if arabic else "Period", report["period"]])
    writer.writerow(["المنطقة الزمنية" if arabic else "Timezone", report["timezone"]])
    writer.writerow(["من" if arabic else "From", report["start_at"]])
    writer.writerow(["إلى" if arabic else "To", report["end_at"]])
    writer.writerow([])
    writer.writerow(labels)
    for row in [report["fleet"], *report["generators"]]:
        source = row["source"]
        if arabic:
            source = ", ".join({"counter": "عداد تراكمي", "flow": "تدفق الوقود", "tank": "خزان معاير", "unavailable": "غير متاح"}.get(item, item) for item in source.split(","))
        writer.writerow([row["name"], row["fuel_litres"], row["energy_kwh"], row["matched_fuel_litres"],
                         row["run_hours"], row["litres_per_hour"], row["kwh_per_litre"], row["litres_per_kwh"],
                         row["average_output_kw"], row["efficiency_percent"], row["coverage_percent"],
                         row["matched_coverage_percent"], ("نعم" if row["estimated"] else "لا") if arabic else row["estimated"],
                         source, "; ".join(ISSUES[issue][1 if arabic else 0] for issue in row["issues"] if issue in ISSUES)])
    writer.writerow([])
    writer.writerow(["التاريخ" if arabic else "Date", "الوقود (لتر)" if arabic else "Fuel (L)",
                     "الطاقة (ك.و.س)" if arabic else "Energy (kWh)", "لتر/ك.و.س" if arabic else "L/kWh",
                     "تغطية القياسات (%)" if arabic else "Matched coverage (%)"])
    for day in report["fleet"]["daily"]:
        writer.writerow([day["date"], day["fuel_litres"], day["energy_kwh"], day["litres_per_kwh"], day["matched_coverage_percent"]])
    return Response(content="\ufeff" + out.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": f'attachment; filename="{kind}_{locale}_{period_name(report)}.csv"'})


def period_name(report):
    return report["generated_at"][:10]


@router.get("/fuel")
async def fuel_report(user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)],
                      period: Period = "30d", panel_id: str | None = None, start_date: date | None = None, end_date: date | None = None):
    return await _report("fuel", period, panel_id, start_date, end_date, user, session)


@router.get("/efficiency")
async def efficiency_report(user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)],
                            period: Period = "30d", panel_id: str | None = None, start_date: date | None = None, end_date: date | None = None):
    return await _report("efficiency", period, panel_id, start_date, end_date, user, session)


@router.get("/fuel/export")
async def fuel_export(user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)],
                      period: Period = "30d", panel_id: str | None = None, start_date: date | None = None, end_date: date | None = None,
                      locale: Literal["en", "ar"] = "en"):
    return _localized_csv(await _report("fuel", period, panel_id, start_date, end_date, user, session), "fuel", locale)


@router.get("/efficiency/export")
async def efficiency_export(user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)],
                            period: Period = "30d", panel_id: str | None = None, start_date: date | None = None, end_date: date | None = None,
                            locale: Literal["en", "ar"] = "en"):
    return _localized_csv(await _report("efficiency", period, panel_id, start_date, end_date, user, session), "efficiency", locale)


@router.get("/fuel/movements/{panel_id}")
async def list_fuel_movements(panel_id: str, user: Annotated[User, Depends(get_current_user)], session: Annotated[AsyncSession, Depends(get_session)]):
    if not await scoped_get(session, Panel, panel_id, user.site_id):
        raise HTTPException(404, "Generator not found")
    items = (await session.execute(scoped_select(FuelMovement, user.site_id).where(FuelMovement.panel_id == panel_id)
             .order_by(desc(FuelMovement.occurred_at)))).scalars().all()
    return [{"id": m.id, "occurred_at": m.occurred_at, "litres": m.litres, "notes": m.notes} for m in items]


@router.post("/fuel/movements/{panel_id}", status_code=201)
async def record_fuel_movement(panel_id: str, body: MovementInput, user: Annotated[User, Depends(get_current_user)],
                               session: Annotated[AsyncSession, Depends(get_session)]):
    if not await scoped_get(session, Panel, panel_id, user.site_id):
        raise HTTPException(404, "Generator not found")
    if body.litres == 0:
        raise HTTPException(422, "Fuel movement must not be zero")
    occurred_at = body.occurred_at.replace(tzinfo=timezone.utc) if body.occurred_at.tzinfo is None else body.occurred_at
    if occurred_at > datetime.now(timezone.utc) + timedelta(minutes=5):
        raise HTTPException(422, "Fuel movement cannot be in the future")
    movement = FuelMovement(site_id=user.site_id, panel_id=panel_id, occurred_at=occurred_at,
                            litres=body.litres, notes=body.notes, recorded_by=user.id)
    session.add(movement)
    await session.commit()
    await session.refresh(movement)
    return {"id": movement.id, "occurred_at": movement.occurred_at, "litres": movement.litres, "notes": movement.notes}
