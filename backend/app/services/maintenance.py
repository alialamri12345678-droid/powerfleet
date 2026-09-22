"""Manufacturer-based service deadlines and persistent, verifiable early warnings."""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from statistics import mean
from zoneinfo import ZoneInfo

from sqlalchemy import desc
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.tenant import scoped_select
from app.models.maintenance_task import MaintenanceFindingRecord, MaintenanceTask
from app.models.maintenance_record import MaintenanceRecord
from app.models.event import Event
from app.models.site import Site
from app.models.panel import Panel
from app.models.telemetry_sample import TelemetrySample
from app.services.measurement_quality import metric_value, utc
from app.services.performance import build_intervals


# These are changes in comparable, valid operating readings, not a claim that
# any one engine's absolute manufacturer limit is universal.
CHANGE_RULES = {
    "coolant_temperature": (8.0, "up", "Coolant temperature rising at similar load", "Inspect coolant, radiator airflow, thermostat and fan."),
    "oil_pressure": (0.5, "down", "Oil pressure falling at similar load", "Check oil level and grade, filters, leaks and calibrated pressure."),
    "oil_temperature": (10.0, "up", "Oil temperature rising at similar load", "Inspect lubrication and cooling under load."),
    "battery_voltage": (1.0, "down", "Starter battery voltage declining", "Check charging, terminals, battery health and starting performance."),
}


def _measurements(samples, metric, loaded=True):
    rows = []
    for sample in samples:
        if not sample.is_reachable or (loaded and sample.engine_status != "running"):
            continue
        value = metric_value(sample, metric)
        load = metric_value(sample, "load_kw_percent") if loaded else None
        speed = metric_value(sample, "engine_speed") if loaded else None
        if value is None or (loaded and (load is None or speed is None or speed <= 0)):
            continue
        if loaded and (load < 10 or load > 105):
            continue
        rows.append((sample, value, load, speed))
    return rows


def _detect_changes(panel, samples):
    findings = []
    for metric, (amount, direction, title, recommendation) in CHANGE_RULES.items():
        rows = _measurements(samples, metric, loaded=metric != "battery_voltage")
        if len(rows) < 8:
            continue
        # Compare three earlier and three recent readings at similar load and
        # speed. A short-lived excursion cannot become a persistent finding.
        recent = rows[-3:]
        older = [r for r in rows[:-3]
                 if metric == "battery_voltage" or
                 (abs(r[2] - mean(v[2] for v in recent)) <= 10 and
                  abs(r[3] - mean(v[3] for v in recent)) <= 100)]
        if len(older) < 3:
            continue
        baseline = mean(r[1] for r in older[:3])
        current = mean(r[1] for r in recent)
        delta = current - baseline
        if (direction == "up" and delta < amount) or (direction == "down" and delta > -amount):
            continue
        if direction == "up" and not all(r[1] >= baseline + amount for r in recent):
            continue
        if direction == "down" and not all(r[1] <= baseline - amount for r in recent):
            continue
        if (utc(recent[-1][0].recorded_at) - utc(recent[0][0].recorded_at)).total_seconds() < 120:
            continue
        findings.append({"metric": metric, "severity": "warning", "title": title,
                         "detail": f"Comparable readings changed from {baseline:.1f} to {current:.1f} ({delta:+.1f}).",
                         "recommendation": recommendation, "verification_kind": "sensor",
                         "evidence": {"baseline": round(baseline, 3), "trigger": round(current, 3),
                                      "direction": direction, "threshold": amount,
                                      "load_percent": round(mean(v[2] for v in recent), 2) if metric != "battery_voltage" else None,
                                      "recorded_at": utc(recent[-1][0].recorded_at).isoformat()}})
    # A fuel deterioration comparison requires enough measured consumption in
    # each group and the same operating load band; never infer from tank level.
    if (panel.analytics_config or {}).get("fuel_source", "counter") == "counter":
        intervals, _ = build_intervals(panel, samples)
        valid = [i for i in intervals if i["fuel"] is not None and i["energy"] is not None
                 and i["fuel"] > 0 and i["energy"] > 0 and not i["estimated"]
                 and i["load_band"] not in ("unknown", "transition", "unloaded")]
        if len(valid) >= 8:
            recent = valid[-3:]
            comparable = [i for i in valid[:-3] if i["load_band"] == recent[0]["load_band"]]
            if len(comparable) >= 3 and all(i["load_band"] == recent[0]["load_band"] for i in recent):
                older = comparable[:3]
                old_fuel, new_fuel = sum(i["fuel"] for i in older), sum(i["fuel"] for i in recent)
                old_energy, new_energy = sum(i["energy"] for i in older), sum(i["energy"] for i in recent)
                if old_fuel >= 5 and new_fuel >= 5 and old_energy > 0 and new_energy > 0:
                    baseline, current = old_fuel / old_energy, new_fuel / new_energy
                    if current >= baseline * 1.15:
                        findings.append({"metric": "fuel_efficiency", "severity": "warning",
                                         "title": "Fuel use rising for comparable output",
                                         "detail": f"Specific consumption rose from {baseline:.3f} to {current:.3f} L/kWh at {recent[0]['load_band']} load.",
                                         "recommendation": "Inspect fuel delivery, filters, load balance and engine condition.",
                                         "verification_kind": "sensor",
                                         "evidence": {"baseline": baseline, "trigger": current,
                                                      "direction": "up", "threshold": baseline * 0.15,
                                                      "load_band": recent[0]["load_band"],
                                                      "recorded_at": recent[-1]["end"].isoformat()}})
    return findings


def _verified(finding, samples, panel=None):
    if finding.work_recorded_at is None:
        return False
    evidence = finding.evidence or {}
    metric = finding.metric
    if metric == "alarms":
        return False  # Controller alarms require an explicit inspection/clearance.
    if metric == "fuel_efficiency":
        if panel is None:
            return False
        intervals, _ = build_intervals(panel, samples)
        after = [i for i in intervals if i["start"] > utc(finding.work_recorded_at)
                 and i["fuel"] is not None and i["energy"] is not None and
                 i["load_band"] == evidence.get("load_band") and not i["estimated"]]
        after = after[-3:]
        if len(after) < 3 or sum(i["fuel"] for i in after) < 5 or sum(i["energy"] for i in after) <= 0:
            return False
        ratio = sum(i["fuel"] for i in after) / sum(i["energy"] for i in after)
        return ratio <= float(evidence.get("baseline", 0)) * 1.075
    rows = [r for r in _measurements(samples, metric, loaded=metric != "battery_voltage")
            if utc(r[0].recorded_at) > utc(finding.work_recorded_at)]
    if len(rows) < 3 or (utc(rows[-1][0].recorded_at) - utc(rows[0][0].recorded_at)).total_seconds() < 120:
        return False
    rows = rows[-3:]
    load = evidence.get("load_percent")
    if load is not None and any(abs(row[2] - load) > 10 for row in rows):
        return False
    baseline = evidence.get("baseline")
    trigger = evidence.get("trigger")
    if baseline is None or trigger is None:
        return False
    current = mean(row[1] for row in rows)
    return abs(current - baseline) <= max(float(evidence.get("threshold", 0)) / 2, abs(trigger - baseline) / 3)


async def evaluate_site_maintenance(session: AsyncSession, site_id: str, gateway=None):
    panels = (await session.execute(scoped_select(Panel, site_id))).scalars().all()
    for panel in panels:
        start = datetime.now(timezone.utc) - timedelta(days=30)
        samples = (await session.execute(scoped_select(TelemetrySample, site_id).where(
            TelemetrySample.panel_id == panel.id, TelemetrySample.recorded_at >= start,
        ).order_by(TelemetrySample.recorded_at))).scalars().all()
        existing = (await session.execute(scoped_select(MaintenanceFindingRecord, site_id).where(
            MaintenanceFindingRecord.panel_id == panel.id,
        ).order_by(desc(MaintenanceFindingRecord.first_detected_at)))).scalars().all()
        by_metric = {}
        for finding in existing:
            by_metric.setdefault(finding.metric, finding)
        candidates = _detect_changes(panel, samples)
        now = datetime.now(timezone.utc)
        state = gateway.states.get(panel.id) if gateway and hasattr(gateway, "states") else None
        active_alarms = (list(getattr(state, "active_alarms", []) or [])
                         if state and state.is_reachable and state.is_data_fresh else [])
        latest = samples[-1] if samples else None
        if active_alarms or (latest and utc(latest.recorded_at) >= now - timedelta(minutes=5) and latest.active_alarm_count):
            candidates.append({"metric": "alarms", "severity": "critical",
                               "title": "Controller alarms require inspection",
                               "detail": ", ".join(active_alarms) if active_alarms else "Controller reported active alarms.",
                               "recommendation": "Resolve or reset the controller alarm and confirm the cause with an engineer.",
                               "verification_kind": "inspection",
                               "evidence": {"recorded_at": now.isoformat(), "alarms": active_alarms}})
        for candidate in candidates:
            found = by_metric.get(candidate["metric"])
            if found and found.status != "resolved":
                found.last_detected_at = now
                found.detail = candidate["detail"]
            elif not found or (found.resolved_at and
                               utc(datetime.fromisoformat(candidate["evidence"]["recorded_at"])) > utc(found.resolved_at)):
                session.add(MaintenanceFindingRecord(
                    site_id=site_id, panel_id=panel.id, first_detected_at=now, last_detected_at=now,
                    **candidate,
                ))
        for found in existing:
            if found.status == "awaiting_verification" and _verified(found, samples, panel):
                found.status = "resolved"
                found.resolved_at = now
    await session.flush()


def task_deadline(task, records, current_hours, today, daily_usage=None):
    latest = next((r for r in records if task.id in (r.task_ids or [])), None)
    base_date = latest.service_date if latest else task.baseline_date
    base_hours = latest.run_hours if latest else task.baseline_run_hours
    next_date = base_date + timedelta(days=task.interval_days) if base_date and task.interval_days else None
    next_hours = base_hours + task.interval_hours if base_hours is not None and task.interval_hours else None
    days_left = (next_date - today).days if next_date else None
    hours_left = next_hours - current_hours if next_hours is not None and current_hours is not None else None
    if (task.interval_days and not base_date) or (task.interval_hours and base_hours is None):
        status = "configuration_required"
    elif (days_left is not None and days_left < 0) or (hours_left is not None and hours_left < 0):
        status = "overdue"
    elif (days_left is not None and days_left <= 14) or (hours_left is not None and hours_left <= 25):
        status = "due_soon"
    elif task.interval_hours and hours_left is None:
        status = "insufficient_data"
    else:
        status = "scheduled"
    estimate = None
    if hours_left is not None and daily_usage and daily_usage > 0:
        estimate = (today + timedelta(days=max(0, hours_left) / daily_usage)).isoformat()
    return {"id": task.id, "component": task.component, "name": task.name, "active": task.active,
            "interval_hours": task.interval_hours, "interval_days": task.interval_days,
            "baseline_date": task.baseline_date.isoformat() if task.baseline_date else None,
            "baseline_run_hours": task.baseline_run_hours, "manufacturer_reference": task.manufacturer_reference,
            "last_completed_at": latest.service_date.isoformat() if latest else None,
            "next_due_date": next_date.isoformat() if next_date else None,
            "next_due_run_hours": next_hours, "remaining_days": days_left,
            "remaining_hours": round(hours_left, 1) if hours_left is not None else None,
            "estimated_due_date": estimate, "status": status}


async def site_task_status(session: AsyncSession, site_id: str):
    site = await session.get(Site, site_id)
    if site is None:
        return []
    today = datetime.now(timezone.utc).astimezone(ZoneInfo(site.timezone)).date()
    tasks = (await session.execute(scoped_select(MaintenanceTask, site_id).where(
        MaintenanceTask.active.is_(True),
    ))).scalars().all()
    records = (await session.execute(scoped_select(MaintenanceRecord, site_id).order_by(
        desc(MaintenanceRecord.service_date), desc(MaintenanceRecord.created_at)
    ))).scalars().all()
    records_by_panel = {}
    for record in records:
        records_by_panel.setdefault(record.panel_id, []).append(record)
    hours_by_panel = {}
    result = []
    for task in tasks:
        if task.panel_id not in hours_by_panel:
            sample = (await session.execute(scoped_select(TelemetrySample, site_id).where(
                TelemetrySample.panel_id == task.panel_id,
            ).order_by(desc(TelemetrySample.recorded_at)).limit(1))).scalars().first()
            hours_by_panel[task.panel_id] = (metric_value(sample, "run_hours") if sample and
                utc(sample.recorded_at) >= datetime.now(timezone.utc) - timedelta(minutes=10) else None)
        result.append({"panel_id": task.panel_id, **task_deadline(
            task, records_by_panel.get(task.panel_id, []), hours_by_panel[task.panel_id], today)})
    return result


async def emit_due_events(session: AsyncSession, site_id: str):
    for task in await site_task_status(session, site_id):
        status = task["status"]
        if status not in {"due_soon", "overdue"}:
            continue
        last = (await session.execute(scoped_select(Event, site_id).where(
            Event.panel_id == task["panel_id"], Event.command == "maintenance_due",
            Event.value == task["id"],
        ).order_by(desc(Event.timestamp)).limit(1))).scalars().first()
        task_model = await session.get(MaintenanceTask, task["id"])
        completions = (await session.execute(scoped_select(MaintenanceRecord, site_id).where(
            MaintenanceRecord.panel_id == task["panel_id"],
        ).order_by(desc(MaintenanceRecord.created_at)))).scalars().all()
        latest_completion = next((row for row in completions if task["id"] in (row.task_ids or [])), None)
        reset_at = max((utc(value) for value in (
            task_model.updated_at if task_model else None,
            latest_completion.created_at if latest_completion else None,
        ) if value), default=None)
        if last and last.new_state == status and (reset_at is None or utc(last.timestamp) >= reset_at):
            continue
        session.add(Event(site_id=site_id, panel_id=task["panel_id"],
                          event_type="system", command="maintenance_due", value=task["id"],
                          triggered_by="system", reason=f"{task['name']}: {status}",
                          previous_state=last.new_state if last else "scheduled",
                          new_state=status, command_result="success"))
