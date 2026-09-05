"""Thresholds API router — load-following trigger levels and hysteresis."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import ThresholdCreate, ThresholdResponse, ThresholdUpdate
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_select
from app.dependencies import get_current_user
from app.models.threshold import Threshold

router = APIRouter(prefix="/thresholds", tags=["Thresholds"])


@router.get("", response_model=ThresholdResponse)
async def get_site_threshold(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ThresholdResponse:
    """Get the load threshold configuration for the current site. Creates default if none exists."""
    stmt = scoped_select(Threshold, user.site_id).where(Threshold.panel_id.is_(None))
    result = await session.execute(stmt)
    threshold = result.scalar_one_or_none()

    if threshold is None:
        # Create sensible default (70% start, 50% stop, 120s dwell)
        threshold = Threshold(
            site_id=user.site_id,
            panel_id=None,
            start_pct=70.0,
            stop_pct=50.0,
            dwell_seconds=120,
        )
        session.add(threshold)
        await session.commit()
        await session.refresh(threshold)

    return ThresholdResponse.model_validate(threshold)


@router.put("", response_model=ThresholdResponse)
async def update_site_threshold(
    body: ThresholdCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ThresholdResponse:
    """Update load threshold settings. Enforces start_pct > stop_pct."""
    stmt = scoped_select(Threshold, user.site_id).where(Threshold.panel_id.is_(None))
    result = await session.execute(stmt)
    threshold = result.scalar_one_or_none()

    if threshold is None:
        threshold = Threshold(
            site_id=user.site_id,
            panel_id=None,
            start_pct=body.start_pct,
            stop_pct=body.stop_pct,
            dwell_seconds=body.dwell_seconds,
        )
        session.add(threshold)
    else:
        threshold.start_pct = body.start_pct
        threshold.stop_pct = body.stop_pct
        threshold.dwell_seconds = body.dwell_seconds

    await session.commit()
    await session.refresh(threshold)
    return ThresholdResponse.model_validate(threshold)
