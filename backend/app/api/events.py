"""Events API router — append-only audit trail logs."""

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import EventResponse
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_select
from app.dependencies import get_current_user
from app.models.event import Event

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("", response_model=list[EventResponse])
async def list_events(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    panel_id: str | None = None,
    event_type: str | None = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> list[EventResponse]:
    """Retrieve immutable audit log events scoped to the site."""
    stmt = scoped_select(Event, user.site_id)

    if panel_id:
        stmt = stmt.where(Event.panel_id == panel_id)
    if event_type:
        stmt = stmt.where(Event.event_type == event_type)

    stmt = stmt.order_by(desc(Event.timestamp)).limit(limit).offset(offset)
    result = await session.execute(stmt)
    events = result.scalars().all()

    return [EventResponse.model_validate(e) for e in events]
