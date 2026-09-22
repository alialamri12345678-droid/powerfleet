"""Sites API router — multi-site management and site context switching."""

from typing import Annotated
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SiteCreate, SiteResponse, SiteUpdate
from app.auth.models import User
from app.db.session import get_session
from app.dependencies import get_current_user, get_gateway, get_rules_engine
from app.models.panel import Panel
from app.models.site import Site
from app.models.site_supply import SiteSupply
from app.models.event import Event
from app.models.threshold import Threshold
from app.api.dispatch_config import DispatchConfig, SitePowerReading
from app.rules.adaptive_planner import settings as dispatch_settings

router = APIRouter(prefix="/sites", tags=["Sites"])


async def _owned_site(session, site_id, user):
    site = await session.get(Site, site_id)
    if not site or site.organization_id != user.organization_id:
        raise HTTPException(404, "Site not found")
    return site


@router.get("/{site_id}/dispatch")
async def get_dispatch(site_id: str, user: Annotated[User, Depends(get_current_user)],
                       session: Annotated[AsyncSession, Depends(get_session)]):
    site = await _owned_site(session, site_id, user)
    supply = await session.get(SiteSupply, site_id)
    config = dispatch_settings(site.dispatch_config)
    age = ((datetime.now(timezone.utc) - (supply.measured_at.replace(tzinfo=timezone.utc)
            if supply.measured_at.tzinfo is None else supply.measured_at)).total_seconds() if supply else None)
    return {"config": config, "measurement": supply.reading if supply else None,
            "measured_at": supply.measured_at if supply else None,
            "measurement_fresh": bool(supply and 0 <= age <= config["measurement_max_age_seconds"]),
            "plan": supply.plan if supply else None, "planned_at": supply.planned_at if supply else None}


@router.patch("/{site_id}/dispatch")
async def update_dispatch(site_id: str, body: DispatchConfig,
                          user: Annotated[User, Depends(get_current_user)],
                          session: Annotated[AsyncSession, Depends(get_session)]):
    site = await _owned_site(session, site_id, user)
    previous = dispatch_settings(site.dispatch_config)["mode"]
    site.dispatch_config = body.model_dump()
    session.add(Event(site_id=site_id, event_type="system", command="dispatch_config",
                      value=body.mode, triggered_by="manual", user_id=user.id,
                      reason="Site source and generator dispatch settings updated",
                      previous_state=previous, new_state=body.mode, command_result="success"))
    await session.commit()
    return {"config": site.dispatch_config}


@router.post("/{site_id}/dispatch/measurement")
async def record_dispatch_measurement(site_id: str, body: SitePowerReading,
                                      user: Annotated[User, Depends(get_current_user)],
                                      session: Annotated[AsyncSession, Depends(get_session)]):
    await _owned_site(session, site_id, user)
    now = datetime.now(timezone.utc)
    measured = body.measured_at.astimezone(timezone.utc)
    if measured > now + timedelta(seconds=5) or measured < now - timedelta(minutes=5):
        raise HTTPException(422, "Source measurement timestamp must be recent")
    supply = await session.get(SiteSupply, site_id)
    if supply and measured <= (supply.measured_at.replace(tzinfo=timezone.utc)
                              if supply.measured_at.tzinfo is None else supply.measured_at):
        raise HTTPException(409, "Source measurements must arrive in chronological order")
    if supply is None:
        supply = SiteSupply(site_id=site_id, measured_at=measured, reading=body.model_dump(mode="json"))
        session.add(supply)
    else:
        supply.measured_at = measured
        supply.reading = body.model_dump(mode="json")
    await session.commit()
    return {"status": "recorded", "measured_at": measured}


@router.get("", response_model=list[SiteResponse])
async def list_sites(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SiteResponse]:
    """List sites visible to the current user."""
    stmt = select(Site).where(Site.organization_id == user.organization_id).order_by(Site.name)
    result = await session.execute(stmt)
    sites = result.scalars().all()
    return [SiteResponse.model_validate(s) for s in sites]


@router.get("/current", response_model=SiteResponse)
async def get_current_site(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Get the current user's active site details."""
    site = await session.get(Site, user.site_id)
    if site is None or site.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Site not found")
    return SiteResponse.model_validate(site)


@router.post("", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Create a new site facility. Automatically initializes default load thresholds."""
    new_site = Site(
        organization_id=user.organization_id,
        name=body.name,
        address=body.address,
        timezone=body.timezone,
        max_parallel_units=body.max_parallel_units,
    )
    session.add(new_site)
    await session.flush()

    # Seed default threshold for the new site
    threshold = Threshold(
        site_id=new_site.id,
        panel_id=None,
        start_pct=70.0,
        stop_pct=50.0,
        dwell_seconds=120,
    )
    session.add(threshold)
    await session.commit()
    await session.refresh(new_site)

    return SiteResponse.model_validate(new_site)


from typing import Any
from app.auth.service import create_access_token, create_refresh_token

@router.post("/switch/{site_id}", response_model=dict[str, Any])
async def switch_active_site(
    site_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Switch the current user's active site context and return a new token."""
    target_site = await session.get(Site, site_id)
    if target_site is None or target_site.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Target site not found")

    # Site context is token/session-local, so two open browser sessions can use
    # different facilities without changing each other's selected site.
    claims = {
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "site_id": str(site_id),
        "organization_id": user.organization_id,
    }
    new_token = create_access_token(claims)
    new_refresh_token = create_refresh_token(claims)
    
    return {
        "site": SiteResponse.model_validate(target_site).model_dump(mode="json"),
        "access_token": new_token,
        "refresh_token": new_refresh_token,
    }


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: str,
    body: SiteUpdate,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Update any site's settings."""
    site = await session.get(Site, site_id)
    if site is None or site.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Site not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(site, field, value)

    await session.commit()
    await session.refresh(site)
    return SiteResponse.model_validate(site)


@router.delete("/{site_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_site(
    site_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
    gateway=Depends(get_gateway),
    rules_engine=Depends(get_rules_engine),
):
    """Delete a site and all its generators."""
    site = await session.get(Site, site_id)
    if site is None or site.organization_id != user.organization_id:
        raise HTTPException(status_code=404, detail="Site not found")

    # Accounts belong to the customer installation; deleting a facility must
    # not delete colleagues whose active site happens to be that facility.
    stmt = select(Site).where(
        Site.organization_id == user.organization_id,
        Site.id != site_id,
    ).limit(1)
    result = await session.execute(stmt)
    fallback_site = result.scalars().first()

    if fallback_site is None:
        raise HTTPException(
            status_code=400,
            detail="Cannot delete the only existing site. Create another site first."
        )
    await session.execute(update(User).where(
        User.organization_id == user.organization_id,
        User.site_id == site_id,
    ).values(site_id=fallback_site.id))
    panel_ids = (await session.execute(select(Panel.id).where(Panel.site_id == site_id))).scalars().all()

    # Delete the site (this cascades to panels, thresholds, events, overrides, etc. if ondelete="CASCADE" is set properly).
    await session.delete(site)
    await session.commit()

    for panel_id in panel_ids:
        if gateway:
            gateway.remove_panel(panel_id)
        if rules_engine:
            rules_engine.remove_panel(panel_id)
    if rules_engine:
        from app.main import rules_get_schedules
        await rules_engine.load_schedules(await rules_get_schedules())
    return None
