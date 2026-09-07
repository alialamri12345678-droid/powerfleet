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


from typing import Any
from app.auth.service import create_access_token

@router.post("/switch/{site_id}", response_model=dict[str, Any])
async def switch_active_site(
    site_id: str,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> dict[str, Any]:
    """Switch the current user's active site context and return a new token."""
    target_site = await session.get(Site, site_id)
    if target_site is None:
        raise HTTPException(status_code=404, detail="Target site not found")

    user.site_id = site_id
    await session.commit()
    
    # Generate new token with updated site_id
    new_token = create_access_token({
        "sub": str(user.id),
        "email": user.email,
        "role": user.role,
        "site_id": str(user.site_id) if user.site_id else None,
    })
    
    return {
        "site": SiteResponse.model_validate(target_site).model_dump(mode="json"),
        "access_token": new_token
    }


@router.patch("/{site_id}", response_model=SiteResponse)
async def update_site(
    site_id: str,
    body: SiteUpdate,
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> SiteResponse:
    """Update any site's settings (technician only)."""
    site = await session.get(Site, site_id)
    if site is None:
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
    user: Annotated[User, Depends(require_technician)],
    session: Annotated[AsyncSession, Depends(get_session)],
):
    """Delete a site and all its generators (technician only)."""
    site = await session.get(Site, site_id)
    if site is None:
        raise HTTPException(status_code=404, detail="Site not found")

    # Prevent cascading deletion of the current user.
    # Reassign the user to a different site if one exists, else prevent deletion.
    stmt = select(Site).where(Site.id != site_id).limit(1)
    result = await session.execute(stmt)
    fallback_site = result.scalars().first()

    if user.site_id == site_id:
        if fallback_site:
            user.site_id = fallback_site.id
            await session.commit()
        else:
            raise HTTPException(
                status_code=400,
                detail="Cannot delete the only existing site. Create another site first."
            )

    # Delete the site (this cascades to panels, thresholds, events, overrides, etc. if ondelete="CASCADE" is set properly).
    await session.delete(site)
    await session.commit()
    return None
