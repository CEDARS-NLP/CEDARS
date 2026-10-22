"""Compatibility worker for production note-level prediction runs."""

import asyncio
import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.common.utils import now_utc
from app.config import settings
from app.jobs.models import BackgroundJob, JobStatus
from app.production.models import NotePrediction, ProductionResult, ProductionRun

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
    """Run the staged production coordinator while retaining the legacy job shape."""
    if session_factory is None:
        session_factory = _make_session_factory()

    stats: dict = {
        "total_sentences": 0,
        "predictions_made": 0,
        "annotations_created": 0,
        "errors": 0,
        "patients_processed": 0,
        "total_patients": 0,
        "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
    }

    async with session_factory() as session:
        bg_job = await session.get(BackgroundJob, job_db_id)
        if not bg_job:
            logger.error("BackgroundJob %s not found", job_db_id)
            return {"error": "Job not found"}

        production_run_id = (bg_job.result_summary or {}).get("production_run_id")
        if bg_job.is_cancelled:
            if production_run_id:
                from app.production.service import cancel_run

                await cancel_run(session, production_run_id)
            bg_job.status = JobStatus.CANCELLED
            bg_job.completed_at = now_utc()
            bg_job.result_summary = {**(bg_job.result_summary or {}), **stats}
            await session.commit()
            return stats

        try:
            from app.annotations.prediction_service import _production_config
            from app.production.service import start_run

            if production_run_id is None:
                config = await _production_config(session, project_id)
                run = await start_run(
                    session,
                    project_id,
                    bg_job.created_by,
                    config,
                    confirmed=False,
                )
                production_run_id = run.id
                bg_job.result_summary = {
                    **(bg_job.result_summary or {}),
                    "production_run_id": production_run_id,
                }
            else:
                run = await session.get(ProductionRun, production_run_id)
                if run is None or run.project_id != project_id:
                    raise ValueError("Production run not found for this prediction job")

            bg_job.status = JobStatus.RUNNING
            bg_job.started_at = bg_job.started_at or now_utc()
            session.add(bg_job)
            await session.commit()
        except Exception as exc:
            logger.exception("Could not stage prediction run for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)[:2000]
            bg_job.completed_at = now_utc()
            session.add(bg_job)
            await session.commit()
            return stats

    async def _execute() -> None:
        from app.production.service import execute_run

        async with session_factory() as run_session:
            await execute_run(run_session, production_run_id)
            await _link_predictions_to_annotations(run_session, project_id, production_run_id)

    execution = asyncio.create_task(_execute())
    cancellation_requested = False
    bind = session_factory.kw.get("bind")
    pool = getattr(getattr(bind, "sync_engine", None), "pool", None)
    can_poll_concurrently = type(pool).__name__ != "StaticPool"
    if can_poll_concurrently:
        while not execution.done():
            await asyncio.sleep(0.05)
            async with session_factory() as session:
                bg_job = await session.get(BackgroundJob, job_db_id)
                if bg_job is None:
                    break
                if bg_job.is_cancelled and not cancellation_requested:
                    from app.production.service import cancel_run

                    await cancel_run(session, production_run_id)
                    cancellation_requested = True

                production_run = await session.get(ProductionRun, production_run_id)
                if production_run is not None:
                    stats = await _collect_stats(session, project_id, production_run_id)
                    bg_job.progress = (
                        min(99, int(100 * production_run.completed_notes / production_run.total_notes))
                        if production_run.total_notes
                        else 99
                    )
                    bg_job.result_summary = {**(bg_job.result_summary or {}), **stats}
                    session.add(bg_job)
                    await session.commit()

    try:
        await execution
    except Exception:
        if not cancellation_requested:
            logger.exception("Prediction job failed for project %s", project_id)

    async with session_factory() as session:
        bg_job = await session.get(BackgroundJob, job_db_id)
        if bg_job is None:
            return stats
        production_run = await session.get(ProductionRun, production_run_id)
        stats = await _collect_stats(session, project_id, production_run_id)
        is_cancelled = production_run is not None and production_run.status == "cancelled"
        bg_job.status = (
            JobStatus.CANCELLED
            if is_cancelled
            else JobStatus.FAILED
            if production_run is None or production_run.status == "failed"
            else JobStatus.COMPLETED
        )
        bg_job.progress = 100 if not is_cancelled else bg_job.progress
        bg_job.completed_at = now_utc()
        bg_job.result_summary = {**(bg_job.result_summary or {}), **stats}
        session.add(bg_job)
        await session.commit()
        return stats


async def _link_predictions_to_annotations(
    session: AsyncSession, project_id: str, run_id: str
) -> None:
    from app.annotations.models import Annotation
    from app.connectors.models import Patient, PatientStatus

    predictions = list(
        await session.scalars(
            select(NotePrediction).where(
                NotePrediction.project_id == project_id,
                NotePrediction.run_id == run_id,
            )
        )
    )
    prediction_by_text = {item.text_id: item for item in predictions}
    annotations = list(
        await session.scalars(
            select(Annotation).where(
                Annotation.project_id == project_id,
                Annotation.production_run_id == run_id,
            )
        )
    )
    for annotation in annotations:
        prediction = prediction_by_text.get(annotation.text_id)
        if prediction is not None:
            annotation.prediction_id = prediction.id

    predictions_by_patient: dict[str, list[NotePrediction]] = {}
    for prediction in predictions:
        predictions_by_patient.setdefault(prediction.patient_id, []).append(prediction)
    for patient in await session.scalars(
        select(Patient).where(Patient.project_id == project_id)
    ):
        patient_predictions = predictions_by_patient.get(patient.patient_id_ext, [])
        if (
            patient.status == PatientStatus.REVIEWED
            and patient_predictions
            and all(item.status == "succeeded" and item.label == 0 for item in patient_predictions)
        ):
            patient.review_source = "llm"
    await session.commit()


async def _collect_stats(
    session: AsyncSession, project_id: str, run_id: str
) -> dict:
    from app.annotations.models import Annotation

    predictions = list(
        await session.scalars(
            select(NotePrediction).where(
                NotePrediction.project_id == project_id,
                NotePrediction.run_id == run_id,
            )
        )
    )
    annotations_count = await session.scalar(
        select(func.count()).select_from(Annotation).where(
            Annotation.project_id == project_id,
            Annotation.production_run_id == run_id,
        )
    )
    results = list(
        await session.scalars(
            select(ProductionResult).where(ProductionResult.project_id == project_id)
        )
    )
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for prediction in predictions:
        for key in usage:
            usage[key] += int((prediction.token_usage or {}).get(key, 0) or 0)
    return {
        "total_sentences": annotations_count or 0,
        "predictions_made": sum(item.status == "succeeded" for item in predictions),
        "annotations_created": annotations_count or 0,
        "errors": sum(item.status == "failed" for item in predictions),
        "patients_processed": sum(
            item.processing_status in {"completed", "failed"} for item in results
        ),
        "total_patients": len(results),
        "token_usage": usage,
    }
