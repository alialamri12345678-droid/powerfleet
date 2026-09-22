"""Periodically evaluate maintenance for facilities owned by this gateway."""

import asyncio
import logging

from app.db.session import async_session_factory
from app.services.maintenance import evaluate_site_maintenance, emit_due_events

logger = logging.getLogger(__name__)


async def monitor_maintenance(gateway, stop_event: asyncio.Event) -> None:
    while not stop_event.is_set():
        # Read current assignments each pass, including newly added panels.
        site_ids = {state.site_id for state in list(gateway.states.values()) if state.site_id}
        for site_id in site_ids:
            if stop_event.is_set():
                break
            try:
                async with async_session_factory() as session:
                    await evaluate_site_maintenance(session, site_id, gateway=gateway)
                    await emit_due_events(session, site_id)
                    await session.commit()
            except Exception:
                logger.exception("Maintenance evaluation failed for facility %s", site_id)
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=60)
        except asyncio.TimeoutError:
            pass
