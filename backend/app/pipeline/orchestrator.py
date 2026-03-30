"""Pipeline run orchestration: dispatch, cancel, retry, stats."""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import Patient
from app.pipeline.models import (
    EventConfig,
    PatientTask,
    PatientTaskStatus,
    PipelineRun,
    PipelineRunStatus,
)


async def _check_no_active_run(session: AsyncSession, event_config_id: str) -> None:
    """Reject if there's already an active run for this event config (Decision #35)."""
    stmt = select(PipelineRun).where(
        PipelineRun.event_config_id == event_config_id,
        PipelineRun.status.in_([PipelineRunStatus.QUEUED, PipelineRunStatus.RUNNING]),
        PipelineRun.is_cancelled == False,  # noqa: E712
    )
    result = await session.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("An active pipeline run already exists for this event config")


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
    await session.refresh(run)
    return run


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
    """Get aggregated PatientTask status counts for a run."""
    stmt = (
        select(PatientTask.status, func.count())
        .where(PatientTask.pipeline_run_id == run_id)
        .group_by(PatientTask.status)
    )
    result = await session.execute(stmt)
    counts = {status.value: count for status, count in result.all()}
    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "no_match": counts.get("no_match", 0),
    }


async def list_tasks(
    session: AsyncSession,
    run_id: str,
    status_filter: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[PatientTask]:
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
    return list(result.scalars().all())
