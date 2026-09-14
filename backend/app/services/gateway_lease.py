"""Cross-process facility ownership using renewable database leases."""

from datetime import datetime, timedelta, timezone

from sqlalchemy import delete, select, text, update

from app.db.session import async_session_factory
from app.models.gateway_lease import GatewayLease


async def acquire_site_leases(owner_id: str, site_ids: list[str], ttl_seconds: int) -> set[str]:
    now = datetime.now(timezone.utc)
    expires = now + timedelta(seconds=ttl_seconds)
    async with async_session_factory() as session:
        for site_id in site_ids:
            await session.execute(text(
                "INSERT INTO gateway_leases (site_id, owner_id, heartbeat_at, expires_at) "
                "VALUES (:site_id, :owner_id, :now, :expires) "
                "ON CONFLICT(site_id) DO UPDATE SET owner_id=:owner_id, heartbeat_at=:now, expires_at=:expires "
                "WHERE gateway_leases.expires_at < :now OR gateway_leases.owner_id = :owner_id"
            ), {"site_id": site_id, "owner_id": owner_id, "now": now, "expires": expires})
        await session.commit()
        result = await session.execute(select(GatewayLease.site_id).where(
            GatewayLease.owner_id == owner_id, GatewayLease.expires_at > now
        ))
        return set(result.scalars().all())


async def renew_site_leases(owner_id: str, ttl_seconds: int) -> int:
    now = datetime.now(timezone.utc)
    result_count = 0
    async with async_session_factory() as session:
        result = await session.execute(update(GatewayLease).where(
            GatewayLease.owner_id == owner_id, GatewayLease.expires_at > now
        ).values(heartbeat_at=now, expires_at=now + timedelta(seconds=ttl_seconds)))
        result_count = result.rowcount or 0
        await session.commit()
    return result_count


async def release_site_leases(owner_id: str) -> None:
    async with async_session_factory() as session:
        await session.execute(delete(GatewayLease).where(GatewayLease.owner_id == owner_id))
        await session.commit()
