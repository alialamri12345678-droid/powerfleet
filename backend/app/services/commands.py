"""Durable command queue used when the web API and site gateway are separate."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

from sqlalchemy import select

from app.db.session import async_session_factory
from app.models.command_record import CommandRecord
from app.models.panel import Panel


async def enqueue_command(panel: Panel, command: str, triggered_by: str, reason: str,
                          user_id: str | None, payload: dict | None = None,
                          command_id: str | None = None) -> CommandRecord:
    record = CommandRecord(
        id=command_id or str(uuid.uuid4()), site_id=panel.site_id, panel_id=panel.id,
        command=command, status="queued", triggered_by=triggered_by,
        requested_by=user_id, reason=reason, payload=payload or {},
    )
    async with async_session_factory() as session:
        session.add(record)
        await session.commit()
        await session.refresh(record)
    return record


async def dispatch_queued_commands(gateway, stop_event) -> None:
    """Process queued commands; database state survives WAN/API restarts."""
    import asyncio
    while not stop_event.is_set():
        async with async_session_factory() as session:
            result = await session.execute(
                select(CommandRecord).where(CommandRecord.status == "queued")
                .order_by(CommandRecord.requested_at).limit(20)
            )
            commands = result.scalars().all()
            for record in commands:
                if record.panel_id not in gateway.states:
                    continue
                record.status = "dispatching"
                record.updated_at = datetime.now(timezone.utc)
            await session.commit()
        for record in commands:
            if record.status != "dispatching" or record.panel_id not in gateway.states:
                continue
            common = dict(
                panel_id=record.panel_id, triggered_by=record.triggered_by,
                reason=record.reason or "", user_id=record.requested_by,
                command_id=record.id,
            )
            if record.command == "remote_start":
                await gateway.send_remote_start(**common)
            elif record.command == "remote_stop":
                await gateway.send_remote_stop(**common)
            elif record.command == "set_power":
                await gateway.write_power_setpoint(
                    panel_id=record.panel_id, kw_pct=int(record.payload.get("kw_pct", 0)),
                    triggered_by=record.triggered_by, reason=record.reason or "",
                    user_id=record.requested_by, command_id=record.id,
                )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=1.0)
        except asyncio.TimeoutError:
            pass
