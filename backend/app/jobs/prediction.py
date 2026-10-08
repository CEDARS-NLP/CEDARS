"""Prediction job executor: per-patient batched bulk predictions."""

import logging
from collections import defaultdict
from dataclasses import asdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.completion_service import complete_negative_llm_patients
from app.annotations.models import Annotation, AnnotationPrediction
from app.common.utils import now_utc
from app.config import settings
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus
from app.predictors.base import PredictionResult, PredictorError
from app.predictors.factory import create_predictor
from app.predictors.models import PredictorConfig
from app.predictors.service import get_active_predictor_config

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
    """Score existing annotations with the active predictor, batched per patient.

    - Groups unscored annotations by patient
    - Commits after each patient (verdicts immediately available)
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
        bg_job.started_at = now_utc()
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
            predictor_config = await get_active_predictor_config(session, project_id)
            if not predictor_config:
                raise ValueError("No active predictor configured for this project")

            predictor = create_predictor(predictor_config)

            # Find annotations this predictor has not scored yet, grouped by patient
            already_scored = (
                select(AnnotationPrediction.id)
                .where(
                    AnnotationPrediction.annotation_id == Annotation.id,
                    AnnotationPrediction.predictor_config_id == predictor_config.id,
                )
                .exists()
            )
            stmt = (
                select(Annotation)
                .join(Note, Annotation.note_id == Note.id)
                .where(
                    Annotation.project_id == project_id,
                    Note.deleted_at.is_(None),
                    Annotation.review_excluded.is_(False),
                    ~already_scored,
                )
                .order_by(Annotation.patient_id, Note.note_date, Annotation.sentence_number)
            )
            result = await session.execute(stmt)
            rows = list(result.scalars().all())

            # Group by patient
            patient_batches: dict[str, list[Annotation]] = defaultdict(list)
            for annotation in rows:
                patient_batches[annotation.patient_id].append(annotation)

            stats["total_sentences"] = len(rows)
            stats["total_patients"] = len(patient_batches)

            # Process per-patient
            for patient_idx, (patient_id, annotations) in enumerate(patient_batches.items()):
                # Check cancellation
                await session.refresh(bg_job)
                if bg_job.is_cancelled:
                    bg_job.status = JobStatus.CANCELLED
                    bg_job.completed_at = now_utc()
                    bg_job.result_summary = stats
                    session.add(bg_job)
                    await session.commit()
                    return stats

                for annotation in annotations:
                    prediction: PredictionResult | None = None
                    try:
                        prediction = await predictor.predict(annotation.sentence_text)
                        stats["predictions_made"] += 1
                        pred_use = prediction.token_usage
                        if pred_use:
                            stats["token_usage"]["prompt_tokens"] += pred_use.prompt_tokens
                            stats["token_usage"]["completion_tokens"] += pred_use.completion_tokens
                            stats["token_usage"]["total_tokens"] += pred_use.total_tokens
                    except PredictorError as e:
                        logger.warning("Prediction failed for annotation %s: %s", annotation.id, e)
                        stats["errors"] += 1
                        continue

                    session.add(
                        AnnotationPrediction(
                            annotation_id=annotation.id,
                            project_id=project_id,
                            predictor_config_id=predictor_config.id,
                            predictor_model=prediction.model,
                            predicted_score=prediction.score,
                            predicted_label=prediction.label,
                            reasoning=prediction.reasoning or "",
                            token_usage=(
                                asdict(prediction.token_usage)
                                if prediction.token_usage
                                else None
                            ),
                        )
                    )
                    stats["annotations_created"] += 1

                # Commit after each patient
                await complete_negative_llm_patients(
                    session, project_id, [patient_id], predictor_config,
                )
                await session.commit()
                stats["patients_processed"] += 1

                # Update progress
                bg_job.progress = int(((patient_idx + 1) / stats["total_patients"]) * 100)
                bg_job.result_summary = stats
                session.add(bg_job)
                await session.commit()

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = now_utc()
            bg_job.result_summary = stats

        except Exception:
            logger.exception("Prediction job failed for project %s", project_id)
            await session.rollback()
            bg_job = await session.get(BackgroundJob, job_db_id)
            if bg_job is None:
                return stats
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = "Prediction processing failed. Check server logs for details."
            bg_job.completed_at = now_utc()

        session.add(bg_job)
        await session.commit()
        return stats
