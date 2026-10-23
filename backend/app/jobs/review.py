"""ARQ worker and recovery for durable patient-review batches."""

from __future__ import annotations

import logging
from datetime import timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.common.utils import now_utc
from app.config import settings

logger = logging.getLogger(__name__)
MAX_REVIEW_ATTEMPTS = 3
STALE_REVIEW_JOB_AGE = timedelta(hours=1)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def enqueue_review_job(job_id: str, attempt: int = 0) -> bool:
    """Enqueue one attempt idempotently; the database remains the source of truth."""
    redis = None
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        queued = await redis.enqueue_job(
            "finalize_patient_review_job",
            job_id,
            _job_id=f"patient-review-{job_id}-{attempt}",
        )
        return queued is not None
    except Exception:
        logger.exception("Failed to enqueue patient review job %s", job_id)
        return False
    finally:
        if redis is not None:
            await redis.aclose()


async def _claim_job(session: AsyncSession, job_id: str) -> bool:
    from app.annotations.review_jobs import PatientReviewJob

    result = await session.execute(
        update(PatientReviewJob)
        .where(
            PatientReviewJob.id == job_id,
            PatientReviewJob.status == "queued",
            PatientReviewJob.attempt_count < MAX_REVIEW_ATTEMPTS,
        )
        .values(
            status="running",
            attempt_count=PatientReviewJob.attempt_count + 1,
            started_at=now_utc(),
            updated_at=now_utc(),
        )
        .execution_options(synchronize_session=False)
    )
    await session.commit()
    return result.rowcount == 1


async def _record_failure(
    session_factory: async_sessionmaker[AsyncSession], job_id: str, error: Exception
) -> tuple[str | None, int]:
    from app.annotations.review_jobs import PatientReviewJob
    from app.connectors.models import Patient, PatientStatus
    from app.production.results import refresh_patient_result

    async with session_factory() as session:
        job = await session.scalar(
            select(PatientReviewJob)
            .where(PatientReviewJob.id == job_id)
            .with_for_update()
        )
        if job is None or job.status != "running":
            return None, 0
        job.last_error = str(error)[:4000]
        job.updated_at = now_utc()
        attempt = job.attempt_count
        patient = await session.scalar(
            select(Patient).where(Patient.id == job.patient_uuid).with_for_update()
        )
        if attempt >= MAX_REVIEW_ATTEMPTS:
            job.status = "failed"
            job.completed_at = now_utc()
            if patient and patient.locked_by == job.reviewer_id:
                patient.locked_by = None
                patient.locked_at = None
                patient.status = PatientStatus.REVIEWING
                patient.review_source = None
                patient.review_reason = None
                patient.reviewed_by = None
                patient.reviewed_at = None
                session.add(patient)
            session.add(job)
            await session.commit()
            if patient is not None:
                try:
                    await refresh_patient_result(session, job.project_id, patient.id)
                    await session.commit()
                except Exception:
                    await session.rollback()
                    logger.exception("Failed to refresh RESULTS after review job failure %s", job_id)
            return "failed", attempt

        job.status = "queued"
        job.started_at = None
        session.add(job)
        await session.commit()
        return "queued", attempt


async def execute_patient_review_job(
    job_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Apply one submitted patient batch, retrying failures up to three attempts."""
    from app.annotations.adjudication_service import apply_patient_review_job
    from app.annotations.review_jobs import PatientReviewJob

    factory = session_factory or _make_session_factory()
    async with factory() as session:
        claimed = await _claim_job(session, job_id)
        if not claimed:
            job = await session.get(PatientReviewJob, job_id)
            return {"status": job.status if job else "missing", "job_id": job_id}

    try:
        async with factory() as session:
            job = await apply_patient_review_job(session, job_id)
            return {
                "status": job.status,
                "job_id": job.id,
                "attempt_count": job.attempt_count,
            }
    except Exception as error:
        logger.exception("Patient review batch %s failed", job_id)
        status, attempt = await _record_failure(factory, job_id, error)
        if status == "queued":
            await enqueue_review_job(job_id, attempt)
        return {"status": status or "missing", "job_id": job_id, "attempt_count": attempt}


async def recover_patient_review_jobs(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> int:
    """Re-enqueue queued work and recover jobs abandoned by a worker crash."""
    from app.annotations.review_jobs import PatientReviewJob
    from app.connectors.models import Patient, PatientStatus
    from app.production.results import refresh_patient_result

    factory = session_factory or _make_session_factory()
    stale_before = now_utc() - STALE_REVIEW_JOB_AGE
    async with factory() as session:
        stale_jobs = list(
            await session.scalars(
                select(PatientReviewJob)
                .where(
                    PatientReviewJob.status == "running",
                    PatientReviewJob.started_at < stale_before,
                )
                .with_for_update(skip_locked=True)
            )
        )
        for job in stale_jobs:
            job.last_error = "Worker stopped before the batch completed"
            job.updated_at = now_utc()
            if job.attempt_count >= MAX_REVIEW_ATTEMPTS:
                job.status = "failed"
                job.completed_at = now_utc()
                patient = await session.get(Patient, job.patient_uuid)
                if patient and patient.locked_by == job.reviewer_id:
                    patient.locked_by = None
                    patient.locked_at = None
                    patient.status = PatientStatus.REVIEWING
                    patient.review_source = None
                    patient.review_reason = None
                    patient.reviewed_by = None
                    patient.reviewed_at = None
                    session.add(patient)
                    await refresh_patient_result(session, job.project_id, patient.id)
            else:
                job.status = "queued"
                job.started_at = None
            session.add(job)
        await session.commit()
        queued = list(
            await session.scalars(
                select(PatientReviewJob)
                .where(PatientReviewJob.status == "queued")
                .order_by(PatientReviewJob.created_at)
            )
        )

    enqueued = 0
    for job in queued:
        if await enqueue_review_job(job.id, job.attempt_count):
            enqueued += 1
    return enqueued


async def request_patient_review_retry(
    session: AsyncSession, project_id: str, job_id: str, user_id: str
):
    from app.annotations.review_jobs import PatientReviewJob

    job = await session.scalar(
        select(PatientReviewJob).where(
            PatientReviewJob.id == job_id,
            PatientReviewJob.project_id == project_id,
        ).with_for_update()
    )
    if job is None or job.status != "failed":
        return None
    job.retry_requested_by = user_id
    job.retry_requested_at = now_utc()
    job.updated_at = now_utc()
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def retry_patient_review_job(
    session: AsyncSession, project_id: str, job_id: str
):
    from app.annotations.review_jobs import PatientReviewJob
    from app.connectors.models import Patient, PatientStatus

    job = await session.scalar(
        select(PatientReviewJob).where(
            PatientReviewJob.id == job_id,
            PatientReviewJob.project_id == project_id,
        ).with_for_update()
    )
    if job is None or job.status != "failed":
        return None
    patient = await session.scalar(
        select(Patient).where(Patient.id == job.patient_uuid).with_for_update()
    )
    if patient is None:
        return None
    if patient.locked_by not in (None, job.reviewer_id):
        raise ValueError("Patient is currently locked by another reviewer")
    patient.locked_by = job.reviewer_id
    patient.locked_at = now_utc()
    patient.status = PatientStatus.REVIEWING
    patient.review_source = None
    patient.review_reason = None
    patient.reviewed_by = None
    patient.reviewed_at = None
    job.status = "queued"
    job.attempt_count = 0
    job.last_error = None
    job.retry_requested_by = None
    job.retry_requested_at = None
    job.started_at = None
    job.completed_at = None
    job.updated_at = now_utc()
    session.add_all([patient, job])
    await session.commit()
    await session.refresh(job)
    return job


async def discard_failed_patient_review_job(
    session: AsyncSession, project_id: str, job_id: str
):
    from app.annotations.review_jobs import PatientReviewJob

    job = await session.scalar(
        select(PatientReviewJob).where(
            PatientReviewJob.id == job_id,
            PatientReviewJob.project_id == project_id,
        ).with_for_update()
    )
    if job is None or job.status != "failed":
        return None
    job.status = "discarded"
    job.updated_at = now_utc()
    job.completed_at = now_utc()
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job
