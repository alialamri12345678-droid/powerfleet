"""Early warnings require comparable, persistent, trustworthy readings."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from app.services.maintenance import _detect_changes, _verified


def reading(at, pressure, *, load=50, speed=1500, quality=True):
    values = {"oil_pressure": pressure, "load_kw_percent": load, "engine_speed": speed}
    return SimpleNamespace(is_reachable=True, engine_status="running", recorded_at=at,
                           readings=values, reading_quality={key: "good" for key in values} if quality else {},
                           reading_timestamps={key: at.isoformat() for key in values} if quality else {})


def test_sustained_fall_at_similar_load_and_healthy_post_work_verification():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    samples = [reading(start + timedelta(minutes=i), 4.0 if i < 5 else 3.2) for i in range(8)]
    panel = SimpleNamespace(analytics_config={})
    findings = _detect_changes(panel, samples)
    assert len(findings) == 1
    finding = findings[0]
    assert finding["metric"] == "oil_pressure"
    record = SimpleNamespace(metric="oil_pressure", work_recorded_at=start + timedelta(minutes=8), evidence=finding["evidence"])
    assert not _verified(record, samples, panel)
    recovered = samples + [reading(start + timedelta(minutes=i), 4.0) for i in range(9, 12)]
    assert _verified(record, recovered, panel)


def test_single_bad_reading_or_mismatched_load_is_not_a_warning():
    start = datetime(2026, 9, 1, tzinfo=timezone.utc)
    panel = SimpleNamespace(analytics_config={})
    outlier = [reading(start + timedelta(minutes=i), 4.0 if i != 7 else 2.0) for i in range(8)]
    assert not _detect_changes(panel, outlier)
    mismatch = [reading(start + timedelta(minutes=i), 4.0 if i < 5 else 3.0,
                        load=20 if i < 5 else 80) for i in range(8)]
    assert not _detect_changes(panel, mismatch)
    untrusted = [reading(start + timedelta(minutes=i), 4.0 if i < 5 else 3.0,
                         quality=False) for i in range(8)]
    assert not _detect_changes(panel, untrusted)
