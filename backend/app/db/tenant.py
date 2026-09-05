"""Multi-tenant query scoping helpers.

Every database query that touches tenant-scoped data MUST use these helpers
to ensure site isolation. Never query a TenantMixin-derived model without
filtering by site_id.
"""

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import TenantMixin


def scoped_select(model, site_id: str) -> Select:
    """Return a SELECT statement pre-filtered by site_id.

    Usage::

        stmt = scoped_select(Panel, current_user.site_id)
        result = await session.execute(stmt)
        panels = result.scalars().all()
    """
    if not issubclass(model, TenantMixin):
        raise TypeError(
            f"{model.__name__} does not inherit TenantMixin — "
            "cannot scope by site_id"
        )
    return select(model).where(model.site_id == site_id)


async def scoped_get(
    session: AsyncSession, model, record_id: str, site_id: str
):
    """Fetch a single record by PK, enforcing site_id match.

    Returns None if the record doesn't exist or belongs to a different site.
    """
    obj = await session.get(model, record_id)
    if obj is None:
        return None
    if hasattr(obj, "site_id") and obj.site_id != site_id:
        return None  # Treat cross-tenant access as "not found"
    return obj


async def scoped_get_or_404(
    session: AsyncSession, model, record_id: str, site_id: str
):
    """Like scoped_get but raises ValueError if not found."""
    obj = await scoped_get(session, model, record_id, site_id)
    if obj is None:
        raise ValueError(
            f"{model.__name__} {record_id!r} not found in site {site_id!r}"
        )
    return obj
