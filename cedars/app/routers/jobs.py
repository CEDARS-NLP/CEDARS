"""Read APIs for project-local ARQ job history."""
from fastapi import APIRouter, Depends, Query

from ..database import get_current_project_engine
from ..database.db_overview import list_recent_jobs
from ..dependencies import ProjectContext, require_project
from ..schemas import BackgroundJobOut

router = APIRouter(prefix="/projects/{project_id}/jobs", tags=["jobs"])


def _job_out(job) -> BackgroundJobOut:
    return BackgroundJobOut(
        id=job.job_id,
        arq_job_id=job.arq_job_id,
        job_type=job.job_type,
        status=job.status,
        progress=job.progress,
        created_by=job.created_by,
        result_summary=job.result_summary,
        error_message=job.error_message,
        created_at=job.created_at,
        started_at=job.started_at,
        completed_at=job.completed_at,
    )


@router.get("", response_model=list[BackgroundJobOut])
def list_jobs(
    limit: int = Query(default=20, ge=1, le=100),
    _ctx: ProjectContext = Depends(require_project),
):
    """List recent durable jobs from the currently bound project database."""
    return [_job_out(job) for job in list_recent_jobs(get_current_project_engine(), limit)]