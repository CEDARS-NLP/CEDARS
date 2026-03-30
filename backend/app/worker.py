"""ARQ worker configuration.

Run with: arq app.worker.WorkerSettings
"""

import logging
from urllib.parse import urlparse

from arq.connections import RedisSettings

from app.config import settings

# Import ALL models at worker startup so SQLAlchemy can resolve foreign keys.
# The ARQ worker runs in a separate process without the FastAPI app context.
import app.auth.models  # noqa: F401
import app.projects.models  # noqa: F401
import app.connectors.models  # noqa: F401
import app.nlp.models  # noqa: F401
import app.annotations.models  # noqa: F401
import app.pipeline.models  # noqa: F401
import app.evaluation.models  # noqa: F401  # Phase 1: unified eval models

logger = logging.getLogger(__name__)


def parse_redis_settings() -> RedisSettings:
    """Parse CEDARS redis_url into ARQ RedisSettings."""
    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


async def run_nlp_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run NLP pipeline for a project."""
    from app.jobs.nlp import execute_nlp_job

    return await execute_nlp_job(project_id, job_db_id)


async def run_prediction_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run bulk predictions with per-patient batching."""
    from app.jobs.prediction import execute_prediction_job

    return await execute_prediction_job(project_id, job_db_id)


async def run_ingestion_job(ctx: dict, project_id: str, job_db_id: str, data_source_id: str) -> dict:
    """ARQ task: run data ingestion for a data source."""
    from app.jobs.ingestion import execute_ingestion_job

    return await execute_ingestion_job(project_id, job_db_id, data_source_id)


async def run_export_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: generate export. (Placeholder)"""
    return {"status": "not_implemented"}


async def run_pipeline_job(ctx: dict, pipeline_run_id: str) -> dict:
    """ARQ task: execute a pipeline run (search + classify per patient)."""
    from app.jobs.pipeline import execute_pipeline_run

    return await execute_pipeline_run(pipeline_run_id)


async def run_eval_pipeline_job(ctx: dict, run_id: str) -> dict:
    """Execute a full pipeline run for a committed evaluation session.

    Uses PatientResult rows instead of PatientTask. Reuses the same
    search + classify logic but stores results in the new schema.
    """
    from app.common.database import async_session
    from app.evaluation.models import EvaluationSession, PatientResult, PatientResultStatus
    from app.pipeline.models import PipelineRun, PipelineRunStatus
    from app.connectors.models import Note
    from app.nlp.engine import parse_query, process_note
    from app.pipeline.classifier import classify_patient
    from sqlalchemy import select
    from datetime import UTC, datetime
    import logging

    logger = logging.getLogger(__name__)

    async with async_session() as db:
        run = await db.get(PipelineRun, run_id)
        if not run:
            return {"error": "Run not found"}

        run.status = PipelineRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        db.add(run)
        await db.commit()

        config = run.config_snapshot or {}

        # Find the evaluation session linked to this run
        stmt = select(PatientResult.session_id).where(
            PatientResult.pipeline_run_id == run_id,
        ).limit(1)
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            run.status = PipelineRunStatus.FAILED
            db.add(run)
            await db.commit()
            return {"error": "No PatientResult rows found"}

        session_id = row[0]
        eval_session = await db.get(EvaluationSession, session_id)
        if not eval_session:
            run.status = PipelineRunStatus.FAILED
            db.add(run)
            await db.commit()
            return {"error": "Evaluation session not found"}

        # Parse search queries from config
        search_queries = config.get("search_queries", [])
        include_queries = []
        exclude_queries = []
        for q in search_queries:
            query_str = q.get("query", "")
            if q.get("type") == "exclude":
                exclude_queries.append(query_str)
            else:
                include_queries.append(query_str)

        # Build classifier config
        class _Config:
            pass

        classifier_config = _Config()
        classifier_config.name = config.get("event_name", "")
        classifier_config.description = config.get("event_description", "")
        classifier_config.include_criteria = config.get("include_criteria", "")
        classifier_config.exclude_criteria = config.get("exclude_criteria", "")
        classifier_config.llm_provider = config.get("llm_provider", "")
        classifier_config.llm_model = config.get("llm_model", "")
        classifier_config.llm_api_base = config.get("llm_api_base")

        # Process queued patients
        processed = 0
        failed = 0

        while True:
            if run.is_cancelled:
                break

            # Pick next queued patient
            stmt = select(PatientResult).where(
                PatientResult.pipeline_run_id == run_id,
                PatientResult.status == PatientResultStatus.QUEUED,
            ).limit(1)
            result = await db.execute(stmt)
            pr = result.scalar_one_or_none()
            if not pr:
                break

            pr.status = PatientResultStatus.PROCESSING
            pr.started_at = datetime.now(UTC)
            db.add(pr)
            await db.commit()

            try:
                # Get patient notes
                stmt = select(Note).where(
                    Note.patient_id == pr.patient_id,
                    Note.text.isnot(None),
                ).order_by(Note.note_date)
                result = await db.execute(stmt)
                notes = list(result.scalars().all())

                pr.notes_searched = len(notes)

                # Run search queries on notes
                matched_notes = []
                for note in notes:
                    is_matched = False
                    for query_str in include_queries:
                        query_groups = parse_query(query_str)
                        sentences = process_note(note.text, query_groups)
                        if any(s.get("is_target") or s.get("matched_tokens") for s in sentences):
                            is_matched = True
                            break

                    # Check exclude queries
                    if is_matched:
                        for query_str in exclude_queries:
                            query_groups = parse_query(query_str)
                            sentences = process_note(note.text, query_groups)
                            if any(s.get("matched_tokens") for s in sentences):
                                is_matched = False
                                break

                    if is_matched:
                        matched_notes.append(note)

                pr.notes_matched = len(matched_notes)

                if not matched_notes:
                    pr.status = PatientResultStatus.NO_MATCH
                    pr.finding_label = "no_match"
                    pr.completed_at = datetime.now(UTC)
                else:
                    # Classify with LLM
                    excerpts = [
                        {
                            "note_id": n.id,
                            "text": n.text,
                            "note_date": str(n.note_date) if n.note_date else "unknown",
                        }
                        for n in matched_notes
                    ]
                    classification = await classify_patient(excerpts, classifier_config)

                    pr.finding_label = classification.label
                    pr.finding_reasoning = classification.reasoning
                    pr.finding_evidence = classification.evidence or []
                    pr.event_date = classification.event_date
                    pr.predicted_score = classification.confidence
                    pr.token_usage = classification.token_usage
                    pr.status = PatientResultStatus.COMPLETED
                    pr.completed_at = datetime.now(UTC)

                processed += 1

            except Exception as e:
                pr.status = PatientResultStatus.FAILED
                pr.error_message = str(e)
                pr.completed_at = datetime.now(UTC)
                failed += 1
                logger.warning("Eval pipeline failed for patient %s: %s", pr.patient_id, e)

            db.add(pr)

            # Update run progress
            run.processed_patients = processed + failed
            run.failed_patients = failed
            db.add(run)
            await db.commit()

            # Re-check cancellation
            await db.refresh(run)

        # Finalize
        from app.evaluation.models import SessionStatus
        if run.is_cancelled:
            run.status = PipelineRunStatus.CANCELLED
        else:
            run.status = PipelineRunStatus.COMPLETED
            eval_session.status = SessionStatus.COMPLETED
            db.add(eval_session)

        run.completed_at = datetime.now(UTC)
        db.add(run)
        await db.commit()

    return {"processed": processed, "failed": failed}


class WorkerSettings:
    functions = [run_nlp_job, run_prediction_job, run_ingestion_job, run_export_job, run_pipeline_job, run_eval_pipeline_job]
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
