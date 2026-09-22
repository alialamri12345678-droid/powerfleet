"""Rate-limited durable capture of normalized generator telemetry."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
from datetime import datetime, timedelta, timezone
from sqlalchemy import delete

from app.db.session import async_session_factory
from app.models.panel import Panel
from app.models.telemetry_sample import TelemetrySample
from app.modbus.panel_state import PanelState
from app.services.measurement_quality import metric_value

logger = logging.getLogger(__name__)


class TelemetryRecorder:
    """Persist one representative snapshot per panel at a controlled interval."""

    def __init__(self, interval_seconds: int = 60, retention_days: int = 400):
        self.interval_seconds = max(5, interval_seconds)
        self.retention_days = max(30, retention_days)
        self._last_recorded: dict[str, float] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._last_cleanup = 0.0

    async def record_if_due(self, panel_id: str, state: PanelState) -> None:
        now = time.monotonic()
        if now - self._last_recorded.get(panel_id, 0.0) < self.interval_seconds:
            return
        lock = self._locks.setdefault(panel_id, asyncio.Lock())
        if lock.locked():
            return
        async with lock:
            now = time.monotonic()
            if now - self._last_recorded.get(panel_id, 0.0) < self.interval_seconds:
                return
            try:
                async with async_session_factory() as session:
                    panel = await session.get(Panel, panel_id)
                    if panel is None:
                        return
                    fuel_config = panel.analytics_config or {}
                    identity_input = [panel.controller_profile, panel.transport_type, panel.address,
                                      panel.unit_id, {key: fuel_config.get(key) for key in
                                                      ("fuel_source", "tank_curve", "fuel_lhv_kwh_per_litre")}]
                    source_identity = hashlib.sha256(json.dumps(identity_input, sort_keys=True).encode()).hexdigest()
                    session.add(TelemetrySample(
                        site_id=panel.site_id,
                        panel_id=panel_id,
                        is_reachable=state.is_reachable,
                        engine_status=state.engine_status,
                        load_kw=state.load_kw,
                        load_kw_percent=state.load_kw_percent,
                        coolant_temperature=state.coolant_temperature,
                        oil_pressure=state.oil_pressure,
                        battery_voltage=state.battery_voltage,
                        fuel_level_percent=state.fuel_level_percent,
                        frequency=state.frequency,
                        run_hours=state.run_hours,
                        total_kwh=state.total_kwh,
                        number_of_starts=state.number_of_starts,
                        active_alarm_count=len(state.active_alarms),
                        readings=state.readings,
                        fuel_used_litres=metric_value(state, "fuel_used_litres"),
                        reading_quality=dict(state.reading_quality),
                        reading_units=dict(state.reading_units),
                        reading_timestamps=dict(state.reading_timestamps),
                        source_identity=source_identity,
                    ))
                    await session.commit()
                self._last_recorded[panel_id] = now
                await self._cleanup_if_due()
            except Exception as exc:
                logger.error("Failed to persist telemetry for panel %s: %s", panel_id, exc)

    def remove_panel(self, panel_id: str) -> None:
        self._last_recorded.pop(panel_id, None)
        self._locks.pop(panel_id, None)

    async def _cleanup_if_due(self) -> None:
        now = time.monotonic()
        if now - self._last_cleanup < 86400:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        async with async_session_factory() as session:
            await session.execute(delete(TelemetrySample).where(TelemetrySample.recorded_at < cutoff))
            await session.commit()
        self._last_cleanup = now
