"""Fuel and electrical performance from matched, quality-checked intervals.

Never subtract global extrema: controller replacement/reset, missing readings,
and collection gaps are explicit breaks in coverage. Ratios use only their
common measured intervals, including fuel burned with zero electrical output.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta, timezone
from math import isfinite
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.services.measurement_quality import metric_value, source_uncertain, utc

ISSUES = {
    "insufficient_data": ("Not enough valid readings", "لا توجد قراءات صالحة كافية"),
    "historical_quality_unknown": ("Historical readings have no acquisition quality record", "القراءات التاريخية لا تتضمن سجل جودة القياس"),
    "collection_gap": ("Collection gaps excluded from totals", "تم استبعاد فترات انقطاع جمع البيانات"),
    "source_changed": ("Controller or measurement configuration changed", "تغيرت وحدة التحكم أو إعدادات القياس"),
    "counter_reset": ("Counter reset or unconfirmed rollover excluded", "تم استبعاد تصفير العداد أو التفافه غير المؤكد"),
    "fuel_unavailable": ("Fuel measurement unavailable or stale", "قياس الوقود غير متاح أو قديم"),
    "energy_unavailable": ("Energy measurement unavailable or stale", "قياس الطاقة غير متاح أو قديم"),
    "hours_unavailable": ("Running-hour measurement unavailable", "قياس ساعات التشغيل غير متاح"),
    "estimated_fuel": ("Fuel is estimated from flow or calibrated tank levels", "الوقود مقدر من التدفق أو مستويات الخزان المعايرة"),
    "integrated_power": ("Energy estimated by integrating sampled output power", "الطاقة مقدرة بتكامل القدرة المسجلة"),
    "boundary_estimate": ("Boundary intervals apportioned by time", "تم توزيع الفترات عند حدود التقرير حسب الزمن"),
    "fuel_resolution": ("Fuel change too small for a reliable consumption ratio", "تغير الوقود صغير جدًا لحساب معدل استهلاك موثوق"),
    "zero_output": ("No electrical output in matched intervals", "لا يوجد إنتاج كهربائي في الفترات المتطابقة"),
    "lhv_missing": ("Configure fuel heating value to calculate percentage efficiency", "حدد القيمة الحرارية للوقود لحساب نسبة الكفاءة"),
    "unrecorded_tank_movement": ("Tank level increased without a matching refill record", "ارتفع مستوى الخزان دون سجل تعبئة مطابق"),
    "invalid_tank_calibration": ("A calibrated tank curve is required", "يلزم منحنى معايرة للخزان"),
    "meter_timing": ("Meter acquisition times differ by more than 30 seconds", "تختلف أوقات التقاط العدادات بأكثر من ٣٠ ثانية"),
}


def site_timezone(name: str):
    try:
        return ZoneInfo(name)
    except ZoneInfoNotFoundError:
        return timezone.utc


def report_window(period, tz_name, start_date=None, end_date=None, now=None):
    now = utc(now or datetime.now(timezone.utc))
    tz = site_timezone(tz_name)
    if period == "custom":
        if start_date is None or end_date is None or start_date > end_date:
            raise ValueError("Custom period requires ordered start_date and end_date")
        start = datetime.combine(start_date, time.min, tzinfo=tz).astimezone(timezone.utc)
        end = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc)
        if start >= now:
            raise ValueError("Reporting period must begin before the current time")
        return start, min(end, now)
    if period == "today":
        return now.astimezone(tz).replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc), now
    return (now - timedelta(days={"7d": 7, "30d": 30}[period]) if period != "all" else None), now


def _delta(a, b, key):
    left, right = metric_value(a, key), metric_value(b, key)
    if left is None or right is None or left < 0 or right < 0:
        return None, None
    if right < left:
        return None, "counter_reset"
    return right - left, None


def _tank_volume(percent, config):
    curve = sorted(config.get("tank_curve") or [], key=lambda p: p["percent"])
    if percent is None or len(curve) < 2 or percent < curve[0]["percent"] or percent > curve[-1]["percent"]:
        return None
    for a, b in zip(curve, curve[1:]):
        if a["percent"] <= percent <= b["percent"]:
            return a["litres"] + (b["litres"] - a["litres"]) * (percent - a["percent"]) / (b["percent"] - a["percent"])
    return None


def build_intervals(panel, samples, movements=()):
    config = getattr(panel, "analytics_config", None) or {}
    source = config.get("fuel_source", "counter")
    max_gap = float(config.get("max_gap_seconds", 180))
    intervals, issues = [], Counter()
    samples = sorted(samples, key=lambda s: utc(s.recorded_at))
    for a, b in zip(samples, samples[1:]):
        start, end = utc(a.recorded_at), utc(b.recorded_at)
        seconds = (end - start).total_seconds()
        if seconds <= 0:
            continue
        if seconds > max_gap:
            issues["collection_gap"] += 1
            continue
        left_id, right_id = getattr(a, "source_identity", None), getattr(b, "source_identity", None)
        if left_id != right_id:
            issues["source_changed"] += 1
            continue
        estimated = source_uncertain(a) or source_uncertain(b)
        if estimated:
            issues["historical_quality_unknown"] += 1
        hours = seconds / 3600
        fuel, error = None, None
        if source == "counter":
            fuel, error = _delta(a, b, "fuel_used_litres")
        elif source == "flow":
            values = [metric_value(s, "fuel_flow_lph") for s in (a, b)]
            if all(v is not None and v >= 0 for v in values):
                fuel = sum(values) / 2 * hours
            estimated = True
            issues["estimated_fuel"] += 1
        elif source == "tank":
            levels = [_tank_volume(metric_value(s, "fuel_level_percent"), config) for s in (a, b)]
            if all(v is not None for v in levels):
                movement = sum(float(m.litres) for m in movements if start < utc(m.occurred_at) <= end)
                fuel = levels[0] + movement - levels[1]
                if fuel < 0:
                    fuel, error = None, "unrecorded_tank_movement"
            else:
                error = "invalid_tank_calibration"
            estimated = True
            issues["estimated_fuel"] += 1
        if error:
            issues[error] += 1
        energy, energy_error = _delta(a, b, "total_kwh")
        energy_source = "counter"
        if energy_error:
            issues[energy_error] += 1
        # Do not bridge a known counter reset using a different instrument.
        if energy is None and not energy_error:
            power = [metric_value(s, "load_kw") for s in (a, b)]
            if all(v is not None and v >= 0 for v in power):
                energy = sum(power) / 2 * hours
                estimated, energy_source = True, "integrated_power"
                issues["integrated_power"] += 1
        runtime, runtime_error = _delta(a, b, "run_hours")
        if runtime_error:
            issues[runtime_error] += 1
        # Hour-counter rounding can yield slightly more than wall-clock time.
        if runtime is not None and runtime > hours + 0.11:
            runtime = None
        for missing, issue in ((fuel, "fuel_unavailable"), (energy, "energy_unavailable"), (runtime, "hours_unavailable")):
            if missing is None:
                issues[issue] += 1
        load = [metric_value(s, "load_kw_percent") for s in (a, b)]
        def band(v):
            if v is None: return "unknown"
            if v <= 1: return "unloaded"
            if v < 25: return "1–25%"
            if v < 50: return "25–50%"
            if v < 75: return "50–75%"
            return "75–100%+"
        load_band = band(load[0]) if band(load[0]) == band(load[1]) else "transition"
        intervals.append({"start": start, "end": end, "seconds": seconds,
                          "fuel": fuel, "energy": energy, "hours": runtime,
                          "estimated": estimated, "source": source, "energy_source": energy_source,
                          "lhv": config.get("fuel_lhv_kwh_per_litre"), "load_band": load_band,
                          "minimum_fuel": max(5.0, float(config.get("fuel_counter_resolution_litres", 1)) * 5)})
    return intervals, issues


def _clip(interval, start, end):
    left, right = max(interval["start"], start), min(interval["end"], end)
    if left >= right:
        return None
    fraction = (right - left).total_seconds() / interval["seconds"]
    result = dict(interval, start=left, end=right, seconds=(right-left).total_seconds())
    for key in ("fuel", "energy", "hours"):
        result[key] = interval[key] * fraction if interval[key] is not None else None
    result["boundary_estimate"] = fraction < 0.999999
    result["estimated"] = interval["estimated"] or result["boundary_estimate"]
    return result


def summarize(intervals, period_seconds, issues=()):
    fuel_intervals = [i for i in intervals if i["fuel"] is not None]
    matched = [i for i in fuel_intervals if i["energy"] is not None]
    running = [i for i in fuel_intervals if i["hours"] is not None]
    output_hours = [i for i in matched if i["hours"] is not None]
    fuel = sum(i["fuel"] for i in fuel_intervals) if fuel_intervals else None
    energy = sum(i["energy"] for i in matched) if matched else None
    matched_fuel = sum(i["fuel"] for i in matched) if matched else None
    runtime = sum(i["hours"] for i in running) if running else None
    hour_fuel = sum(i["fuel"] for i in running) if running else None
    issue_set = set(issues)
    if not fuel_intervals: issue_set.add("insufficient_data")
    if any(i.get("boundary_estimate") for i in intervals): issue_set.add("boundary_estimate")
    minimum = max((i["minimum_fuel"] for i in intervals), default=5)
    ratio_ready = matched_fuel is not None and matched_fuel >= minimum
    if matched and not ratio_ready: issue_set.add("fuel_resolution")
    if energy == 0: issue_set.add("zero_output")
    lhv_ready = bool(matched) and all(i["lhv"] and i["lhv"] > 0 for i in matched)
    if not lhv_ready: issue_set.add("lhv_missing")
    fuel_input = sum(i["fuel"] * i["lhv"] for i in matched) if lhv_ready else None
    output_runtime = sum(i["hours"] for i in output_hours)
    def rounded(value):
        return round(value, 4) if value is not None and isfinite(value) else None
    return {
        "fuel_litres": rounded(fuel), "energy_kwh": rounded(energy),
        "matched_fuel_litres": rounded(matched_fuel), "run_hours": rounded(runtime),
        "litres_per_hour": rounded(hour_fuel / runtime) if runtime and hour_fuel >= minimum else None,
        "kwh_per_litre": rounded(energy / matched_fuel) if ratio_ready and energy is not None else None,
        "litres_per_kwh": rounded(matched_fuel / energy) if ratio_ready and energy and energy > 0 else None,
        "average_output_kw": rounded(sum(i["energy"] for i in output_hours) / output_runtime) if output_runtime else None,
        "efficiency_percent": rounded(energy / fuel_input * 100) if ratio_ready and fuel_input else None,
        "coverage_percent": rounded(min(100, sum(i["seconds"] for i in fuel_intervals) / period_seconds * 100)) if period_seconds else 0,
        "matched_coverage_percent": rounded(min(100, sum(i["seconds"] for i in matched) / period_seconds * 100)) if period_seconds else 0,
        "estimated": any(i["estimated"] for i in intervals),
        "source": ",".join(sorted({i["source"] for i in fuel_intervals})) or "unavailable",
        "energy_source": ",".join(sorted({i["energy_source"] for i in matched})) or "unavailable",
        "valid_intervals": len(fuel_intervals), "issues": sorted(issue_set),
    }


def daily_summaries(intervals, start, end, tz_name, panel_count=1):
    tz = site_timezone(tz_name)
    date = start.astimezone(tz).date()
    daily = []
    while datetime.combine(date, time.min, tzinfo=tz).astimezone(timezone.utc) < end:
        day_start = max(start, datetime.combine(date, time.min, tzinfo=tz).astimezone(timezone.utc))
        day_end = min(end, datetime.combine(date + timedelta(days=1), time.min, tzinfo=tz).astimezone(timezone.utc))
        clipped = [result for interval in intervals if (result := _clip(interval, day_start, day_end))]
        daily.append({"date": date.isoformat(), **summarize(clipped, (day_end-day_start).total_seconds() * panel_count)})
        date += timedelta(days=1)
    return daily


def generator_report(panel, samples, start, end, tz_name, movements=()):
    intervals, issues = build_intervals(panel, samples, movements)
    intervals = [result for i in intervals if (result := _clip(i, start, end))]
    seconds = (end-start).total_seconds()
    result = {"panel_id": panel.id, "name": panel.name, "rated_kw": float(panel.rated_kw),
              **summarize(intervals, seconds, issues), "daily": daily_summaries(intervals, start, end, tz_name),
              "load_bands": [{"label": label, **summarize([i for i in intervals if i["load_band"] == label], seconds)}
                             for label in ("unloaded", "1–25%", "25–50%", "50–75%", "75–100%+", "transition", "unknown")
                             if any(i["load_band"] == label for i in intervals)]}
    curve = (getattr(panel, "analytics_config", None) or {}).get("fuel_curve") or []
    result["manufacturer_curve"] = curve
    return result, intervals
