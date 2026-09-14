"""Authentication router handling login, token refresh, and user profile."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.auth.schemas import LoginRequest, RefreshRequest, TokenResponse, UserResponse
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_password,
    create_stream_token,
)
from app.db.session import get_session
from app.dependencies import get_current_user

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.get("/stream-token")
async def stream_token(current_user: Annotated[User, Depends(get_current_user)]):
    return {"token": create_stream_token({
        "sub": current_user.id,
        "site_id": current_user.site_id,
        "organization_id": current_user.organization_id,
    })}


@router.post("/login", response_model=TokenResponse)
async def login(
    body: LoginRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    """Authenticate user with email and password, returning JWT tokens."""
    stmt = select(User).where(User.email == body.email)
    result = await session.execute(stmt)
    user = result.scalar_one_or_none()

    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Incorrect email or password",
            headers={"WWW-Authenticate": "Bearer"},
        )

    claims = {
        "sub": user.id,
        "role": user.role,
        "site_id": user.site_id,
        "email": user.email,
        "organization_id": user.organization_id,
    }
    access_token = create_access_token(claims)
    refresh_token = create_refresh_token(claims)

    return TokenResponse(
        access_token=access_token,
        refresh_token=refresh_token,
        role=user.role,
        site_id=user.site_id,
        user_id=user.id,
        full_name=user.full_name,
        organization_id=user.organization_id,
    )


@router.post("/refresh", response_model=TokenResponse)
async def refresh_token(
    body: RefreshRequest,
    session: Annotated[AsyncSession, Depends(get_session)],
) -> TokenResponse:
    """Issue a new access token using a valid refresh token."""
    payload = decode_token(body.refresh_token)
    if payload is None or payload.get("type") != "refresh":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired refresh token",
        )

    user_id = payload.get("sub")
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )

    requested_site_id = payload.get("site_id") or user.site_id
    from app.models.site import Site
    requested_site = await session.get(Site, requested_site_id)
    if requested_site is None or requested_site.organization_id != user.organization_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Site is not available to this customer")

    claims = {
        "sub": user.id,
        "role": user.role,
        "site_id": requested_site_id,
        "email": user.email,
        "organization_id": user.organization_id,
    }
    new_access_token = create_access_token(claims)
    new_refresh_token = create_refresh_token(claims)

    return TokenResponse(
        access_token=new_access_token,
        refresh_token=new_refresh_token,
        role=user.role,
        site_id=requested_site_id,
        user_id=user.id,
        full_name=user.full_name,
        organization_id=user.organization_id,
    )


@router.get("/me", response_model=UserResponse)
async def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserResponse:
    """Return profile details for the currently authenticated user."""
    return UserResponse.model_validate(current_user)
