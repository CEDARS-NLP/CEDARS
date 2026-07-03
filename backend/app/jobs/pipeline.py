"""Pipeline job executor: per-patient ARQ jobs with circuit breaker.

Architecture:
- run_pipeline_orchestrator: marks run as RUNNING, enqueues one job per patient,
  then monitors progress and applies circuit breaker logic.
- run_patient_task: processes a single patient (search + classify).
  Each patient is an independent ARQ message — visible in queue, individually
  retryable, and trackable.

Circuit breaker: after CIRCUIT_BREAKER_THRESHOLD consecutive failures, the
orchestrator cancels the run. This prevents burning LLM tokens on a
misconfigured event definition or a downed provider.
"""

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.models import Annotation, ReviewStatus
from app.common.utils import now_utc
from app.config import settings
from app.connectors.models import Note
from app.evaluation.models import EvaluationSession, PatientResult, SessionStatus
from app.pipeline.classifier import classify_patient
from app.pipeline.models import (
    Evidence,
    PatientTask,
    PatientTaskStatus,
    PipelineRun,
    PipelineRunStatus,
)
from app.pipeline.search import search_patient_notes

logger = logging.getLogger(__name__)

# Circuit breaker: cancel after this many consecutive patient failures.
CIRCUIT_BREAKER_THRESHOLD = 5
# How often the orchestrator polls for progress (seconds).
POLL_INTERVAL = 2


# ── Shared helpers ────────────────────────────────────────────────


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _sync_eval_session_status(
    db: AsyncSession, run_id: str, run_status: PipelineRunStatus
) -> None:
    """Update the EvaluationSession status when its pipeline run terminates."""
    stmt = (
        select(PatientResult.session_id)
        .where(PatientResult.pipeline_run_id == run_id)
        .distinct()
        .limit(1)
    )
    result = await db.execute(stmt)
    row = result.first()
    if not row or not row[0]:
        return

    eval_session = await db.get(EvaluationSession, row[0])
    if not eval_session or eval_session.status != SessionStatus.COMMITTED:
        return

    if run_status == PipelineRunStatus.COMPLETED:
        eval_session.status = SessionStatus.COMPLETED
    elif run_status in (PipelineRunStatus.CANCELLED, PipelineRunStatus.FAILED):
        eval_session.status = SessionStatus.DISCARDED
    else:
        return

    eval_session.updated_at = now_utc()
    db.add(eval_session)
    await db.commit()


# ── Per-patient job ───────────────────────────────────────────────


async def process_single_patient(
    pipeline_run_id: str,
    patient_task_id: int,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Process one patient: search notes → classify → create annotation.

    This is the unit of work per ARQ message. Returns a dict with outcome.
    """
    if session_factory is None:
        session_factory = _make_session_factory()

    async with session_factory() as db:
        task = await db.get(PatientTask, patient_task_id)
        if not task:
            return {"status": "error", "detail": "PatientTask not found"}

        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            return {"status": "error", "detail": "PipelineRun not found"}

        # Check cancellation before starting
        if run.is_cancelled:
            return {"status": "cancelled"}

        config = run.config_snapshot
        keywords = config.get("search_patterns", {}).get("keywords", [])
        regex_patterns = config.get("search_patterns", {}).get("regex_patterns", [])
        exclusion_patterns = config.get("search_patterns", {}).get("exclusion_patterns", [])

        # Use savepoint so failures don't corrupt the session
        try:
            async with db.begin_nested():
                task.transition_status(PatientTaskStatus.PROCESSING)
                task.started_at = now_utc()
                db.add(task)
                await db.flush()

                # Load patient notes
                note_stmt = select(Note).where(
                    Note.patient_id == task.patient_id,
                    Note.project_id == run.project_id,
                    Note.deleted_at.is_(None),
                )
                notes = list((await db.execute(note_stmt)).scalars().all())

                # Deterministic search
                matches = search_patient_notes(
                    notes, keywords, regex_patterns, exclusion_patterns,
                )

                if not matches:
                    task.transition_status(PatientTaskStatus.NO_MATCH)
                    task.completed_at = now_utc()
                    db.add(task)
                    await db.commit()
                    return {"status": "no_match", "patient_id": task.patient_id}

                # Store evidence
                for m in matches:
                    db.add(Evidence(
                        patient_task_id=task.id,
                        note_id=m.note_id,
                        text=m.matched_text,
                        start_pos=m.start_pos,
                        end_pos=m.end_pos,
                        match_source=m.match_source,
                        match_pattern=m.match_pattern,
                    ))

                # Classify patient (single LLM call — litellm handles transient retries)
                excerpts = [
                    {"note_id": m.note_id, "text": m.matched_text}
                    for m in matches
                ]

                class _ConfigProxy:
                    pass

                proxy = _ConfigProxy()
                proxy.name = config["name"]
                proxy.description = config["description"]
                proxy.include_criteria = config["include_criteria"]
                proxy.exclude_criteria = config["exclude_criteria"]
                proxy.llm_provider = config["llm_provider"]
                proxy.llm_model = config["llm_model"]
                proxy.llm_api_base = config.get("llm_api_base")
                proxy.llm_api_key = config.get("llm_api_key")

                classification = await classify_patient(excerpts, proxy)

                # Create annotation
                db.add(Annotation(
                    project_id=run.project_id,
                    patient_id=task.patient_id,
                    note_id=matches[0].note_id,
                    sentence_text="; ".join(m.matched_text for m in matches[:5]),
                    predicted_score=classification.confidence,
                    predicted_label=1 if classification.label == "positive" else 0,
                    predictor_model=config["llm_model"],
                    reasoning=classification.reasoning,
                    review_status=ReviewStatus.PENDING,
                    pipeline_run_id=run.id,
                    patient_task_id=task.id,
                    predicted_reasoning=classification.reasoning,
                ))

                task.transition_status(PatientTaskStatus.COMPLETED)
                task.completed_at = now_utc()
                db.add(task)

            await db.commit()
            return {
                "status": "completed",
                "patient_id": task.patient_id,
                "label": classification.label,
                "token_usage": classification.token_usage,
            }

        except Exception as exc:
            logger.warning(
                "Patient %s failed in run %s: %s",
                task.patient_id, pipeline_run_id, exc,
            )
            # Savepoint rolled back — update task status outside savepoint
            await db.refresh(task)
            task.status = PatientTaskStatus.FAILED
            task.error_message = str(exc)[:1000]
            task.completed_at = now_utc()
            db.add(task)
            await db.commit()
            return {
                "status": "failed",
                "patient_id": task.patient_id,
                "error": str(exc)[:500],
            }


# ── Orchestrator job ──────────────────────────────────────────────


async def execute_pipeline_run(
    pipeline_run_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Orchestrate a pipeline run: enqueue per-patient jobs, monitor, circuit-break.

    Flow:
    1. Mark run as RUNNING
    2. Enqueue one ARQ job per queued PatientTask
    3. Poll for completion, tracking consecutive failures
    4. If consecutive failures >= CIRCUIT_BREAKER_THRESHOLD, cancel remaining
    5. Finalize run status
    """
    if session_factory is None:
        session_factory = _make_session_factory()

    async with session_factory() as db:
        run = await db.get(PipelineRun, pipeline_run_id)
        if not run:
            logger.error("PipelineRun %s not found", pipeline_run_id)
            return {"error": "Run not found"}

        run.status = PipelineRunStatus.RUNNING
        run.updated_at = now_utc()
        db.add(run)
        await db.commit()

        # Get all queued tasks
        stmt = (
            select(PatientTask)
            .where(
                PatientTask.pipeline_run_id == pipeline_run_id,
                PatientTask.status == PatientTaskStatus.QUEUED,
            )
            .order_by(PatientTask.id)
        )
        tasks = list((await db.execute(stmt)).scalars().all())

        if not tasks:
            run.status = PipelineRunStatus.COMPLETED
            run.result_summary = {"patients_processed": 0}
            run.updated_at = now_utc()
            db.add(run)
            await db.commit()
            return {"patients_processed": 0}

        # Enqueue each patient as a separate ARQ job
        try:
            from arq import create_pool

            from app.worker import parse_redis_settings

            redis = await create_pool(parse_redis_settings())
            for task in tasks:
                await redis.enqueue_job(
                    "run_patient_task",
                    pipeline_run_id,
                    task.id,
                    _job_id=f"patient-{pipeline_run_id}-{task.id}",
                )
            await redis.aclose()
            logger.info(
                "Enqueued %d patient jobs for run %s", len(tasks), pipeline_run_id,
            )
        except Exception:
            logger.exception("Failed to enqueue patient jobs for run %s", pipeline_run_id)
            run.status = PipelineRunStatus.FAILED
            run.result_summary = {"error": "Failed to enqueue patient jobs"}
            run.updated_at = now_utc()
            db.add(run)
            await db.commit()
            return {"error": "Failed to enqueue patient jobs"}

        # Poll for completion with circuit breaker
        consecutive_failures = 0
        prev_failed = 0
        prev_done = 0

        while True:
            await asyncio.sleep(POLL_INTERVAL)

            # Refresh run to check cancellation
            await db.refresh(run)
            if run.is_cancelled:
                run.status = PipelineRunStatus.CANCELLED
                break

            # Get current stats
            stat_stmt = (
                select(PatientTask.status, func.count())
                .where(PatientTask.pipeline_run_id == pipeline_run_id)
                .group_by(PatientTask.status)
            )
            counts = {
                (s.value if hasattr(s, "value") else s): c
                for s, c in (await db.execute(stat_stmt)).all()
            }

            total = sum(counts.values())
            failed = counts.get("failed", 0)
            done = (
                counts.get("completed", 0)
                + failed
                + counts.get("no_match", 0)
            )

            # Update run progress
            run.processed_patients = done
            run.failed_patients = failed
            run.updated_at = now_utc()
            db.add(run)
            await db.commit()

            # Circuit breaker: track consecutive failures
            new_failures = failed - prev_failed
            new_successes = (done - failed) - (prev_done - prev_failed)
            if new_successes > 0:
                consecutive_failures = 0
            if new_failures > 0:
                consecutive_failures += new_failures
            prev_failed = failed
            prev_done = done

            if consecutive_failures >= CIRCUIT_BREAKER_THRESHOLD:
                logger.warning(
                    "Circuit breaker tripped for run %s: %d consecutive failures",
                    pipeline_run_id, consecutive_failures,
                )
                run.is_cancelled = True
                run.status = PipelineRunStatus.FAILED
                run.result_summary = {
                    "error": f"Circuit breaker: {consecutive_failures} consecutive failures",
                    "failed_count": failed,
                    "completed_count": counts.get("completed", 0),
                }
                db.add(run)
                await db.commit()
                break

            # All done?
            if done >= total:
                if failed > 0 and counts.get("completed", 0) == 0 and counts.get("no_match", 0) == 0:
                    run.status = PipelineRunStatus.FAILED
                else:
                    run.status = PipelineRunStatus.COMPLETED
                break

        # Build final stats
        final_stmt = (
            select(PatientTask.status, func.count())
            .where(PatientTask.pipeline_run_id == pipeline_run_id)
            .group_by(PatientTask.status)
        )
        final_counts = {
            (s.value if hasattr(s, "value") else s): c
            for s, c in (await db.execute(final_stmt)).all()
        }

        stats = {
            "patients_processed": sum(final_counts.values()),
            "patients_completed": final_counts.get("completed", 0),
            "patients_no_match": final_counts.get("no_match", 0),
            "patients_failed": final_counts.get("failed", 0),
            "patients_queued": final_counts.get("queued", 0),
            "patients_processing": final_counts.get("processing", 0),
        }

        run.result_summary = stats
        run.updated_at = now_utc()
        db.add(run)
        await db.commit()
        await _sync_eval_session_status(db, run.id, run.status)
        return stats
