"""FastAPI dependencies for authentication and service access."""

from typing import Annotated, Any

from fastapi import Depends, HTTPException, Query, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.service import decode_token
from app.db.session import get_session
from app.auth.models import User
from app.models.site import Site

# Security scheme for Bearer token
security_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Security(security_bearer)],
    session: Annotated[AsyncSession, Depends(get_session)],
) -> User:
    """Extract and validate the current user from the Authorization header."""
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_token(credentials.credentials)
    if payload is None or payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired access token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: str | None = payload.get("sub")
    if user_id is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token payload missing subject identifier",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User account no longer exists",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claimed_org = payload.get("organization_id")
    if claimed_org and claimed_org != user.organization_id:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Account access has changed; sign in again")
    claimed_site = payload.get("site_id") or user.site_id
    site = await session.get(Site, claimed_site)
    # If the selected site was deleted, fall back to the account's current
    # site. This is the only time database context supersedes session context.
    if site is None and claimed_site != user.site_id:
        claimed_site = user.site_id
        site = await session.get(Site, claimed_site)
    if site is None or site.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Site is not available to this customer")

    # Site selection belongs to this token/session. Detaching prevents an API
    # request from accidentally persisting another browser session's context.
    session.sync_session.expunge(user)
    user.site_id = claimed_site
    return user


async def get_site_id(
    user: Annotated[User, Depends(get_current_user)],
) -> str:
    """Return the site_id associated with the authenticated user."""
    return user.site_id


# Singletons injected into app.state
def get_gateway():
    from app.main import gateway_instance
    return gateway_instance


def get_rules_engine():
    from app.main import rules_engine_instance
    return rules_engine_instance
