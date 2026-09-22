"""Measured fuel and output must be matched over the same valid intervals."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.performance import generator_report, report_window


def sample(at, fuel, energy, hours, *, identity="controller-v1", quality=True):
    readings = {"fuel_used_litres": fuel, "total_kwh": energy, "run_hours": hours,
                "load_kw": 60, "load_kw_percent": 60}
    return SimpleNamespace(recorded_at=at, is_reachable=True, readings=readings,
                           reading_quality={key: "good" for key in readings} if quality else {},
                           reading_timestamps={key: at.isoformat() for key in readings} if quality else {},
                           source_identity=identity)


def panel():
    return SimpleNamespace(id="p1", name="Generator", rated_kw=100,
                           analytics_config={"fuel_source": "counter", "fuel_lhv_kwh_per_litre": 10})


def test_five_hours_three_hundred_kwh_one_hundred_litres():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    samples = [sample(start + timedelta(minutes=2 * i), i * (100 / 150), i * 2, i / 30)
               for i in range(151)]
    result, _ = generator_report(panel(), samples, start, start + timedelta(hours=5), "Asia/Riyadh")
    assert result["fuel_litres"] == 100
    assert result["energy_kwh"] == 300
    assert result["kwh_per_litre"] == 3
    assert result["litres_per_kwh"] == 0.3333
    assert result["litres_per_hour"] == 20
    assert result["efficiency_percent"] == 30


def test_counter_reset_and_unverified_history_do_not_inflate_totals():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    samples = [sample(start + timedelta(minutes=2*i), fuel, energy, i / 30)
               for i, (fuel, energy) in enumerate([(0, 0), (2, 6), (4, 12), (0, 0), (2, 6)])]
    result, _ = generator_report(panel(), samples, start, start + timedelta(minutes=8), "UTC")
    assert result["fuel_litres"] == 6
    assert result["energy_kwh"] == 18
    assert "counter_reset" in result["issues"]
    old = [sample(start, 0, 0, 0, quality=False), sample(start + timedelta(minutes=2), 10, 30, .1, quality=False)]
    unknown, _ = generator_report(panel(), old, start, start + timedelta(minutes=2), "UTC")
    assert unknown["fuel_litres"] is None
    assert unknown["kwh_per_litre"] is None


def test_site_today_starts_at_local_midnight():
    now = datetime(2026, 9, 20, 2, 0, tzinfo=timezone.utc)
    start, end = report_window("today", "Asia/Riyadh", now=now)
    assert start == datetime(2026, 9, 19, 21, 0, tzinfo=timezone.utc)
    assert end == now
