"""Shared measurement validation: a default scalar zero is not a measurement."""
from __future__ import annotations

from datetime import datetime, timezone
from math import isfinite


def utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def metric_value(sample, key: str, max_age_seconds: float = 180) -> float | None:
    if not getattr(sample, "is_reachable", False):
        return None
    readings = getattr(sample, "readings", None) or {}
    quality = getattr(sample, "reading_quality", None) or {}
    if quality.get(key) != "good" or key not in readings:
        return None
    value = readings.get(key, getattr(sample, key, None))
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not isfinite(value):
        return None
    timestamps = getattr(sample, "reading_timestamps", None) or {}
    timestamp = timestamps.get(key)
    if not timestamp:
        return None
    if timestamp:
        try:
            acquired = utc(datetime.fromisoformat(timestamp)) if isinstance(timestamp, str) else utc(timestamp)
            recorded = getattr(sample, "recorded_at", None) or getattr(sample, "last_successful_poll", None)
            age = (utc(recorded or datetime.now(timezone.utc)) - acquired).total_seconds()
            if age < -5 or age > max_age_seconds:
                return None
        except (TypeError, ValueError):
            return None
    return float(value)


def source_uncertain(sample) -> bool:
    return not bool(getattr(sample, "reading_quality", None)) or not bool(getattr(sample, "reading_timestamps", None))
