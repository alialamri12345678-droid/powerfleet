"""Diagnostics API router — raw registers, connection health, and overrides."""

from datetime import datetime, timedelta, timezone
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import OverrideRequest, OverrideResponse
from app.auth.models import User
from app.db.session import get_session
from app.db.tenant import scoped_get, scoped_select
from app.dependencies import get_current_user, get_gateway
from app.models.override import Override
from app.models.panel import Panel
from app.models.telemetry_sample import TelemetrySample
from app.modbus.gateway import ModbusGateway
from app.services.commands import enqueue_command
from app.modbus.register_map import load_register_map
from app.config import settings
from app.controllers import create_adapter, get_controller_profile
from sqlalchemy import desc

router = APIRouter(prefix="/diagnostics", tags=["Diagnostics"])


@router.get("/panels/{panel_id}/raw")
async def get_raw_registers(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
) -> dict[str, Any]:
    """Read all registers defined in register_map.yaml for the specified panel."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    latest = None
    if gateway:
        reg_dump = await gateway.read_all_registers(panel_id)
        state = gateway.states.get(panel_id)
    else:
        latest = (await session.execute(scoped_select(TelemetrySample, user.site_id).where(
            TelemetrySample.panel_id == panel_id
        ).order_by(desc(TelemetrySample.recorded_at)).limit(1))).scalars().first()
        reg_dump = latest.readings if latest else {}
        state = None

    return {
        "panel_id": panel_id,
        "panel_name": panel.name,
        "is_reachable": state.is_reachable if state else bool(latest and latest.is_reachable),
        "registers": reg_dump,
    }


@router.get("/panels/{panel_id}/health")
async def get_panel_health(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
) -> dict[str, Any]:
    """Get connection diagnostic telemetry for a panel."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    state = gateway.states.get(panel_id) if gateway else None
    latest = None
    if not state:
        latest = (await session.execute(scoped_select(TelemetrySample, user.site_id).where(
            TelemetrySample.panel_id == panel_id
        ).order_by(desc(TelemetrySample.recorded_at)).limit(1))).scalars().first()
    if not state and not latest:
        raise HTTPException(status_code=404, detail="Panel state unavailable")

    return {
        "panel_id": panel_id,
        "name": panel.name,
        "transport_type": panel.transport_type,
        "address": panel.address,
        "unit_id": panel.unit_id,
        "is_reachable": state.is_reachable if state else latest.is_reachable,
        "consecutive_errors": state.consecutive_errors if state else 0,
        "last_error": state.last_error if state else None,
        "last_successful_poll": state.last_successful_poll.isoformat() if state and state.last_successful_poll else latest.recorded_at.isoformat(),
        "engine_status": state.engine_status if state else latest.engine_status,
        "active_alarms": state.active_alarms if state else [],
    }


@router.get("/panels/{panel_id}/controller-profile")
async def controller_profile_status(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")
    register_map = load_register_map(settings.register_map_path)
    profile = get_controller_profile(panel.controller_profile)
    profile_map = create_adapter(panel.controller_profile, register_map).register_map
    commissioned = register_map.version.startswith("gencomm-")
    return {
        "profile": panel.controller_profile, "map_version": register_map.version,
        "map_family": profile.map_family,
        "commissioned": commissioned,
        "readable_parameters": len(profile_map.readable_registers()),
        "warning": "Verify model-specific optional points against the controller firmware during commissioning.",
    }


# ── Overrides ───────────────────────────────────────────────────────────
@router.get("/overrides", response_model=list[OverrideResponse])
async def list_active_overrides(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[OverrideResponse]:
    """List all currently active overrides for the site (visible to all users)."""
    now = datetime.now(timezone.utc)
    stmt = (
        scoped_select(Override, user.site_id)
        .where(Override.is_active.is_(True))
        .where(Override.expires_at > now)
    )
    result = await session.execute(stmt)
    overrides = result.scalars().all()
    return [OverrideResponse.model_validate(o) for o in overrides]


@router.post("/panels/{panel_id}/override", response_model=OverrideResponse)
async def create_override(
    panel_id: str,
    body: OverrideRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway: Annotated[ModbusGateway | None, Depends(get_gateway)],
) -> OverrideResponse:
    """Force start or stop on a panel with mandatory expiration."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    # Deactivate existing active overrides on this panel
    existing = await session.execute(
        select(Override).where(
            Override.panel_id == panel_id,
            Override.is_active.is_(True),
        )
    )
    for ov in existing.scalars().all():
        ov.is_active = False

    expires_at = datetime.now(timezone.utc) + timedelta(minutes=body.duration_minutes)

    override = Override(
        site_id=user.site_id,
        panel_id=panel_id,
        override_type=body.override_type,
        created_by=user.id,
        expires_at=expires_at,
        is_active=True,
        reason=body.reason or f"Manual override by customer {user.full_name or user.email}",
    )
    # Issue the commanded action to the gateway first
    success = True
    msg = ""
    if gateway is None:
        command = "remote_start" if body.override_type == "force_start" else "remote_stop"
        await enqueue_command(panel, command, "override", override.reason or "Customer override", user.id)
    elif body.override_type == "force_start":
        success, msg = await gateway.send_remote_start(
            panel_id=panel_id,
            triggered_by="override",
            reason=f"Customer override (expires in {body.duration_minutes}m): {override.reason}",
            user_id=user.id,
        )
    elif body.override_type == "force_stop":
        success, msg = await gateway.send_remote_stop(
            panel_id=panel_id,
            triggered_by="override",
            reason=f"Customer override (expires in {body.duration_minutes}m): {override.reason}",
            user_id=user.id,
        )

    if not success:
        await session.rollback()
        raise HTTPException(status_code=400, detail=f"Modbus command failed: {msg}")

    # Commit only if Modbus command succeeds
    session.add(override)
    await session.commit()
    await session.refresh(override)

    return OverrideResponse.model_validate(override)


@router.delete("/panels/{panel_id}/override")
async def release_override(
    panel_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Release active override on a panel."""
    panel = await scoped_get(session, Panel, panel_id, user.site_id)
    if panel is None:
        raise HTTPException(status_code=404, detail="Panel not found")

    stmt = select(Override).where(
        Override.panel_id == panel_id,
        Override.is_active.is_(True),
    )
    result = await session.execute(stmt)
    overrides = result.scalars().all()

    for ov in overrides:
        ov.is_active = False

    await session.commit()
    return {"status": "success", "message": f"Overrides cleared for panel {panel_id}"}
