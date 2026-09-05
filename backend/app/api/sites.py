"""Sites API router — multi-site management and site context switching."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.schemas import SiteCreate, SiteResponse, SiteUpdate
from app.auth.models import User
from app.db.session import get_session
from app.dependencies import get_current_user, require_technician
from app.models.site import Site
from app.models.threshold import Threshold

router = APIRouter(prefix="/sites", tags=["Sites"])


@router.get("", response_model=list[SiteResponse])
async def list_sites(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> list[SiteResponse]:
    """List all sites registered in the system."""
    stmt = select(Site).order_by(Site.name)
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
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")
    return SiteResponse.model_validate(site)


@router.post("", response_model=SiteResponse, status_code=status.HTTP_201_CREATED)
async def create_site(
    body: SiteCreate,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Create a new site facility (technician only). Automatically initializes default load thresholds."""
    new_site = Site(
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


@router.post("/switch/{site_id}", response_model=SiteResponse)
async def switch_active_site(
    site_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Switch the current user's active site context."""
    target_site = await session.get(Site, site_id)
    if target_site is None:
        raise HTTPException(status_code=404, detail="Target site not found")

    user.site_id = site_id
    await session.commit()
    return SiteResponse.model_validate(target_site)


@router.patch("/current", response_model=SiteResponse)
async def update_current_site(
    body: SiteUpdate,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Update current site settings (technician only)."""
    site = await session.get(Site, user.site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(site, field, value)

    await session.commit()
    await session.refresh(site)
    return SiteResponse.model_validate(site)
