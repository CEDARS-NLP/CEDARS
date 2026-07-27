"""Internal-processes API (platform-admin only), scoped per project."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.admin.router import require_platform_admin
from app.admin.service import get_queue_stats, get_worker_info
from app.auth.models import User
from app.common.database import get_session
from app.workflow import internal_service
from app.workflow.schemas import NlpRunResponse, SimpleJobResponse

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/workflow/internal",
    tags=["workflow-internal"],
)


@router.get("/queues")
async def queue_status(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Queue + worker status (v1 internal processes RQ dashboard)."""
    queues = await get_queue_stats(session)
    workers = await get_worker_info()
    return {"queues": queues, "workers": workers}


@router.post("/unlock-all", response_model=SimpleJobResponse)
async def unlock_all(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Unlock every patient in the project (v1 ``unlock_all_patients``)."""
    affected = await internal_service.unlock_all_patients(session, project_id)
    return SimpleJobResponse(status="ok", detail="Patients unlocked", affected=affected)


@router.post("/unlock/{patient_id}", response_model=SimpleJobResponse)
async def unlock_one(
    project_id: str,
    patient_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Unlock a single patient (v1 ``unlock_patient``)."""
    await internal_service.unlock_patient(session, project_id, patient_id)
    return SimpleJobResponse(status="ok", detail=f"Patient {patient_id} unlocked")


@router.post("/rebuild-results", response_model=SimpleJobResponse)
async def rebuild_results(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Rebuild the results table (v1 ``update_results_collection``)."""
    affected = await internal_service.rebuild_results(session, project_id)
    return SimpleJobResponse(status="ok", detail="Results rebuilt", affected=affected)


@router.post("/rerun-nlp", response_model=NlpRunResponse)
async def rerun_nlp(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    admin: User = Depends(require_platform_admin()),
):
    """Clear annotations and re-run NLP for the project."""
    dispatched, mode = await internal_service.rerun_nlp(session, project_id, admin.id)
    return NlpRunResponse(dispatched_patients=dispatched, mode=mode)


@router.post("/drop-data", response_model=SimpleJobResponse)
async def drop_data(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Delete all workflow data for the project (destructive reset)."""
    await internal_service.drop_project_data(session, project_id)
    return SimpleJobResponse(status="ok", detail="Project data cleared")
