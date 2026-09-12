"""Thresholds API router — load-following trigger levels and hysteresis."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ThresholdCreate, ThresholdResponse, ThresholdUpdate,
    ReleaseThresholdResponse, BulkReleaseThresholdUpdate,
    StartThresholdResponse, BulkStartThresholdUpdate,
)
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_select
from app.dependencies import get_current_user
from app.models.panel import Panel
from app.models.release_threshold import ReleaseThreshold
from app.models.start_threshold import StartThreshold
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


# ── Per-Backup Release Thresholds ──────────────────────────────────────

@router.get("/release", response_model=list[ReleaseThresholdResponse])
async def get_release_thresholds(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ReleaseThresholdResponse]:
    """Get per-backup-unit release thresholds for the site.
    Auto-creates entries for any panels that don't have one yet.
    """
    # Get all panels for this site
    panels_stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority)
    panels_result = await session.execute(panels_stmt)
    panels = panels_result.scalars().all()

    # Get existing release thresholds
    rt_stmt = scoped_select(ReleaseThreshold, user.site_id).where(
        ReleaseThreshold.panel_id.in_([p.id for p in panels])
    )
    rt_result = await session.execute(rt_stmt)
    existing_rts = {rt.panel_id: rt for rt in rt_result.scalars().all()}

    # Get the site's default stop_pct for auto-seeding
    thresh_stmt = scoped_select(Threshold, user.site_id).where(Threshold.panel_id.is_(None))
    thresh_result = await session.execute(thresh_stmt)
    site_thresh = thresh_result.scalar_one_or_none()
    default_release_pct = float(site_thresh.stop_pct) if site_thresh else 50.0

    # Auto-create missing release thresholds
    created_any = False
    for panel in panels:
        if panel.id not in existing_rts:
            rt = ReleaseThreshold(
                site_id=user.site_id,
                panel_id=panel.id,
                release_pct=default_release_pct,
                priority_order=panel.priority,
            )
            session.add(rt)
            existing_rts[panel.id] = rt
            created_any = True

    if created_any:
        await session.commit()
        for rt in existing_rts.values():
            await session.refresh(rt)

    # Build response with panel names
    panel_name_map = {p.id: p.name for p in panels}
    results = []
    for rt in sorted(existing_rts.values(), key=lambda x: x.priority_order):
        resp = ReleaseThresholdResponse(
            id=rt.id,
            site_id=rt.site_id,
            panel_id=rt.panel_id,
            release_pct=float(rt.release_pct),
            priority_order=rt.priority_order,
            panel_name=panel_name_map.get(rt.panel_id),
            created_at=rt.created_at,
            updated_at=rt.updated_at,
        )
        results.append(resp)

    return results


@router.put("/release", response_model=list[ReleaseThresholdResponse])
async def update_release_thresholds(
    body: BulkReleaseThresholdUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ReleaseThresholdResponse]:
    """Bulk update per-backup release thresholds for the site."""
    # Validate panel IDs belong to site
    panels_stmt = scoped_select(Panel, user.site_id)
    panels_result = await session.execute(panels_stmt)
    panels = panels_result.scalars().all()
    panel_ids = {p.id for p in panels}
    panel_name_map = {p.id: p.name for p in panels}

    for item in body.thresholds:
        if item.panel_id not in panel_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panel '{item.panel_id}' does not belong to this site.",
            )

    # Get existing release thresholds
    rt_stmt = scoped_select(ReleaseThreshold, user.site_id)
    rt_result = await session.execute(rt_stmt)
    existing_rts = {rt.panel_id: rt for rt in rt_result.scalars().all()}

    updated_rts = []
    for item in body.thresholds:
        rt = existing_rts.get(item.panel_id)
        if rt:
            rt.release_pct = item.release_pct
            rt.priority_order = item.priority_order
        else:
            rt = ReleaseThreshold(
                site_id=user.site_id,
                panel_id=item.panel_id,
                release_pct=item.release_pct,
                priority_order=item.priority_order,
            )
            session.add(rt)
        updated_rts.append(rt)

    await session.commit()
    for rt in updated_rts:
        await session.refresh(rt)

    results = []
    for rt in sorted(updated_rts, key=lambda x: x.priority_order):
        resp = ReleaseThresholdResponse(
            id=rt.id,
            site_id=rt.site_id,
            panel_id=rt.panel_id,
            release_pct=float(rt.release_pct),
            priority_order=rt.priority_order,
            panel_name=panel_name_map.get(rt.panel_id),
            created_at=rt.created_at,
            updated_at=rt.updated_at,
        )
        results.append(resp)

    return results


# ── Per-Backup Start Thresholds (facility-load based) ──────────────────

@router.get("/start", response_model=list[StartThresholdResponse])
async def get_start_thresholds(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StartThresholdResponse]:
    """Get per-backup-unit start thresholds for the site.
    Auto-creates entries for any panels that don't have one yet.
    """
    # Get all panels for this site
    panels_stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority)
    panels_result = await session.execute(panels_stmt)
    panels = panels_result.scalars().all()

    # Get existing start thresholds
    st_stmt = scoped_select(StartThreshold, user.site_id).where(
        StartThreshold.panel_id.in_([p.id for p in panels])
    )
    st_result = await session.execute(st_stmt)
    existing_sts = {st.panel_id: st for st in st_result.scalars().all()}

    # Get the site's default start_pct for auto-seeding
    thresh_stmt = scoped_select(Threshold, user.site_id).where(Threshold.panel_id.is_(None))
    thresh_result = await session.execute(thresh_stmt)
    site_thresh = thresh_result.scalar_one_or_none()
    default_start_pct = float(site_thresh.start_pct) if site_thresh else 70.0

    # Auto-create missing start thresholds
    created_any = False
    for panel in panels:
        if panel.id not in existing_sts:
            st = StartThreshold(
                site_id=user.site_id,
                panel_id=panel.id,
                start_pct=default_start_pct,
                priority_order=panel.priority,
            )
            session.add(st)
            existing_sts[panel.id] = st
            created_any = True

    if created_any:
        await session.commit()
        for st in existing_sts.values():
            await session.refresh(st)

    # Build response with panel names
    panel_name_map = {p.id: p.name for p in panels}
    results = []
    for st in sorted(existing_sts.values(), key=lambda x: x.priority_order):
        resp = StartThresholdResponse(
            id=st.id,
            site_id=st.site_id,
            panel_id=st.panel_id,
            start_pct=float(st.start_pct),
            priority_order=st.priority_order,
            panel_name=panel_name_map.get(st.panel_id),
            created_at=st.created_at,
            updated_at=st.updated_at,
        )
        results.append(resp)

    return results


@router.put("/start", response_model=list[StartThresholdResponse])
async def update_start_thresholds(
    body: BulkStartThresholdUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[StartThresholdResponse]:
    """Bulk update per-backup start thresholds for the site."""
    # Validate panel IDs belong to site
    panels_stmt = scoped_select(Panel, user.site_id)
    panels_result = await session.execute(panels_stmt)
    panels = panels_result.scalars().all()
    panel_ids = {p.id for p in panels}
    panel_name_map = {p.id: p.name for p in panels}

    for item in body.thresholds:
        if item.panel_id not in panel_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panel '{item.panel_id}' does not belong to this site.",
            )

    # Get existing start thresholds
    st_stmt = scoped_select(StartThreshold, user.site_id)
    st_result = await session.execute(st_stmt)
    existing_sts = {st.panel_id: st for st in st_result.scalars().all()}

    updated_sts = []
    for item in body.thresholds:
        st = existing_sts.get(item.panel_id)
        if st:
            st.start_pct = item.start_pct
            st.priority_order = item.priority_order
        else:
            st = StartThreshold(
                site_id=user.site_id,
                panel_id=item.panel_id,
                start_pct=item.start_pct,
                priority_order=item.priority_order,
            )
            session.add(st)
        updated_sts.append(st)

    await session.commit()
    for st in updated_sts:
        await session.refresh(st)

    results = []
    for st in sorted(updated_sts, key=lambda x: x.priority_order):
        resp = StartThresholdResponse(
            id=st.id,
            site_id=st.site_id,
            panel_id=st.panel_id,
            start_pct=float(st.start_pct),
            priority_order=st.priority_order,
            panel_name=panel_name_map.get(st.panel_id),
            created_at=st.created_at,
            updated_at=st.updated_at,
        )
        results.append(resp)

    return results
