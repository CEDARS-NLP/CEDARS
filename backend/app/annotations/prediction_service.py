"""Prediction service: bulk prediction runs and token estimation."""

import logging

import tiktoken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.models import Annotation, AnnotationPrediction
from app.common.utils import now_utc
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.llm.pricing import estimate_cost
from app.nlp.models import SearchQuery
from app.predictors.llm import SYSTEM_PROMPT
from app.predictors.models import PredictorType
from app.predictors.service import get_active_predictor_config
from app.production.models import NotePrediction

logger = logging.getLogger(__name__)


async def run_bulk_predictions(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Run the configured predictor on complete matched notes via production."""
    config = await _production_config(session, project_id)
    from app.production.service import execute_run, start_run

    run = await start_run(session, project_id, None, config, confirmed=False)
    from app.nlp.service import _process_notes_into_sentences

    await _process_notes_into_sentences(
        session, project_id, create_annotations=False, rebuild=True
    )
    run = await execute_run(session, run.id)
    annotations = list(
        await session.scalars(
            select(Annotation).where(
                col(Annotation.project_id) == project_id,
                col(Annotation.production_run_id) == run.id,
            )
        )
    )
    predictions = list(
        await session.scalars(
            select(NotePrediction).where(
                col(NotePrediction.project_id) == project_id,
                col(NotePrediction.run_id) == run.id,
            )
        )
    )
    token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for prediction in predictions:
        usage = prediction.token_usage or {}
        for key in token_usage:
            token_usage[key] += int(usage.get(key, 0) or 0)
    return {
        "total_sentences": len(annotations),
        "predictions_made": sum(item.status == "succeeded" for item in predictions),
        "annotations_created": len(annotations),
        "errors": sum(item.status == "failed" for item in predictions),
        "token_usage": token_usage,
    }


async def _production_config(session: AsyncSession, project_id: str) -> dict:
    predictor = await get_active_predictor_config(session, project_id)
    if predictor is None:
        raise ValueError("No active predictor configured for this project")
    if predictor.predictor_type != PredictorType.LLM:
        raise ValueError("Production full-note prediction currently requires an LLM predictor")

    query = await session.scalar(
        select(SearchQuery).where(
            col(SearchQuery.project_id) == project_id,
            col(SearchQuery.deleted_at).is_(None),
            col(SearchQuery.is_active).is_(True),
        )
    )
    if query is None:
        raise ValueError("No active search query configured for this project")

    predictor_settings = dict(predictor.config or {})
    llm_settings = predictor_settings.get("llm_config") or predictor_settings.get("llm") or {
        key: predictor_settings[key]
        for key in ("provider", "model", "api_base")
        if key in predictor_settings
    }
    if not llm_settings.get("provider") or not llm_settings.get("model"):
        raise ValueError("The active LLM predictor requires a provider and model")
    return {
        **predictor_settings,
        "query": query.query,
        "hide_duplicates": query.hide_duplicates,
        "skip_after_event": query.skip_after_event,
        "exclude_negated": query.exclude_negated,
        "llm_config": llm_settings,
    }


def _unscored_annotations_stmt(project_id: str, predictor_config_id: str):
    """Annotations in a project that the given predictor has not scored yet."""
    already_scored = (
        select(col(AnnotationPrediction.id))
        .where(
            col(AnnotationPrediction.annotation_id) == col(Annotation.annotation_id),
            col(AnnotationPrediction.predictor_config_id) == predictor_config_id,
        )
        .exists()
    )
    return select(Annotation).where(
        col(Annotation.project_id) == project_id,
        col(Annotation.status) == "U",
        ~already_scored,
    )


async def estimate_bulk_predictions(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Estimate token usage for running the active predictor over unscored annotations."""
    try:
        config = await _production_config(session, project_id)
    except ValueError:
        return {
            "sentence_count": 0,
            "estimated_prompt_tokens": 0,
            "estimated_completion_tokens": 0,
            "estimated_total_tokens": 0,
            "estimated_cost": None,
        }

    result = await session.execute(
        select(col(Note.text))
        .join(
            Annotation,
            (col(Annotation.project_id) == col(Note.project_id))
            & (col(Annotation.text_id) == col(Note.text_id)),
        )
        .outerjoin(
            NotePrediction,
            (col(NotePrediction.project_id) == col(Note.project_id))
            & (col(NotePrediction.text_id) == col(Note.text_id)),
        )
        .where(
            col(Note.project_id) == project_id,
            col(Note.deleted_at).is_(None),
            col(NotePrediction.id).is_(None),
        )
        .distinct()
    )
    texts = list(result.scalars())

    sentence_count = len(texts)
    if sentence_count == 0:
        return {
            "sentence_count": 0,
            "estimated_prompt_tokens": 0,
            "estimated_completion_tokens": 0,
            "estimated_total_tokens": 0,
            "estimated_cost": None,
        }

    enc = tiktoken.get_encoding("cl100k_base")
    system_tokens = len(enc.encode(SYSTEM_PROMPT))

    # Estimate per-sentence: system prompt + ~80 tokens overhead + sentence text + ~50 completion
    total_prompt_tokens = 0
    estimated_completion = 50  # avg JSON response tokens
    for text in texts:
        text_tokens = len(enc.encode(text))
        total_prompt_tokens += system_tokens + 80 + text_tokens

    estimated_completion_tokens = sentence_count * estimated_completion

    return {
        "sentence_count": sentence_count,
        "estimated_prompt_tokens": total_prompt_tokens,
        "estimated_completion_tokens": estimated_completion_tokens,
        "estimated_total_tokens": total_prompt_tokens + estimated_completion_tokens,
        "estimated_cost": estimate_cost(
            config["llm_config"].get("provider"),
            config["llm_config"].get("model"),
            total_prompt_tokens,
            estimated_completion_tokens,
        ),
    }


async def dispatch_prediction_job(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> dict:
    """Dispatch a full-note production run while preserving the legacy job shape."""
    config = await _production_config(session, project_id)
    from app.production.service import start_run

    run = await start_run(session, project_id, user_id, config, confirmed=False)

    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.PREDICTION,
        status=JobStatus.PENDING,
        created_by=user_id,
        result_summary={"production_run_id": run.id},
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession
    from sqlalchemy.ext.asyncio import async_sessionmaker

    factory = async_sessionmaker(session.bind, class_=_AsyncSession, expire_on_commit=False)
    task = asyncio.create_task(_execute_production_prediction_job(bg_job.id, run.id, factory))

    def _on_done(done: asyncio.Task) -> None:
        if not done.cancelled() and done.exception():
            logger.exception(
                "Background production prediction task failed", exc_info=done.exception()
            )

    task.add_done_callback(_on_done)

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }


async def _execute_production_prediction_job(job_id, run_id, session_factory) -> None:
    from app.production.service import execute_run, get_stats

    async with session_factory() as session:
        job = await session.get(BackgroundJob, job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        job.started_at = now_utc()
        await session.commit()
        try:
            from app.nlp.service import _process_notes_into_sentences

            await _process_notes_into_sentences(
                session, job.project_id, create_annotations=False, rebuild=True
            )
            run = await execute_run(session, run_id)
            stats = await get_stats(session, run_id)
            job.status = JobStatus.FAILED if run.status == "failed" else JobStatus.COMPLETED
            job.progress = 100
            job.result_summary = {**(job.result_summary or {}), **stats}
        except Exception as exc:
            await session.rollback()
            job = await session.get(BackgroundJob, job_id)
            if job is None:
                return
            job.status = JobStatus.FAILED
            job.error_message = str(exc)[:2000]
        job.completed_at = now_utc()
        session.add(job)
        await session.commit()


async def get_prediction_job_status(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Get the latest prediction job status for a project."""
    stmt = (
        select(BackgroundJob)
        .where(
            col(BackgroundJob.project_id) == project_id,
            col(BackgroundJob.job_type) == JobType.PREDICTION,
        )
        .order_by(col(BackgroundJob.created_at).desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    bg_job = result.scalar_one_or_none()
    if not bg_job:
        return None

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
        "result_summary": bg_job.result_summary,
    }


async def cancel_prediction_job(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Cancel a running or pending prediction job for a project.

    Also handles stuck/zombie jobs: if the job is already cancelled but
    still in a non-terminal status, force it to CANCELLED.
    """

    # Find any non-terminal prediction job (pending, running)
    stmt = (
        select(BackgroundJob)
        .where(
            col(BackgroundJob.project_id) == project_id,
            col(BackgroundJob.job_type) == JobType.PREDICTION,
            col(BackgroundJob.status).in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
        .order_by(col(BackgroundJob.created_at).desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    bg_job = result.scalar_one_or_none()
    if not bg_job:
        return None

    run_id = (bg_job.result_summary or {}).get("production_run_id")
    if run_id:
        from app.production.service import cancel_run

        await cancel_run(session, run_id)
    bg_job.is_cancelled = True
    # If job is stuck (already cancelled but still "running"), force terminal state
    if bg_job.status in (JobStatus.PENDING, JobStatus.RUNNING):
        bg_job.status = JobStatus.CANCELLED
        bg_job.completed_at = now_utc()
    session.add(bg_job)
    await session.commit()

    return {"job_id": bg_job.id, "cancelled": True}
