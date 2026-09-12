"""Panels API router with site scoping and command dispatch."""

import logging
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ManualCommandRequest,
    PanelCreate,
    PanelResponse,
    PanelUpdate,
    DailyPriorityResponse,
    BulkDailyPriorityUpdate,
)
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_get, scoped_select
from app.dependencies import get_current_user, get_gateway, get_rules_engine
from app.models.panel import Panel
from app.models.daily_priority import DailyPriority
from app.models.release_threshold import ReleaseThreshold
from app.models.start_threshold import StartThreshold
from app.models.threshold import Threshold
from app.models.schedule_exception import ScheduleException
from app.models.event import Event
from app.modbus.gateway import ModbusGateway
from app.rules.engine import RulesEngine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/panels", tags=["Panels"])


@router.get("", response_model=list[PanelResponse])
async def list_panels(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[PanelResponse]:
    """List all panels for the current site."""
    stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority, Panel.name)
    result = await session.execute(stmt)
    panels = result.scalars().all()
    return [PanelResponse.model_validate(p) for p in panels]


@router.get("/{panel_id}", response_model=PanelResponse)
async def get_panel(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PanelResponse:
    """Get single panel details scoped to user's site."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")
    return PanelResponse.model_validate(panel)


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


@router.post("", response_model=PanelResponse, status_code=status.HTTP_201_CREATED)
async def create_panel(
    body: PanelCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway, Depends(get_gateway)],
    rules_engine: Annotated[RulesEngine, Depends(get_rules_engine)],
) -> PanelResponse:
    """Create a new panel. Always assigns priority N+1 (last). Auto-seeds daily priorities and release threshold."""
    stmt = scoped_select(Panel, user.site_id)
    existing_panels = (await session.execute(stmt)).scalars().all()
    n_panels = len(existing_panels)
    assigned_priority = n_panels + 1  # Always last position

    panel = Panel(
        site_id=user.site_id,
        name=body.name,
        transport_type=body.transport_type,
        address=body.address,
        unit_id=body.unit_id,
        rated_kw=body.rated_kw,
        rated_kvar=body.rated_kvar,
        priority=assigned_priority,
    )
    session.add(panel)
    await session.flush()  # Get panel.id before seeding related rows

    # Auto-seed daily priorities for all 7 days
    for day in range(7):
        dp = DailyPriority(
            site_id=user.site_id,
            panel_id=panel.id,
            day_of_week=day,
            priority=assigned_priority,
        )
        session.add(dp)

    # Auto-seed release threshold using site's default stop_pct
    thresh_stmt = scoped_select(Threshold, user.site_id).where(Threshold.panel_id.is_(None))
    thresh_result = await session.execute(thresh_stmt)
    site_thresh = thresh_result.scalar_one_or_none()
    default_release_pct = float(site_thresh.stop_pct) if site_thresh else 50.0

    rt = ReleaseThreshold(
        site_id=user.site_id,
        panel_id=panel.id,
        release_pct=default_release_pct,
        priority_order=assigned_priority,
    )
    session.add(rt)

    # Auto-seed start threshold using site's default start_pct
    default_start_pct = float(site_thresh.start_pct) if site_thresh else 70.0
    st = StartThreshold(
        site_id=user.site_id,
        panel_id=panel.id,
        start_pct=default_start_pct,
        priority_order=assigned_priority,
    )
    session.add(st)

    await session.commit()
    await session.refresh(panel)

    # Register in active gateway poll loop if running
    if gateway:
        gateway.add_panel(
            panel_id=panel.id,
            site_id=panel.site_id,
            name=panel.name,
            transport_type=panel.transport_type,
            address=panel.address,
            unit_id=panel.unit_id,
            rated_kw=float(panel.rated_kw),
        )

    # Reload rules engine schedules so it knows about the new panel
    try:
        from app.main import rules_get_schedules
        all_scheds = await rules_get_schedules()
        await rules_engine.load_schedules(all_scheds)
    except Exception as exc:
        logger.warning("Failed to reload schedules after panel create: %s", exc)

    return PanelResponse.model_validate(panel)


@router.patch("/{panel_id}", response_model=PanelResponse)
async def update_panel(
    panel_id: str,
    body: PanelUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
) -> PanelResponse:
    """Update panel properties. Enforces unique priority <= N."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    update_data = body.model_dump(exclude_unset=True)

    if "priority" in update_data and update_data["priority"] is not None:
        new_prio = update_data["priority"]
        stmt = scoped_select(Panel, user.site_id)
        all_panels = (await session.execute(stmt)).scalars().all()
        n_panels = len(all_panels)
        if new_prio < 1 or new_prio > n_panels:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Priority ({new_prio}) cannot exceed number of generators in the site ({n_panels}).",
            )
        # Swap priority with existing panel if another generator has this priority
        other = next((p for p in all_panels if p.id != panel_id and p.priority == new_prio), None)
        if other:
            other.priority = panel.priority

    for field, value in update_data.items():
        setattr(panel, field, value)

    await session.commit()
    await session.refresh(panel)

    # Update in gateway
    if gateway:
        gateway.add_panel(
            panel_id=panel.id,
            site_id=panel.site_id,
            name=panel.name,
            transport_type=panel.transport_type,
            address=panel.address,
            unit_id=panel.unit_id,
            rated_kw=float(panel.rated_kw),
        )

    return PanelResponse.model_validate(panel)


@router.delete("/{panel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_panel(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
    rules_engine: Annotated[RulesEngine, Depends(get_rules_engine)],
):
    """Decommission and delete a panel. Cleans up related data, re-compacts priorities, reloads rules."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    # Remove configuration without ORM cascade relationships as part of the
    # same transaction. This also supports databases created by older versions.
    for model in (StartThreshold, ReleaseThreshold, Threshold, DailyPriority, ScheduleException):
        await session.execute(delete(model).where(model.panel_id == panel_id))

    # Preserve historical audit entries after the generator is decommissioned.
    await session.execute(update(Event).where(Event.panel_id == panel_id).values(panel_id=None))

    # Delete from database (cascades to schedules, setpoints via ORM relationships)
    await session.delete(panel)
    await session.flush()

    # Re-compact remaining panels' priorities so they are 1..N-1
    stmt = scoped_select(Panel, user.site_id).order_by(Panel.priority)
    remaining = (await session.execute(stmt)).scalars().all()
    for idx, p in enumerate(remaining, start=1):
        p.priority = idx

    # Both threshold pages must use the remaining generators' actual ranks.
    ranks = {p.id: p.priority for p in remaining}
    for model in (StartThreshold, ReleaseThreshold):
        rows = (await session.execute(scoped_select(model, user.site_id))).scalars().all()
        for row in rows:
            if row.panel_id in ranks:
                row.priority_order = ranks[row.panel_id]

    # Preserve each day's chosen order, closing the gap left by the deleted unit.
    daily_rows = (await session.execute(
        scoped_select(DailyPriority, user.site_id).order_by(DailyPriority.priority, DailyPriority.panel_id)
    )).scalars().all()
    for day in range(7):
        day_rows = {r.panel_id: r for r in daily_rows if r.day_of_week == day}
        ordered_panels = sorted(remaining, key=lambda p: (
            day_rows[p.id].priority if p.id in day_rows else p.priority, p.priority, p.id,
        ))
        for rank, remaining_panel in enumerate(ordered_panels, start=1):
            row = day_rows.get(remaining_panel.id)
            if row is None:
                row = DailyPriority(site_id=user.site_id, panel_id=remaining_panel.id, day_of_week=day)
                session.add(row)
            row.priority = rank

    await session.commit()

    # Change runtime state only once the database deletion succeeds.
    if gateway:
        gateway.remove_panel(panel_id)
    if rules_engine:
        rules_engine.remove_panel(panel_id)

    # Reload rules engine schedules
    try:
        from app.main import rules_get_schedules
        all_scheds = await rules_get_schedules()
        await rules_engine.load_schedules(all_scheds)
    except Exception as exc:
        logger.warning("Failed to reload schedules after panel delete: %s", exc)

    return None


@router.get("/priorities/daily", response_model=list[DailyPriorityResponse])
async def get_daily_priorities(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DailyPriorityResponse]:
    """Get all daily priorities for panels in the current site."""
    stmt = scoped_select(DailyPriority, user.site_id)
    result = await session.execute(stmt)
    priorities = result.scalars().all()
    return [DailyPriorityResponse.model_validate(p) for p in priorities]


@router.post("/priorities/daily/bulk", response_model=list[DailyPriorityResponse])
async def update_daily_priorities(
    body: BulkDailyPriorityUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[DailyPriorityResponse]:
    """Bulk update daily priorities for the site.
    Rule 1: No generator has the same priority number as another gen in the same site on any day.
    Rule 2: The priority number cannot exceed the number of generators in the site (1 <= priority <= N).
    """
    stmt = scoped_select(Panel, user.site_id)
    panels = (await session.execute(stmt)).scalars().all()
    total_panels = len(panels)
    panel_ids = {p.id for p in panels}

    # Group priorities by day of week
    by_day: dict[int, list[DailyPriorityItem]] = {}
    for item in body.priorities:
        if item.panel_id not in panel_ids:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Generator ID '{item.panel_id}' does not belong to the current site.",
            )
        by_day.setdefault(item.day_of_week, []).append(item)

    for day_of_week, items in by_day.items():
        day_label = DAY_NAMES[day_of_week] if 0 <= day_of_week < 7 else f"Day {day_of_week}"
        seen_priorities = set()
        seen_panels = set()
        for item in items:
            if item.panel_id in seen_panels:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Generator configured multiple times on {day_label}.",
                )
            seen_panels.add(item.panel_id)

            # Rule 2: Cannot exceed the number of generators in the site
            if item.priority < 1 or item.priority > total_panels:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Priority {item.priority} on {day_label} exceeds the number of generators "
                        f"in the site ({total_panels}). Allowed priorities are 1 to {total_panels}."
                    ),
                )
            # Rule 1: No duplicate priorities in the same site
            if item.priority in seen_priorities:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=(
                        f"Duplicate priority {item.priority} on {day_label}. "
                        "Every generator must have a unique priority number."
                    ),
                )
            seen_priorities.add(item.priority)

    # Delete existing priorities for this site
    delete_stmt = select(DailyPriority).where(DailyPriority.site_id == user.site_id)
    result = await session.execute(delete_stmt)
    for p in result.scalars():
        await session.delete(p)
        
    # Insert new priorities
    new_priorities = []
    for item in body.priorities:
        dp = DailyPriority(
            site_id=user.site_id,
            panel_id=item.panel_id,
            day_of_week=item.day_of_week,
            priority=item.priority,
        )
        session.add(dp)
        new_priorities.append(dp)
        
    await session.commit()
    for dp in new_priorities:
        await session.refresh(dp)
        
    return [DailyPriorityResponse.model_validate(p) for p in new_priorities]
# ── Manual Command Dispatch ─────────────────────────────────────────────
@router.post("/{panel_id}/start")
async def manual_remote_start(
    panel_id: str,
    body: ManualCommandRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway, Depends(get_gateway)],
):
    """Trigger a manual Remote Start command. Verified against cooldown and logged."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    reason = f"{body.reason} (by {user.full_name or user.email})"
    
    success, msg = await gateway.send_remote_start(
        panel_id=panel_id,
        triggered_by="manual",
        reason=reason,
        user_id=user.id,
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return {"status": "success", "message": msg}


@router.post("/{panel_id}/stop")
async def manual_remote_stop(
    panel_id: str,
    body: ManualCommandRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway, Depends(get_gateway)],
):
    """Trigger a manual Remote Stop command. Verified against cooldown and logged."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    reason = f"{body.reason} (by {user.full_name or user.email})"
    
    success, msg = await gateway.send_remote_stop(
        panel_id=panel_id,
        triggered_by="manual",
        reason=reason,
        user_id=user.id,
    )

    if not success:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=msg)

    return {"status": "success", "message": msg}
