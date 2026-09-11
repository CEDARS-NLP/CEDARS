"""Internal / technical admin routes (ported from Flask ``ops.internal_processes``).

Exposes the RQ dashboard URL + queue health, and the maintenance operations
(rebuild results, unlock all patients) plus a PINES availability check. All
operations are admin-only and project-scoped.
"""
from fastapi import APIRouter, Depends
from rq.registry import FailedJobRegistry, FinishedJobRegistry

from .. import ops_tasks, queues
from ..api import check_is_pines_available
from ..dependencies import ProjectContext, require_project_admin
from ..schemas import InternalStatusOut, PinesStatusOut, SimpleJobResponse

router = APIRouter(prefix="/projects/{project_id}/internal", tags=["internal"])


@router.get("", response_model=InternalStatusOut)
def internal_status(ctx: ProjectContext = Depends(require_project_admin)):
    """Return this project's dashboard URL and task-queue health counters."""
    queue = queues.get_task_queue(ctx.project_id)
    return InternalStatusOut(
        rq_dashboard_url=f"/api/v1/projects/{ctx.project_id}/rq/",
        queue_length=len(queue),
        failed_jobs=len(FailedJobRegistry(queue=queue)),
        successful_jobs=len(FinishedJobRegistry(queue=queue)),
    )


@router.post("/update_results", response_model=SimpleJobResponse)
def update_results(ctx: ProjectContext = Depends(require_project_admin)):
    """Rebuild the RESULTS collection (background)."""
    job = queues.get_ops_queue(ctx.project_id).enqueue(ops_tasks.update_patient_results,
                                                       ctx.project_id, True)
    return SimpleJobResponse(job_id=job.get_id(),
                             message="Rebuilding results collection.")


@router.post("/unlock_all", response_model=SimpleJobResponse)
def unlock_all(ctx: ProjectContext = Depends(require_project_admin)):
    """Unlock all patients in the project (background)."""
    job = queues.get_ops_queue(ctx.project_id).enqueue(ops_tasks.remove_all_locked, ctx.project_id)
    return SimpleJobResponse(job_id=job.get_id(), message="Unlocking all patients.")



@router.get("/pines/status", response_model=PinesStatusOut)
def pines_status(_ctx: ProjectContext = Depends(require_project_admin)):
    """Report whether the PINES model server is reachable."""
    try:
        available = bool(check_is_pines_available())
    except Exception:  # noqa: BLE001 - unavailable/unreachable PINES is a normal state
        available = False
    return PinesStatusOut(available=available)
