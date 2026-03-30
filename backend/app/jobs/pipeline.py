"""Pipeline job executor: per-patient search + classify with savepoints (Decision #31)."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.models import Annotation, ReviewStatus
from app.config import settings
from app.connectors.models import Note
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


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def execute_pipeline_run(
    pipeline_run_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Process patients for a pipeline run.

    Per patient:
    1. Load notes
    2. Run deterministic search → Evidence records
    3. If matches: classify_patient() → single LLM call
    4. Create Annotation with classification result
    5. Update PatientTask status

    Uses savepoints per patient (Decision #31) so failures don't corrupt
    other patients' data.
    """
    if session_factory is None:
        session_factory = _make_session_factory()

    stats = {
        "patients_processed": 0,
        "patients_matched": 0,
        "patients_no_match": 0,
        "patients_failed": 0,
        "total_evidence": 0,
        "annotations_created": 0,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    async with session_factory() as session:
        run = await session.get(PipelineRun, pipeline_run_id)
        if not run:
            logger.error("PipelineRun %s not found", pipeline_run_id)
            return {"error": "Run not found"}

        run.status = PipelineRunStatus.RUNNING
        run.updated_at = datetime.now(UTC)
        session.add(run)
        await session.commit()

        config = run.config_snapshot
        keywords = config.get("search_patterns", {}).get("keywords", [])
        regex_patterns = config.get("search_patterns", {}).get("regex_patterns", [])
        exclusion_patterns = config.get("search_patterns", {}).get("exclusion_patterns", [])

        try:
            # Get all queued tasks for this run
            stmt = (
                select(PatientTask)
                .where(
                    PatientTask.pipeline_run_id == pipeline_run_id,
                    PatientTask.status == PatientTaskStatus.QUEUED,
                )
                .order_by(PatientTask.id)
            )
            result = await session.execute(stmt)
            tasks = list(result.scalars().all())

            for task in tasks:
                # Check cancellation
                await session.refresh(run)
                if run.is_cancelled:
                    run.status = PipelineRunStatus.CANCELLED
                    run.updated_at = datetime.now(UTC)
                    run.result_summary = stats
                    session.add(run)
                    await session.commit()
                    return stats

                # Savepoint per patient (Decision #31)
                try:
                    async with session.begin_nested():
                        task.transition_status(PatientTaskStatus.PROCESSING)
                        task.started_at = datetime.now(UTC)
                        session.add(task)
                        await session.flush()

                        # Load patient notes
                        note_stmt = select(Note).where(
                            Note.patient_id == task.patient_id,
                            Note.project_id == run.project_id,
                            Note.deleted_at.is_(None),
                        )
                        note_result = await session.execute(note_stmt)
                        notes = list(note_result.scalars().all())

                        # Deterministic search
                        matches = search_patient_notes(
                            notes, keywords, regex_patterns, exclusion_patterns,
                        )

                        if not matches:
                            task.transition_status(PatientTaskStatus.NO_MATCH)
                            task.completed_at = datetime.now(UTC)
                            session.add(task)
                            stats["patients_no_match"] += 1
                        else:
                            # Store evidence
                            for m in matches:
                                ev = Evidence(
                                    patient_task_id=task.id,
                                    note_id=m.note_id,
                                    matched_text=m.matched_text,
                                    match_start=m.start_pos,
                                    match_end=m.end_pos,
                                    match_source=m.match_source,
                                    match_pattern=m.match_pattern,
                                )
                                session.add(ev)
                                stats["total_evidence"] += 1

                            # Classify patient (single LLM call)
                            excerpts = [
                                {"note_id": m.note_id, "text": m.matched_text}
                                for m in matches
                            ]

                            # Build a config-like object for the classifier
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

                            classification = await classify_patient(excerpts, proxy)

                            # Create annotation
                            annotation = Annotation(
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
                            )
                            session.add(annotation)
                            stats["annotations_created"] += 1
                            stats["patients_matched"] += 1

                            if classification.token_usage:
                                for k in ("prompt_tokens", "completion_tokens", "total_tokens"):
                                    stats["token_usage"][k] += classification.token_usage.get(k, 0)

                            task.transition_status(PatientTaskStatus.COMPLETED)
                            task.completed_at = datetime.now(UTC)
                            session.add(task)

                except Exception as exc:
                    logger.warning(
                        "Patient %s failed in run %s: %s",
                        task.patient_id, pipeline_run_id, exc,
                    )
                    # Savepoint rolled back — re-fetch task
                    await session.refresh(task)
                    task.status = PatientTaskStatus.FAILED
                    task.error_message = str(exc)[:1000]
                    task.completed_at = datetime.now(UTC)
                    session.add(task)
                    stats["patients_failed"] += 1

                await session.commit()
                stats["patients_processed"] += 1

                # Update run progress
                run.processed_patients = stats["patients_processed"]
                run.failed_patients = stats["patients_failed"]
                run.result_summary = stats
                run.updated_at = datetime.now(UTC)
                session.add(run)
                await session.commit()

            # Final status
            if stats["patients_failed"] > 0 and stats["patients_matched"] == 0 and stats["patients_no_match"] == 0:
                run.status = PipelineRunStatus.FAILED
            else:
                run.status = PipelineRunStatus.COMPLETED
            run.result_summary = stats
            run.updated_at = datetime.now(UTC)

        except Exception as exc:
            logger.exception("Pipeline run %s failed", pipeline_run_id)
            run.status = PipelineRunStatus.FAILED
            run.result_summary = stats

        session.add(run)
        await session.commit()
        return stats
