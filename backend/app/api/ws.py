"""WebSocket router streaming live panel telemetry and gateway status to connected clients."""

import asyncio
import json
import logging
from typing import Any

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect, status

from app.auth.service import decode_token
from app.modbus.panel_state import PanelState

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
    if payload is None or payload.get("type") != "access":
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="Invalid or expired token")
        return

    site_id = payload.get("site_id")
    if not site_id:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION, reason="No site_id in token")
        return

    await ws_manager.connect(site_id, websocket)

    # Send initial state snapshot immediately
    from app.main import gateway_instance
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

    try:
        while True:
            # Keepalive listener
            data = await websocket.receive_text()
            if data == "ping":
                await websocket.send_text(json.dumps({"type": "pong"}))
    except WebSocketDisconnect:
        await ws_manager.disconnect(site_id, websocket)
    except Exception as exc:
        logger.warning("WebSocket exception: %s", exc)
        await ws_manager.disconnect(site_id, websocket)
