"""Admin API routes for queue monitoring and job management."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.common.database import get_session
from app.dependencies import get_current_user
from app.admin.schemas import JobListItem, QueuesResponse, WorkersResponse
from app.admin.service import get_queue_stats, get_worker_info, list_jobs

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_platform_admin():
    """Dependency that requires platform admin role."""

    async def dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role != UserRole.PLATFORM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admin required",
            )
        return current_user

    return dependency


@router.get("/queues", response_model=QueuesResponse)
async def queues_endpoint(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Get queue statistics."""
    stats = await get_queue_stats(session)
    return {"queues": stats}


@router.get("/workers", response_model=WorkersResponse)
async def workers_endpoint(
    _admin: User = Depends(require_platform_admin()),
):
    """Get active worker info."""
    workers = await get_worker_info()
    return {"workers": workers}


@router.get("/jobs", response_model=list[JobListItem])
async def list_jobs_endpoint(
    job_status: str | None = Query(None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """List background jobs."""
    jobs = await list_jobs(session, status=job_status, limit=limit, offset=offset)
    return jobs
