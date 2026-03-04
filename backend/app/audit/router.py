"""API routes for audit log."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.audit.schemas import AuditLogResponse, PatientActivityResponse
from app.audit.service import get_patient_activity, query_audit_log

router = APIRouter(
    prefix="/api/v1/projects/{project_id}",
    tags=["audit"],
)


@router.get("/audit", response_model=AuditLogResponse)
async def query_audit_endpoint(
    project_id: str,
    patient_id: str | None = Query(None),
    user_id: str | None = Query(None),
    action: str | None = Query(None),
    since: datetime | None = Query(None),
    until: datetime | None = Query(None),
    limit: int = Query(50, le=200),
    offset: int = Query(0, ge=0),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Query audit log entries with filters. Admin only."""
    return await query_audit_log(
        session, project_id,
        patient_id=patient_id,
        user_id=user_id,
        action=action,
        since=since,
        until=until,
        limit=limit,
        offset=offset,
    )


@router.get("/patients/{patient_id}/activity", response_model=PatientActivityResponse)
async def patient_activity_endpoint(
    project_id: str,
    patient_id: str,
    limit: int = Query(100, le=500),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "annotator")),
):
    """Get activity timeline for a patient."""
    return await get_patient_activity(session, project_id, patient_id, limit=limit)
