"""Shared FastAPI dependencies for authentication and authorization."""

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.auth.service import decode_token
from app.common.database import get_session


async def get_current_user(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> User:
    """Validate JWT from httpOnly cookie and return the authenticated user."""
    token = request.cookies.get("access_token")
    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated")
    payload = decode_token(token)
    if not payload or payload.get("type") != "access":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    user = await session.get(User, payload["sub"])
    if not user or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    return user


def require_project_role(*allowed_roles: str):
    """Return a dependency that checks the user has one of the allowed roles in the project.

    Platform admins bypass project role checks entirely.
    """

    async def dependency(
        project_id: str,
        current_user: User = Depends(get_current_user),
        session: AsyncSession = Depends(get_session),
    ) -> User:
        # Platform admins bypass project role checks
        if current_user.role == UserRole.PLATFORM_ADMIN:
            return current_user

        # Import here to avoid circular imports
        from app.projects.service import get_member

        member = await get_member(session, project_id, current_user.id)
        if not member or member.role.value not in allowed_roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return dependency
