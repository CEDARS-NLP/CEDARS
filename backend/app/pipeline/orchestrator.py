"""Pipeline run orchestration: dispatch, cancel, retry, stats."""

import logging
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.connectors.models import Patient
from app.evaluation.models import EvaluationSession, PatientResult, SessionStatus
from app.pipeline.models import (
    EventConfig,
    PatientTask,
    PatientTaskStatus,
    PipelineRun,
    PipelineRunStatus,
)

logger = logging.getLogger(__name__)

# True when running against PostgreSQL (supports SELECT FOR UPDATE).
_USE_DB_LOCKING = "sqlite" not in settings.database_url


async def _check_no_active_run(session: AsyncSession, event_config_id: str) -> None:
    """Reject if there's already an active run for this event config (Decision #35).

    Uses SELECT FOR UPDATE on PostgreSQL to close the TOCTOU race window between
    the existence check and the new run insert.
    """
    stmt = select(PipelineRun).where(
        PipelineRun.event_config_id == event_config_id,
        PipelineRun.status.in_([PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING]),
        PipelineRun.is_cancelled == False,  # noqa: E712
    )
    if _USE_DB_LOCKING:
        stmt = stmt.with_for_update()
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("An active pipeline run already exists for this event config")


async def _enqueue_pipeline_run(run_id: str) -> None:
    """Enqueue a pipeline run to the ARQ worker queue."""
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        await redis.enqueue_job("run_pipeline_job", run_id)
        await redis.aclose()
        logger.info("Enqueued pipeline run %s to ARQ", run_id)
    except Exception:
        logger.exception("Failed to enqueue pipeline run %s — no worker will pick it up", run_id)


async def dispatch_sample_run(
    session: AsyncSession,
    project_id: str,
    event_config_id: str,
    user_id: str,
    sample_size: int = 10,
) -> PipelineRun:
    """Create a sample pipeline run with random patient selection."""
    ec = await session.get(EventConfig, event_config_id)
    if not ec or ec.project_id != project_id or ec.deleted_at is not None:
        raise ValueError("EventConfig not found")

    await _check_no_active_run(session, event_config_id)

    # Get random sample of patients
    stmt = (
        select(Patient.id)
        .where(Patient.project_id == project_id, Patient.deleted_at.is_(None))
        .order_by(func.random())
        .limit(sample_size)
    )
    result = await session.execute(stmt)
    patient_ids = [row[0] for row in result.all()]

    if not patient_ids:
        raise ValueError("No patients available for sampling")

    config_snapshot = {
        "name": ec.name,
        "description": ec.description,
        "include_criteria": ec.include_criteria,
        "exclude_criteria": ec.exclude_criteria,
        "search_patterns": ec.search_patterns,
        "llm_provider": ec.llm_provider,
        "llm_model": ec.llm_model,
        "llm_api_base": ec.llm_api_base,
        "llm_api_key": ec.llm_api_key,
    }

    run = PipelineRun(
        project_id=project_id,
        event_config_id=event_config_id,
        run_type="sample",
        status=PipelineRunStatus.QUEUED,
        config_snapshot=config_snapshot,
        sample_size=sample_size,
        total_patients=len(patient_ids),
        created_by=user_id,
        snapshot_version=ec.version if hasattr(ec, "version") else 1,
    )
    session.add(run)
    await session.flush()  # get run.id

    for pid in patient_ids:
        task = PatientTask(
            pipeline_run_id=run.id,
            patient_id=pid,
            status=PatientTaskStatus.QUEUED,
        )
        session.add(task)

    await session.commit()
    await session.refresh(run)
    await _enqueue_pipeline_run(run.id)
    return run


async def dispatch_full_run(
    session: AsyncSession,
    project_id: str,
    event_config_id: str,
    user_id: str,
) -> PipelineRun:
    """Create a full pipeline run. Requires committed config."""
    ec = await session.get(EventConfig, event_config_id)
    if not ec or ec.project_id != project_id or ec.deleted_at is not None:
        raise ValueError("EventConfig not found")
    if not ec.is_committed:
        raise ValueError("EventConfig must be committed before running a full pipeline")

    await _check_no_active_run(session, event_config_id)

    # All patients not already processed by this event config
    already_processed = (
        select(PatientTask.patient_id)
        .join(PipelineRun, PatientTask.pipeline_run_id == PipelineRun.id)
        .where(
            PipelineRun.event_config_id == event_config_id,
            PatientTask.status.in_([PatientTaskStatus.COMPLETED, PatientTaskStatus.NO_MATCH]),
        )
        .scalar_subquery()
    )
    stmt = select(Patient.id).where(
        Patient.project_id == project_id,
        Patient.deleted_at.is_(None),
        Patient.id.notin_(already_processed),
    )
    result = await session.execute(stmt)
    patient_ids = [row[0] for row in result.all()]

    if not patient_ids:
        raise ValueError("No unprocessed patients available")

    config_snapshot = {
        "name": ec.name,
        "description": ec.description,
        "include_criteria": ec.include_criteria,
        "exclude_criteria": ec.exclude_criteria,
        "search_patterns": ec.search_patterns,
        "llm_provider": ec.llm_provider,
        "llm_model": ec.llm_model,
        "llm_api_base": ec.llm_api_base,
        "llm_api_key": ec.llm_api_key,
        "confidence_threshold": ec.confidence_threshold,
    }

    run = PipelineRun(
        project_id=project_id,
        event_config_id=event_config_id,
        run_type="full",
        status=PipelineRunStatus.QUEUED,
        config_snapshot=config_snapshot,
        total_patients=len(patient_ids),
        created_by=user_id,
        snapshot_version=ec.version if hasattr(ec, "version") else 1,
    )
    session.add(run)
    await session.flush()

    for pid in patient_ids:
        task = PatientTask(
            pipeline_run_id=run.id,
            patient_id=pid,
            status=PatientTaskStatus.QUEUED,
        )
        session.add(task)

    await session.commit()
    await session.refresh(run)
    await _enqueue_pipeline_run(run.id)
    return run


async def cancel_run(
    session: AsyncSession, project_id: str, run_id: str
) -> PipelineRun | None:
    """Cancel a pipeline run."""
    run = await session.get(PipelineRun, run_id)
    if not run or run.project_id != project_id:
        return None
    if run.status in (PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED):
        raise ValueError("Cannot cancel a completed/failed run")
    run.is_cancelled = True
    run.status = PipelineRunStatus.CANCELLED
    run.updated_at = datetime.now(UTC)
    session.add(run)
    await session.commit()

    # Sync evaluation session status if this run is linked to one
    stmt = (
        select(PatientResult.session_id)
        .where(PatientResult.pipeline_run_id == run_id)
        .distinct()
        .limit(1)
    )
    result = await session.execute(stmt)
    row = result.first()
    if row and row[0]:
        eval_session = await session.get(EvaluationSession, row[0])
        if eval_session and eval_session.status == SessionStatus.COMMITTED:
            eval_session.status = SessionStatus.DISCARDED
            eval_session.updated_at = datetime.now(UTC)
            session.add(eval_session)
            await session.commit()

    await session.refresh(run)
    return run


async def rerun(
    session: AsyncSession, project_id: str, run_id: str, user_id: str,
) -> PipelineRun:
    """Clone a terminal pipeline run and re-dispatch with the same config and patients.

    Detects whether this is a standard pipeline run (PatientTask) or an eval
    pipeline run (PatientResult) and dispatches accordingly.
    """
    old_run = await session.get(PipelineRun, run_id)
    if not old_run or old_run.project_id != project_id:
        raise ValueError("Pipeline run not found")
    if old_run.status in (PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING):
        raise ValueError("Cannot rerun an active pipeline run")

    await _check_no_active_run(session, old_run.event_config_id)

    # Check if this is an eval pipeline run (has PatientResult rows)
    eval_check = await session.execute(
        select(PatientResult.session_id)
        .where(PatientResult.pipeline_run_id == run_id)
        .limit(1)
    )
    eval_row = eval_check.first()

    if eval_row:
        # Delegate to eval service rerun
        from app.evaluation.service import rerun_pipeline

        result = await rerun_pipeline(session, eval_row[0], project_id, user_id)
        new_run = await session.get(PipelineRun, result["run_id"])
        if not new_run:
            raise ValueError("Failed to create rerun")
        return new_run

    # Standard pipeline run — clone with PatientTask rows
    stmt = select(PatientTask.patient_id).where(
        PatientTask.pipeline_run_id == run_id
    )
    result = await session.execute(stmt)
    patient_ids = [row[0] for row in result.all()]

    if not patient_ids:
        raise ValueError("Original run has no patient tasks to rerun")

    new_run = PipelineRun(
        project_id=project_id,
        event_config_id=old_run.event_config_id,
        run_type=old_run.run_type,
        status=PipelineRunStatus.QUEUED,
        config_snapshot=old_run.config_snapshot,
        sample_size=old_run.sample_size,
        total_patients=len(patient_ids),
        created_by=user_id,
        snapshot_version=old_run.snapshot_version,
    )
    session.add(new_run)
    await session.flush()

    for pid in patient_ids:
        session.add(PatientTask(
            pipeline_run_id=new_run.id,
            patient_id=pid,
            status=PatientTaskStatus.QUEUED,
        ))

    await session.commit()
    await session.refresh(new_run)
    await _enqueue_pipeline_run(new_run.id)
    return new_run


async def retry_failed(
    session: AsyncSession, project_id: str, run_id: str
) -> PipelineRun | None:
    """Re-queue failed patient tasks for a run."""
    run = await session.get(PipelineRun, run_id)
    if not run or run.project_id != project_id:
        return None

    stmt = select(PatientTask).where(
        PatientTask.pipeline_run_id == run_id,
        PatientTask.status == PatientTaskStatus.FAILED,
    )
    result = await session.execute(stmt)
    failed_tasks = result.scalars().all()

    if not failed_tasks:
        raise ValueError("No failed tasks to retry")

    for task in failed_tasks:
        task.transition_status(PatientTaskStatus.QUEUED)
        task.error_message = None
        task.started_at = None
        task.completed_at = None
        session.add(task)

    run.status = PipelineRunStatus.QUEUED
    run.is_cancelled = False
    run.updated_at = datetime.now(UTC)
    session.add(run)
    await session.commit()
    await session.refresh(run)
    await _enqueue_pipeline_run(run.id)
    return run


async def get_run(
    session: AsyncSession, project_id: str, run_id: str
) -> PipelineRun | None:
    run = await session.get(PipelineRun, run_id)
    if not run or run.project_id != project_id:
        return None
    return run


async def list_runs(
    session: AsyncSession, project_id: str, event_config_id: str | None = None
) -> list[PipelineRun]:
    stmt = (
        select(PipelineRun)
        .where(PipelineRun.project_id == project_id)
        .order_by(PipelineRun.created_at.desc())
    )
    if event_config_id:
        stmt = stmt.where(PipelineRun.event_config_id == event_config_id)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_run_stats(session: AsyncSession, run_id: str) -> dict:
    """Get aggregated status counts for a run.

    Checks PatientTask first (standard pipeline runs), then falls back to
    PatientResult (evaluation-session pipeline runs).
    """
    stmt = (
        select(PatientTask.status, func.count())
        .where(PatientTask.pipeline_run_id == run_id)
        .group_by(PatientTask.status)
    )
    result = await session.execute(stmt)
    # Postgres returns the enum column as a plain str; SQLite (tests) returns the
    # enum member. Handle both so .value isn't called on a str.
    counts = {
        (status.value if hasattr(status, "value") else status): count
        for status, count in result.all()
    }

    # Eval-session runs use PatientResult instead of PatientTask
    if not counts:
        from app.evaluation.models import PatientResult

        stmt = (
            select(PatientResult.status, func.count())
            .where(PatientResult.pipeline_run_id == run_id)
            .group_by(PatientResult.status)
        )
        result = await session.execute(stmt)
        counts = {
            (status.value if hasattr(status, "value") else status): count
            for status, count in result.all()
        }

    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "no_match": counts.get("no_match", 0),
    }


async def retry_stalled(
    session: AsyncSession, project_id: str, run_id: str, stale_minutes: int = 10
) -> int:
    """Re-queue patient tasks stuck in 'processing' for too long."""
    run = await session.get(PipelineRun, run_id)
    if not run or run.project_id != project_id:
        raise ValueError("Pipeline run not found")

    cutoff = datetime.now(UTC) - __import__("datetime").timedelta(minutes=stale_minutes)
    stmt = select(PatientTask).where(
        PatientTask.pipeline_run_id == run_id,
        PatientTask.status == PatientTaskStatus.PROCESSING,
        PatientTask.started_at < cutoff,
    )
    result = await session.execute(stmt)
    stalled = list(result.scalars().all())

    for task in stalled:
        task.status = PatientTaskStatus.QUEUED
        task.started_at = None
        task.error_message = "Re-queued: stalled in processing"
        session.add(task)

    if stalled:
        await session.commit()
    return len(stalled)


async def list_tasks(
    session: AsyncSession,
    run_id: str,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list:
    stmt = (
        select(PatientTask)
        .where(PatientTask.pipeline_run_id == run_id)
        .order_by(PatientTask.id)
        .limit(limit)
        .offset(offset)
    )
    if status_filter:
        stmt = stmt.where(PatientTask.status == status_filter)
    result = await session.execute(stmt)
    tasks = list(result.scalars().all())

    # Eval-session runs use PatientResult instead of PatientTask
    if not tasks:
        from app.evaluation.models import PatientResult

        stmt = (
            select(PatientResult)
            .where(PatientResult.pipeline_run_id == run_id)
            .order_by(PatientResult.id)
            .limit(limit)
            .offset(offset)
        )
        if status_filter:
            stmt = stmt.where(PatientResult.status == status_filter)
        result = await session.execute(stmt)
        tasks = list(result.scalars().all())

    return tasks


async def get_queue_overview(session: AsyncSession, project_id: str) -> dict:
    """Get queue overview: pipeline run counts + background job counts + worker status."""
    from app.jobs.models import BackgroundJob

    # Pipeline run status counts
    stmt = (
        select(PipelineRun.status, func.count())
        .where(PipelineRun.project_id == project_id)
        .group_by(PipelineRun.status)
    )
    result = await session.execute(stmt)
    run_counts = {
        (s.value if hasattr(s, "value") else s): c for s, c in result.all()
    }

    # Background job status counts
    stmt = (
        select(BackgroundJob.status, func.count())
        .where(BackgroundJob.project_id == project_id)
        .group_by(BackgroundJob.status)
    )
    result = await session.execute(stmt)
    job_counts = {
        (s.value if hasattr(s, "value") else s): c for s, c in result.all()
    }

    # Worker health — ARQ stores a health-check key that expires after
    # health_check_interval + 1 seconds (default key: "arq:queue:health-check")
    worker_active = False
    arq_queued = 0
    try:
        from arq import create_pool
        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        health = await redis.get("arq:queue:health-check")
        worker_active = health is not None
        # Count queued ARQ jobs
        arq_queued = await redis.zcard(redis.default_queue_name)
        await redis.aclose()
    except Exception:
        # Redis/ARQ health probe failed — surface it rather than silently
        # reporting worker_active=False (which hides infra outages from ops).
        logger.warning("ARQ/Redis health probe failed", exc_info=True)

    return {
        "pipeline_runs": {
            "queued": run_counts.get("queued", 0),
            "running": run_counts.get("running", 0),
            "completed": run_counts.get("completed", 0),
            "failed": run_counts.get("failed", 0),
            "cancelled": run_counts.get("cancelled", 0),
        },
        "background_jobs": {
            "pending": job_counts.get("pending", 0),
            "running": job_counts.get("running", 0),
            "completed": job_counts.get("completed", 0),
            "failed": job_counts.get("failed", 0),
        },
        "worker_active": worker_active,
        "arq_queued": arq_queued,
    }
