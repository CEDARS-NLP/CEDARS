"""Prediction job executor: per-patient batched bulk predictions."""

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.models import Annotation
from app.config import settings
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus
from app.nlp.models import Sentence
from app.predictors.base import PredictionResult, PredictorError
from app.predictors.factory import create_predictor
from app.predictors.models import PredictorConfig

logger = logging.getLogger(__name__)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a standalone session factory for worker processes."""
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def execute_prediction_job(
    project_id: str,
    job_db_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Run bulk predictions with per-patient batching.

    - Groups target sentences by patient
    - Commits after each patient (annotations immediately available)
    - Checks cancellation flag between patients
    - Updates BackgroundJob progress after each patient
    """
    if session_factory is None:
        session_factory = _make_session_factory()

    async with session_factory() as session:
        bg_job = await session.get(BackgroundJob, job_db_id)
        if not bg_job:
            logger.error("BackgroundJob %s not found", job_db_id)
            return {"error": "Job not found"}

        bg_job.status = JobStatus.RUNNING
        bg_job.started_at = datetime.now(UTC)
        session.add(bg_job)
        await session.commit()

        stats: dict = {
            "total_sentences": 0,
            "predictions_made": 0,
            "annotations_created": 0,
            "errors": 0,
            "patients_processed": 0,
            "total_patients": 0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

        try:
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

            # Find target sentences without annotations, grouped by patient
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
                .order_by(Note.patient_id, Note.note_date, Sentence.sentence_number)
            )
            result = await session.execute(stmt)
            rows = result.all()

            # Group by patient
            patient_batches: dict[str, list[tuple]] = defaultdict(list)
            for sentence, patient_id in rows:
                patient_batches[patient_id].append((sentence, patient_id))

            stats["total_sentences"] = len(rows)
            stats["total_patients"] = len(patient_batches)

            # Process per-patient
            for patient_idx, (patient_id, sentences) in enumerate(patient_batches.items()):
                # Check cancellation
                await session.refresh(bg_job)
                if bg_job.is_cancelled:
                    bg_job.status = JobStatus.CANCELLED
                    bg_job.completed_at = datetime.now(UTC)
                    bg_job.result_summary = stats
                    session.add(bg_job)
                    await session.commit()
                    return stats

                for sentence, pid in sentences:
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
                        patient_id=pid,
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

                # Commit after each patient
                await session.commit()
                stats["patients_processed"] += 1

                # Update progress
                bg_job.progress = int(((patient_idx + 1) / stats["total_patients"]) * 100)
                bg_job.result_summary = stats
                session.add(bg_job)
                await session.commit()

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = datetime.now(UTC)
            bg_job.result_summary = stats

        except Exception as exc:
            logger.exception("Prediction job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return stats
