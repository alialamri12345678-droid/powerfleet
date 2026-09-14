"""WebSocket router streaming live panel telemetry and gateway status to connected clients."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.auth.service import decode_token
from app.modbus.panel_state import PanelState
from app.db.session import async_session_factory
from app.models.site import Site
from app.models.user import User
from app.models.panel import Panel
from app.models.telemetry_sample import TelemetrySample
from app.config import settings
from sqlalchemy import desc, select

logger = logging.getLogger(__name__)

router = APIRouter(tags=["WebSocket"])


class ConnectionManager:
    """Manages active WebSocket connections grouped by site_id."""

    def __init__(self):
        # site_id -> set of active WebSockets
        self._site_connections: dict[str, set[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, site_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            if site_id not in self._site_connections:
                self._site_connections[site_id] = set()
            self._site_connections[site_id].add(websocket)
        logger.info("WebSocket client connected to site %s (total: %d)", site_id, len(self._site_connections[site_id]))

    async def disconnect(self, site_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            if site_id in self._site_connections:
                self._site_connections[site_id].discard(websocket)
                if not self._site_connections[site_id]:
                    del self._site_connections[site_id]
        logger.info("WebSocket client disconnected from site %s", site_id)

    async def broadcast_to_site(self, site_id: str, message: dict[str, Any]) -> None:
        """Broadcast a message payload to all clients connected to a specific site."""
        websockets = list(self._site_connections.get(site_id, set()))
        if not websockets:
            return

        payload = json.dumps(message)
        dead = []
        for ws in websockets:
            try:
                await ws.send_text(payload)
            except Exception:
                dead.append(ws)

        if dead:
            async with self._lock:
                for ws in dead:
                    self._site_connections.get(site_id, set()).discard(ws)


ws_manager = ConnectionManager()


@router.websocket("/ws/status")
async def websocket_status_endpoint(
    websocket: WebSocket,
    token: str = Query(..., description="JWT Bearer token"),
):
    """Realtime telemetry stream for all panels at the user's site."""
    # Authenticate token from query parameter
    payload = decode_token(token)
    if payload is None or payload.get("type") != "stream":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    site_id = payload.get("site_id")
    if not site_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="No site_id in token")
        return
    async with async_session_factory() as session:
        user = await session.get(User, payload.get("sub"))
        site = await session.get(Site, site_id)
        if user is None or site is None or site.organization_id != user.organization_id:
            await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Site access denied")
            return

    await ws_manager.connect(site_id, websocket)

    # Send initial state snapshot immediately
    from app.main import gateway_instance
    last_db_update = None
    if gateway_instance:
        initial_states = [
            state.to_dict()
            for state in gateway_instance.states.values()
            if state.site_id == site_id
        ]
        await websocket.send_text(json.dumps({
            "type": "initial_state",
            "site_id": site_id,
            "gateway_status": "online",
            "panels": initial_states,
        }))
    else:
        async with async_session_factory() as session:
            panel_rows = (await session.execute(select(Panel).where(Panel.site_id == site_id))).scalars().all()
            names = {panel.id: panel.name for panel in panel_rows}
            samples = (await session.execute(
                select(TelemetrySample).where(TelemetrySample.site_id == site_id)
                .order_by(desc(TelemetrySample.recorded_at)).limit(max(100, len(names) * 3))
            )).scalars().all()
            latest = {}
            for sample in samples:
                latest.setdefault(sample.panel_id, sample)
            initial_states = [_sample_to_state(sample, names.get(sample.panel_id, "Generator")) for sample in latest.values()]
            if samples:
                last_db_update = max(sample.recorded_at for sample in samples)
        await websocket.send_text(json.dumps({
            "type": "initial_state", "site_id": site_id,
            "gateway_status": "online" if initial_states else "waiting",
            "panels": initial_states,
        }))

    try:
        while True:
            # Keepalive listener
            try:
                data = await asyncio.wait_for(websocket.receive_text(), timeout=2.0 if settings.runtime_mode == "api" else 30.0)
                if data == "ping":
                    await websocket.send_text(json.dumps({"type": "pong"}))
            except asyncio.TimeoutError:
                if settings.runtime_mode != "api":
                    continue
                async with async_session_factory() as session:
                    stmt = select(TelemetrySample).where(TelemetrySample.site_id == site_id)
                    if last_db_update is not None:
                        stmt = stmt.where(TelemetrySample.recorded_at > last_db_update)
                    fresh = (await session.execute(stmt.order_by(TelemetrySample.recorded_at).limit(500))).scalars().all()
                    for sample in fresh:
                        panel = await session.get(Panel, sample.panel_id)
                        await websocket.send_text(json.dumps({
                            "type": "panel_update", "panel_id": sample.panel_id,
                            "state": _sample_to_state(sample, panel.name if panel else "Generator"),
                            "timestamp": sample.recorded_at.isoformat(),
                        }))
                        last_db_update = sample.recorded_at
    except WebSocketDisconnect:
        await ws_manager.disconnect(site_id, websocket)
    except Exception as exc:
        logger.warning("WebSocket exception: %s", exc)
        await ws_manager.disconnect(site_id, websocket)


def _sample_to_state(sample: TelemetrySample, panel_name: str) -> dict[str, Any]:
    readings = sample.readings or {}
    engine_status = sample.engine_status
    return {
        "panel_id": sample.panel_id, "panel_name": panel_name, "site_id": sample.site_id,
        "is_reachable": sample.is_reachable, "last_successful_poll": sample.recorded_at.isoformat(),
        "engine_status": engine_status, "is_running": engine_status == "running",
        "display_status": "Running" if engine_status == "running" else ("Idle" if engine_status == "stopped" else engine_status.title()),
        "load_kw": sample.load_kw, "load_kw_percent": sample.load_kw_percent,
        "coolant_temperature": sample.coolant_temperature, "oil_pressure": sample.oil_pressure,
        "battery_voltage": sample.battery_voltage, "fuel_level_percent": sample.fuel_level_percent,
        "frequency": sample.frequency, "run_hours": sample.run_hours,
        "number_of_starts": sample.number_of_starts, "active_alarms": [],
        "readings": readings, "reading_units": {}, "reading_quality": {key: "stored" for key in readings},
        **{key: value for key, value in readings.items() if key not in {"panel_id", "site_id"}},
    }
