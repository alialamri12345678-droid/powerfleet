"""Power Setpoints API router (Technician only)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import PowerSetpointCreate, PowerSetpointResponse
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_get, scoped_select
from app.dependencies import get_gateway, require_technician
from app.models.panel import Panel
from app.models.power_setpoint import PowerSetpoint
from app.modbus.gateway import ModbusGateway

router = APIRouter(prefix="/setpoints", tags=["Power Setpoints"])


@router.get("/{panel_id}", response_model=PowerSetpointResponse)
async def get_setpoint(
    panel_id: str,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> PowerSetpointResponse:
    """Get active fixed-power setpoint for a panel."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    stmt = scoped_select(PowerSetpoint, user.site_id).where(
        PowerSetpoint.panel_id == panel_id
    )
    result = await session.execute(stmt)
    sp = result.scalar_one_or_none()

    if sp is None:
        sp = PowerSetpoint(
            site_id=user.site_id,
            panel_id=panel_id,
            target_kw_pct=0.0,
            target_kvar_pct=0.0,
            is_active=False,
        )
        session.add(sp)
        await session.commit()
        await session.refresh(sp)

    return PowerSetpointResponse.model_validate(sp)


@router.put("/{panel_id}", response_model=PowerSetpointResponse)
async def update_setpoint(
    panel_id: str,
    body: PowerSetpointCreate,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway, Depends(get_gateway)],
) -> PowerSetpointResponse:
    """Set fixed-power / base-load target (technician only). Writes to Modbus register."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    stmt = scoped_select(PowerSetpoint, user.site_id).where(
        PowerSetpoint.panel_id == panel_id
    )
    result = await session.execute(stmt)
    sp = result.scalar_one_or_none()

    if sp is None:
        sp = PowerSetpoint(
            site_id=user.site_id,
            panel_id=panel_id,
            target_kw_pct=body.target_kw_pct,
            target_kvar_pct=body.target_kvar_pct,
            is_active=body.is_active,
        )
        session.add(sp)
    else:
        sp.target_kw_pct = body.target_kw_pct
        sp.target_kvar_pct = body.target_kvar_pct
        sp.is_active = body.is_active

    await session.commit()
    await session.refresh(sp)

    # If active, write to Modbus register
    if sp.is_active:
        success, msg = await gateway.write_power_setpoint(
            panel_id=panel_id,
            kw_pct=int(sp.target_kw_pct),
            triggered_by="manual",
            reason=f"Technician setpoint write by {user.full_name or user.email}",
            user_id=user.id,
        )
        if not success:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Failed writing setpoint to panel: {msg}",
            )

    return PowerSetpointResponse.model_validate(sp)
