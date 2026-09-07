"""Schedules API router — weekly duty schedule management and presets."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    BulkScheduleUpdate,
    PresetApplyRequest,
    ScheduleResponse,
    ScheduleExceptionCreate,
    ScheduleExceptionUpdate,
    ScheduleExceptionResponse,
)
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_select
from app.dependencies import get_current_user, get_rules_engine
from app.models.panel import Panel
from app.models.schedule import Schedule
from app.models.schedule_exception import ScheduleException
from app.rules.engine import RulesEngine

router = APIRouter(prefix="/schedules", tags=["Schedules"])


@router.get("", response_model=list[ScheduleResponse])
async def list_schedules(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ScheduleResponse]:
    """List all weekly schedule entries for the current site."""
    stmt = scoped_select(Schedule, user.site_id).order_by(
        Schedule.day_of_week, Schedule.start_time
    )
    result = await session.execute(stmt)
    schedules = result.scalars().all()
    return [ScheduleResponse.model_validate(s) for s in schedules]


@router.post("/bulk", response_model=list[ScheduleResponse])
async def update_bulk_schedules(
    body: BulkScheduleUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    rules_engine: Annotated[RulesEngine, Depends(get_rules_engine)],
) -> list[ScheduleResponse]:
    """Replace entire weekly schedule matrix for the site."""
    # Verify all panel_ids belong to this site
    panel_ids = {item.panel_id for item in body.schedules}
    if panel_ids:
        p_stmt = scoped_select(Panel, user.site_id).where(Panel.id.in_(panel_ids))
        p_res = await session.execute(p_stmt)
        valid_panels = {p.id for p in p_res.scalars().all()}
        invalid = panel_ids - valid_panels
        if invalid:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Panels not found in this site: {invalid}",
            )

    # Delete existing schedules for this site
    await session.execute(delete(Schedule).where(Schedule.site_id == user.site_id))

    # Insert new entries
    created_schedules = []
    for item in body.schedules:
        sched = Schedule(
            site_id=user.site_id,
            panel_id=item.panel_id,
            day_of_week=item.day_of_week,
            start_time=item.start_time,
            end_time=item.end_time,
            is_active=item.is_active,
        )
        session.add(sched)
        created_schedules.append(sched)

    await session.commit()
    for s in created_schedules:
        await session.refresh(s)

    # Reload all active schedules into running rules engine with their site timezones
    from app.main import rules_get_schedules
    all_scheds = await rules_get_schedules()
    await rules_engine.load_schedules(all_scheds)

    return [ScheduleResponse.model_validate(s) for s in created_schedules]


@router.post("/presets", response_model=list[ScheduleResponse])
async def apply_preset(
    body: PresetApplyRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    rules_engine: Annotated[RulesEngine, Depends(get_rules_engine)],
) -> list[ScheduleResponse]:
    """Apply standard schedule presets to simplify configuration."""
    # Fetch site panels
    p_stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority, Panel.created_at)
    p_res = await session.execute(p_stmt)
    panels = p_res.scalars().all()

    if not panels:
        raise HTTPException(status_code=400, detail="No panels configured for site")

    # Clear existing
    await session.execute(delete(Schedule).where(Schedule.site_id == user.site_id))
    new_schedules: list[Schedule] = []

    if body.preset_name == "daily_rotation":
        # Rotate duty daily across available panels (day_of_week % num_panels)
        num_panels = len(panels)
        for day in range(7):
            assigned_panel = panels[day % num_panels]
            sched = Schedule(
                site_id=user.site_id,
                panel_id=assigned_panel.id,
                day_of_week=day,
                start_time="07:00",
                end_time="19:00",
                is_active=True,
            )
            session.add(sched)
            new_schedules.append(sched)

    elif body.preset_name == "load_following_only":
        # Keep 1 primary running every day; other units start via threshold
        primary = None
        if body.primary_panel_id:
            primary = next((p for p in panels if p.id == body.primary_panel_id), None)
        if not primary:
            primary = panels[0]

        for day in range(7):
            sched = Schedule(
                site_id=user.site_id,
                panel_id=primary.id,
                day_of_week=day,
                start_time="00:00",
                end_time="23:59",
                is_active=True,
            )
            session.add(sched)
            new_schedules.append(sched)

    elif body.preset_name == "manual_only":
        # No automated schedule — manual controls and load thresholds only
        pass

    await session.commit()
    for s in new_schedules:
        await session.refresh(s)

    # Sync with rules engine
    from app.main import rules_get_schedules
    all_scheds = await rules_get_schedules()
    await rules_engine.load_schedules(all_scheds)

    return [ScheduleResponse.model_validate(s) for s in new_schedules]


# ── Exceptions ─────────────────────────────────────────────────────────

@router.get("/exceptions", response_model=list[ScheduleExceptionResponse])
async def list_schedule_exceptions(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[ScheduleExceptionResponse]:
    stmt = scoped_select(ScheduleException, user.site_id).order_by(
        ScheduleException.exception_date, ScheduleException.start_time
    )
    result = await session.execute(stmt)
    exceptions = result.scalars().all()
    return [ScheduleExceptionResponse.model_validate(e) for e in exceptions]


@router.post("/exceptions", response_model=ScheduleExceptionResponse)
async def create_schedule_exception(
    body: ScheduleExceptionCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ScheduleExceptionResponse:
    # Verify panel
    p = await session.get(Panel, body.panel_id)
    if not p or p.site_id != user.site_id:
        raise HTTPException(status_code=400, detail="Invalid panel_id")

    if body.is_active and (not body.start_time or not body.end_time):
        raise HTTPException(status_code=400, detail="start_time and end_time required if is_active=True")

    exc = ScheduleException(
        site_id=user.site_id,
        panel_id=body.panel_id,
        exception_date=body.exception_date,
        is_active=body.is_active,
        start_time=body.start_time,
        end_time=body.end_time,
    )
    session.add(exc)
    await session.commit()
    await session.refresh(exc)
    return ScheduleExceptionResponse.model_validate(exc)


@router.delete("/exceptions/{exception_id}")
async def delete_schedule_exception(
    exception_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    stmt = scoped_select(ScheduleException, user.site_id).where(ScheduleException.id == exception_id)
    res = await session.execute(stmt)
    exc = res.scalars().first()
    if not exc:
        raise HTTPException(status_code=404, detail="Exception not found")
        
    await session.delete(exc)
    await session.commit()
    return {"status": "success"}
