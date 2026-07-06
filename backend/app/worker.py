"""ARQ worker configuration.

Run with: arq app.worker.WorkerSettings
"""

import logging
from urllib.parse import urlparse

from arq.connections import RedisSettings

import app.annotations.models  # noqa: F401

# Import ALL models at worker startup so SQLAlchemy can resolve foreign keys.
# The ARQ worker runs in a separate process without the FastAPI app context.
import app.auth.models  # noqa: F401
import app.connectors.models  # noqa: F401
import app.evaluation.models  # noqa: F401  # Phase 1: unified eval models
import app.nlp.models  # noqa: F401
import app.pipeline.models  # noqa: F401
import app.projects.models  # noqa: F401
from app.common.utils import now_utc
from app.config import settings

logger = logging.getLogger(__name__)

# Row-level locking (FOR UPDATE SKIP LOCKED) is a PostgreSQL feature; SQLite
# (tests) ignores/rejects it. Mirror the guard used in pipeline/orchestrator.py
# and evaluation/service.py so the same code path is safe on both backends.
_USE_DB_LOCKING = "sqlite" not in settings.database_url


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
    """ARQ task: orchestrate a pipeline run — enqueues per-patient jobs, monitors, circuit-breaks."""
    from app.jobs.pipeline import execute_pipeline_run

    return await execute_pipeline_run(pipeline_run_id)


async def run_patient_task(ctx: dict, pipeline_run_id: str, patient_task_id: int) -> dict:
    """ARQ task: process a single patient (search + classify). One message per patient."""
    from app.jobs.pipeline import process_single_patient

    return await process_single_patient(pipeline_run_id, patient_task_id)


async def run_sample_llm_job(ctx: dict, session_id: str, project_id: str) -> dict:
    """ARQ task: run LLM classification on matched patients in an evaluation sample."""
    from app.evaluation.service import execute_sample_llm

    return await execute_sample_llm(session_id, project_id)


async def run_eval_pipeline_job(ctx: dict, run_id: str) -> dict:
    """Execute a full pipeline run for a committed evaluation session.

    Uses PatientResult rows instead of PatientTask. Reuses the same
    search + classify logic but stores results in the new schema.
    """
    import logging

    from sqlalchemy import select

    from app.common.database import async_session
    from app.connectors.models import Note
    from app.evaluation.models import EvaluationSession, PatientResult, PatientResultStatus
    from app.nlp.engine import parse_query, process_note
    from app.pipeline.classifier import classify_patient
    from app.pipeline.models import PipelineRun, PipelineRunStatus

    logger = logging.getLogger(__name__)

    async with async_session() as db:
        run = await db.get(PipelineRun, run_id)
        if not run:
            return {"error": "Run not found"}

        run.status = PipelineRunStatus.RUNNING
        run.started_at = now_utc()
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
        classifier_config.llm_api_key = config.get("llm_api_key")

        # Process queued patients
        processed = 0
        failed = 0

        while True:
            if run.is_cancelled:
                break

            # Pick next queued patient. FOR UPDATE SKIP LOCKED lets multiple
            # workers on the same run claim distinct patients without two workers
            # grabbing the same row (which would double the LLM spend and create
            # duplicate annotations). Matches the standard pipeline claim path.
            stmt = select(PatientResult).where(
                PatientResult.pipeline_run_id == run_id,
                PatientResult.status == PatientResultStatus.QUEUED,
            ).limit(1)
            if _USE_DB_LOCKING:
                stmt = stmt.with_for_update(skip_locked=True)
            result = await db.execute(stmt)
            pr = result.scalar_one_or_none()
            if not pr:
                break

            pr.status = PatientResultStatus.PROCESSING
            pr.started_at = now_utc()
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

                # Run search queries on notes — collect matched sentences
                matched_notes = []
                matched_sentences = []  # (note, sentence_text, tokens)
                for note in notes:
                    is_matched = False
                    note_matched_sents = []
                    for query_str in include_queries:
                        query_groups = parse_query(query_str)
                        sentences = process_note(note.text, query_groups)
                        for s in sentences:
                            if s.get("is_target") or s.get("matched_tokens"):
                                is_matched = True
                                note_matched_sents.append(
                                    (s.get("text", ""), s.get("matched_tokens", []))
                                )

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
                        matched_sentences.extend(note_matched_sents)

                pr.notes_matched = len(matched_notes)

                if not matched_notes:
                    pr.status = PatientResultStatus.NO_MATCH
                    pr.finding_label = "no_match"
                    pr.completed_at = now_utc()
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
                    pr.completed_at = now_utc()

                    # Create annotation with matched keyword sentences (not LLM evidence)
                    from app.annotations.models import Annotation, ReviewStatus
                    note_id = matched_notes[0].id if matched_notes else None

                    # Build sentence_text from search-matched sentences
                    keyword_text = "; ".join(
                        sent_text for sent_text, _ in matched_sentences[:5] if sent_text
                    )
                    if not keyword_text and matched_notes:
                        keyword_text = matched_notes[0].text[:500]

                    # Collect matched tokens
                    all_tokens = []
                    for _, tokens in matched_sentences[:5]:
                        all_tokens.extend(tokens)

                    if note_id:
                        annotation = Annotation(
                            project_id=run.project_id,
                            patient_id=pr.patient_id,
                            note_id=note_id,
                            sentence_text=keyword_text,
                            matched_tokens=",".join(set(all_tokens)),
                            predicted_score=classification.confidence,
                            predicted_label=1 if classification.label == "positive" else 0,
                            predictor_model=config.get("llm_model", ""),
                            reasoning=classification.reasoning or "",
                            review_status=ReviewStatus.UNREVIEWED,
                            pipeline_run_id=run.id,
                            predicted_reasoning=classification.reasoning,
                        )
                        db.add(annotation)

                processed += 1

            except Exception as e:
                pr.status = PatientResultStatus.FAILED
                pr.error_message = str(e)
                pr.completed_at = now_utc()
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

        # Create annotations for sample-copied results (already completed before loop)
        from app.annotations.models import Annotation, ReviewStatus
        copied_stmt = select(PatientResult).where(
            PatientResult.pipeline_run_id == run_id,
            PatientResult.status == PatientResultStatus.COMPLETED,
            PatientResult.finding_label.isnot(None),
            PatientResult.started_at.is_(None),  # copied results have no started_at
        )
        copied_result = await db.execute(copied_stmt)
        for pr in copied_result.scalars().all():
            # Re-run search on patient notes to get matched sentences
            p_notes_stmt = select(Note).where(
                Note.patient_id == pr.patient_id,
                Note.text.isnot(None),
            ).order_by(Note.note_date)
            p_notes = list((await db.execute(p_notes_stmt)).scalars().all())

            note_id = p_notes[0].id if p_notes else None
            keyword_text = ""
            all_tokens = []

            for note in p_notes:
                for query_str in include_queries:
                    query_groups = parse_query(query_str)
                    sentences = process_note(note.text, query_groups)
                    for s in sentences:
                        if s.get("is_target") or s.get("matched_tokens"):
                            if not note_id:
                                note_id = note.id
                            sent = s.get("text", "")
                            if sent:
                                keyword_text += ("; " if keyword_text else "") + sent
                            all_tokens.extend(s.get("matched_tokens", []))

            if not keyword_text and p_notes:
                keyword_text = p_notes[0].text[:500]

            if note_id:
                db.add(Annotation(
                    project_id=run.project_id,
                    patient_id=pr.patient_id,
                    note_id=note_id,
                    sentence_text=keyword_text,
                    matched_tokens=",".join(set(all_tokens)),
                    predicted_score=pr.predicted_score,
                    predicted_label=1 if pr.finding_label == "positive" else 0,
                    predictor_model=config.get("llm_model", ""),
                    reasoning=pr.finding_reasoning or "",
                    review_status=ReviewStatus.UNREVIEWED,
                    pipeline_run_id=run.id,
                    predicted_reasoning=pr.finding_reasoning,
                ))
        await db.commit()

        # Finalize
        from app.evaluation.models import SessionStatus
        if run.is_cancelled:
            run.status = PipelineRunStatus.CANCELLED
        else:
            run.status = PipelineRunStatus.COMPLETED
            eval_session.status = SessionStatus.COMPLETED
            db.add(eval_session)

        run.completed_at = now_utc()
        db.add(run)
        await db.commit()

    return {"processed": processed, "failed": failed}


async def on_worker_startup(ctx: dict) -> None:
    """Auto-recover orphaned RUNNING pipeline runs on worker startup.

    If the worker crashed mid-run, PipelineRun stays RUNNING but the ARQ job
    is gone. This detects those runs, resets stuck 'processing' PatientResults
    to 'queued', and re-enqueues them.
    """
    import logging
    log = logging.getLogger("arq.worker.startup")
    try:
        from sqlalchemy import select

        from app.common.database import async_session
        from app.evaluation.models import PatientResult, PatientResultStatus
        from app.pipeline.models import PipelineRun, PipelineRunStatus

        async with async_session() as db:
            # Find RUNNING pipeline runs
            stmt = select(PipelineRun).where(
                PipelineRun.status == PipelineRunStatus.RUNNING,
            )
            result = await db.execute(stmt)
            orphaned_runs = list(result.scalars().all())

            for run in orphaned_runs:
                # Reset stuck 'processing' rows
                stuck_stmt = select(PatientResult).where(
                    PatientResult.pipeline_run_id == run.id,
                    PatientResult.status == PatientResultStatus.PROCESSING,
                )
                stuck = list((await db.execute(stuck_stmt)).scalars().all())
                for pr in stuck:
                    pr.status = PatientResultStatus.QUEUED
                    pr.started_at = None
                    db.add(pr)

                # Reset the run itself to QUEUED so the worker picks it up cleanly
                run.status = PipelineRunStatus.QUEUED
                db.add(run)

                await db.commit()

                # Re-enqueue
                from app.evaluation.service import _enqueue_eval_pipeline_run
                await _enqueue_eval_pipeline_run(run.id)
                log.info(
                    "Auto-recovered orphaned pipeline run %s (%d stuck rows reset)",
                    run.id, len(stuck),
                )

            if not orphaned_runs:
                log.info("No orphaned pipeline runs to recover")
    except Exception:
        log.exception("Failed to auto-recover orphaned pipeline runs")


class WorkerSettings:
    functions = [
        run_nlp_job,
        run_prediction_job,
        run_ingestion_job,
        run_export_job,
        run_pipeline_job,
        run_patient_task,
        run_sample_llm_job,
        run_eval_pipeline_job,
    ]
    on_startup = on_worker_startup
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
    # We handle retries ourselves (litellm for LLM, circuit breaker for runs).
    # ARQ-level retry would re-run jobs whose DB state is already marked FAILED.
    max_tries = 1
