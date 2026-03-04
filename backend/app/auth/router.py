"""Auth API router: register, login, refresh, logout, and current-user endpoints."""

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.auth.models import User
from app.auth.schemas import LoginRequest, LoginResponse, RegisterRequest, UserResponse
from app.auth.service import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.common.database import get_session
from app.config import settings
from app.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _set_auth_cookies(response: Response, access_token: str, refresh_token: str) -> None:
    """Set httpOnly auth cookies on the response."""
    response.set_cookie(
        "access_token",
        access_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api",
        max_age=settings.access_token_expire_minutes * 60,
    )
    response.set_cookie(
        "refresh_token",
        refresh_token,
        httponly=True,
        secure=settings.cookie_secure,
        samesite="lax",
        path="/api/v1/auth",
        max_age=settings.refresh_token_expire_days * 86400,
    )


@router.post("/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED)
async def register(body: RegisterRequest, session: AsyncSession = Depends(get_session)):
    """Create a new user account."""
    existing = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Email already registered")

    user = User(
        email=body.email,
        name=body.name,
        password_hash=hash_password(body.password),
    )
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


@router.post("/login", response_model=LoginResponse)
async def login(body: LoginRequest, response: Response, session: AsyncSession = Depends(get_session)):
    """Authenticate and set httpOnly auth cookies."""
    user = (await session.execute(select(User).where(User.email == body.email))).scalar_one_or_none()
    if not user or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    access_token = create_access_token(user.id, user.role.value)
    refresh_token = create_refresh_token(user.id)
    _set_auth_cookies(response, access_token, refresh_token)

    return LoginResponse(
        user=UserResponse(
            id=user.id,
            email=user.email,
            name=user.name,
            role=user.role.value,
            is_active=user.is_active,
        ),
    )


@router.post("/refresh")
async def refresh(request: Request, response: Response, session: AsyncSession = Depends(get_session)):
    """Refresh the access token using the refresh token cookie."""
    token = request.cookies.get("refresh_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="No refresh token")

    payload = decode_token(token)
    if not payload or payload.get("type") != "refresh":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid refresh token")

    user = await session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")

    new_access = create_access_token(user.id, user.role.value)
    new_refresh = create_refresh_token(user.id)
    _set_auth_cookies(response, new_access, new_refresh)

    return {"message": "Token refreshed"}


@router.post("/logout")
async def logout(response: Response):
    """Clear auth cookies."""
    response.delete_cookie("access_token", path="/api")
    response.delete_cookie("refresh_token", path="/api/v1/auth")
    return {"message": "Logged out"}


@router.get("/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    """Return the currently authenticated user."""
    return current_user
