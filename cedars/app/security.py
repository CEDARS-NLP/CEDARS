"""Authentication & authorization primitives for the FastAPI layer.

Preserves the original CEDARS auth semantics (username/password, an ``is_admin``
flag, and "the first registered user becomes an admin") but issues stateless
JWTs delivered as httpOnly cookies instead of Flask-Login server sessions.
Password hashing continues to use ``werkzeug.security`` exactly as before.
"""
from datetime import datetime, timezone

import jwt
from fastapi import Depends, HTTPException, Request, Response, status

from .database import get_global_engine
from .database.db_auth import get_user
from .settings import settings


class CurrentUser:  # pylint: disable=too-few-public-methods
    """Lightweight authenticated-user object (mirrors the old ``User``)."""

    def __init__(self, data):
        self.username = data.user_id
        self.is_admin = bool(data.is_admin)


def _create_token(username, is_admin, token_type, expires_delta):
    now = datetime.now(timezone.utc)
    payload = {
        "sub": username,
        "is_admin": is_admin,
        "type": token_type,
        "iat": now,
        "exp": now + expires_delta,
    }
    return jwt.encode(payload, settings.SECRET_KEY, algorithm=settings.JWT_ALGORITHM)


def create_access_token(username, is_admin):
    """Create a short-lived access token."""
    return _create_token(username, is_admin, "access", settings.ACCESS_TOKEN_TTL)


def create_refresh_token(username, is_admin):
    """Create a long-lived refresh token."""
    return _create_token(username, is_admin, "refresh", settings.REFRESH_TOKEN_TTL)


def decode_token(token, expected_type):
    """Decode and validate a JWT, enforcing the expected ``type`` claim."""
    try:
        payload = jwt.decode(token, settings.SECRET_KEY,
                             algorithms=[settings.JWT_ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid or expired token") from exc
    if payload.get("type") != expected_type:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Invalid token type")
    return payload


def set_auth_cookies(response: Response, username, is_admin):
    """Attach fresh access + refresh cookies to ``response``."""
    common = {
        "httponly": True,
        "secure": settings.COOKIE_SECURE,
        "samesite": settings.COOKIE_SAMESITE,
        "domain": settings.COOKIE_DOMAIN,
        "path": "/",
    }
    response.set_cookie(
        settings.ACCESS_COOKIE_NAME, create_access_token(username, is_admin),
        max_age=int(settings.ACCESS_TOKEN_TTL.total_seconds()), **common)
    response.set_cookie(
        settings.REFRESH_COOKIE_NAME, create_refresh_token(username, is_admin),
        max_age=int(settings.REFRESH_TOKEN_TTL.total_seconds()), **common)


def clear_auth_cookies(response: Response):
    """Remove the auth cookies (logout)."""
    for name in (settings.ACCESS_COOKIE_NAME, settings.REFRESH_COOKIE_NAME):
        response.delete_cookie(name, domain=settings.COOKIE_DOMAIN, path="/")


def get_current_user(request: Request) -> CurrentUser:
    """FastAPI dependency: resolve the authenticated user from the access cookie."""
    token = request.cookies.get(settings.ACCESS_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="Not authenticated")
    payload = decode_token(token, "access")
    user_data = get_user(get_global_engine(), payload["sub"])
    if user_data is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED,
                            detail="User no longer exists")
    return CurrentUser(user_data)


def require_admin(user: CurrentUser = Depends(get_current_user)) -> CurrentUser:
    """FastAPI dependency: require the authenticated user to be an admin."""
    if not user.is_admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN,
                            detail="You do not have admin access.")
    return user
