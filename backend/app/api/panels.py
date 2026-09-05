"""Panels API router with site scoping and command dispatch."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import (
    ManualCommandRequest,
    PanelCreate,
    PanelResponse,
    PanelUpdate,
)
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_get, scoped_select
from app.dependencies import get_current_user, get_gateway, require_technician
from app.models.panel import Panel
from app.modbus.gateway import ModbusGateway

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


@router.post("", response_model=PanelResponse, status_code=status.HTTP_201_CREATED)
async def create_panel(
    body: PanelCreate,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway, Depends(get_gateway)],
) -> PanelResponse:
    """Create a new panel configuration (technician only)."""
    panel = Panel(
        site_id=user.site_id,
        name=body.name,
        transport_type=body.transport_type,
        address=body.address,
        unit_id=body.unit_id,
        rated_kw=body.rated_kw,
        rated_kvar=body.rated_kvar,
        priority=body.priority,
    )
    session.add(panel)
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
        )

    return PanelResponse.model_validate(panel)


@router.patch("/{panel_id}", response_model=PanelResponse)
async def update_panel(
    panel_id: str,
    body: PanelUpdate,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
) -> PanelResponse:
    """Update panel properties (technician only)."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    update_data = body.model_dump(exclude_unset=True)
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
        )

    return PanelResponse.model_validate(panel)


@router.delete("/{panel_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_panel(
    panel_id: str,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
):
    """Decommission and delete a panel (technician only). Unregisters from gateway."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    # Unregister from live gateway poll loop
    if gateway:
        gateway.remove_panel(panel_id)

    # Delete from database (cascades to schedules and setpoints)
    await session.delete(panel)
    await session.commit()
    return None


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
