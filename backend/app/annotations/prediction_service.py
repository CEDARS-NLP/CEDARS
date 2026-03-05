"""Prediction service: bulk prediction runs and token estimation."""

import logging

import tiktoken
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp.models import Sentence
from app.predictors.base import PredictionResult, PredictorError
from app.predictors.factory import create_predictor
from app.predictors.llm import SYSTEM_PROMPT
from app.predictors.models import PredictorConfig

logger = logging.getLogger(__name__)


async def run_bulk_predictions(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Run the active predictor on all target sentences without annotations.

    Flow:
    1. Get the active predictor config for the project
    2. Find target sentences that don't yet have annotations
    3. Run predictor on each sentence
    4. Create annotation records with prediction results
    """
    # Get active predictor
    stmt = select(PredictorConfig).where(
        PredictorConfig.project_id == project_id,
        PredictorConfig.is_active == True,  # noqa: E712
        PredictorConfig.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    predictor_config = result.scalar_one_or_none()

    if not predictor_config:
        raise ValueError("No active predictor configured for this project")

    predictor = create_predictor(predictor_config)

    # Find target sentences without annotations
    existing_annotations = (
        select(Annotation.sentence_id)
        .where(Annotation.project_id == project_id)
        .scalar_subquery()
    )

    stmt = (
        select(Sentence, Note.patient_id)
        .join(Note, Sentence.note_id == Note.id)
        .where(
            Sentence.project_id == project_id,
            Sentence.is_target == True,  # noqa: E712
            Note.deleted_at.is_(None),
            Sentence.id.notin_(existing_annotations),
        )
    )
    result = await session.execute(stmt)
    rows = result.all()

    stats: dict = {
        "total_sentences": len(rows),
        "predictions_made": 0,
        "annotations_created": 0,
        "errors": 0,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    for sentence, patient_id in rows:
        prediction: PredictionResult | None = None
        try:
            prediction = await predictor.predict(sentence.text)
            stats["predictions_made"] += 1
            if prediction.token_usage:
                stats["token_usage"]["prompt_tokens"] += prediction.token_usage.prompt_tokens
                stats["token_usage"]["completion_tokens"] += prediction.token_usage.completion_tokens
                stats["token_usage"]["total_tokens"] += prediction.token_usage.total_tokens
        except PredictorError as e:
            logger.warning("Prediction failed for sentence %s: %s", sentence.id, e)
            stats["errors"] += 1

        annotation = Annotation(
            project_id=project_id,
            patient_id=patient_id,
            note_id=sentence.note_id,
            sentence_id=sentence.id,
            sentence_text=sentence.text,
            matched_tokens=",".join(sentence.matched_tokens) if sentence.matched_tokens else "",
            is_negated=sentence.is_negated,
            predicted_score=prediction.score if prediction else None,
            predicted_label=prediction.label if prediction else None,
            predictor_model=prediction.model if prediction else "",
            reasoning=prediction.reasoning if prediction else "",
        )
        session.add(annotation)
        stats["annotations_created"] += 1

    await session.commit()
    return stats


async def estimate_bulk_predictions(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Estimate token usage for bulk predictions on unannotated target sentences."""
    existing_annotations = (
        select(Annotation.sentence_id)
        .where(Annotation.project_id == project_id)
        .scalar_subquery()
    )

    stmt = select(Sentence.text).where(
        Sentence.project_id == project_id,
        Sentence.is_target == True,  # noqa: E712
        Sentence.id.notin_(existing_annotations),
    )
    result = await session.execute(stmt)
    texts = [r[0] for r in result.all()]

    sentence_count = len(texts)
    if sentence_count == 0:
        return {
            "sentence_count": 0,
            "estimated_prompt_tokens": 0,
            "estimated_completion_tokens": 0,
            "estimated_total_tokens": 0,
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
    }


async def dispatch_prediction_job(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> dict:
    """Create a BackgroundJob and enqueue prediction processing via ARQ.

    Falls back to synchronous execution if Redis/ARQ is unavailable.
    Raises ValueError if no active predictor is configured.
    """
    # Verify active predictor exists before dispatching
    stmt = select(PredictorConfig).where(
        PredictorConfig.project_id == project_id,
        PredictorConfig.is_active == True,  # noqa: E712
        PredictorConfig.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    if not result.scalar_one_or_none():
        raise ValueError("No active predictor configured for this project")

    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.PREDICTION,
        status=JobStatus.PENDING,
        created_by=user_id,
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    use_sync = True
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())

        # Check if any ARQ workers are active before enqueuing
        worker_keys = await redis.keys("arq:worker:*")
        if worker_keys:
            arq_job = await redis.enqueue_job("run_prediction_job", project_id, bg_job.id)
            bg_job.arq_job_id = arq_job.job_id
            session.add(bg_job)
            await session.commit()
            use_sync = False
        else:
            logger.warning("No ARQ workers found, running prediction synchronously")

        await redis.aclose()
    except Exception:
        logger.warning("ARQ unavailable, running prediction synchronously")

    if use_sync:
        import asyncio

        from sqlalchemy.ext.asyncio import async_sessionmaker
        from sqlalchemy.ext.asyncio import AsyncSession as _AsyncSession

        from app.jobs.prediction import execute_prediction_job

        factory = async_sessionmaker(
            session.bind, class_=_AsyncSession, expire_on_commit=False
        )
        # Run as a background task so the endpoint returns immediately
        # and the job is cancellable via the cancel endpoint.
        asyncio.create_task(execute_prediction_job(project_id, bg_job.id, session_factory=factory))

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }


async def get_prediction_job_status(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Get the latest prediction job status for a project."""
    stmt = (
        select(BackgroundJob)
        .where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type == JobType.PREDICTION,
        )
        .order_by(BackgroundJob.created_at.desc())
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
    """Cancel a running or pending prediction job for a project."""
    stmt = (
        select(BackgroundJob)
        .where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type == JobType.PREDICTION,
            BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            BackgroundJob.is_cancelled == False,  # noqa: E712
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    bg_job = result.scalar_one_or_none()
    if not bg_job:
        return None

    bg_job.is_cancelled = True
    session.add(bg_job)
    await session.commit()

    return {"job_id": bg_job.id, "cancelled": True}
