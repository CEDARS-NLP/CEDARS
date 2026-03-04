"""Consolidated project statistics aggregation."""

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.jobs.models import BackgroundJob, JobStatus
from app.nlp.models import Sentence


async def get_project_stats(session: AsyncSession, project_id: str) -> dict:
    """Aggregate all project statistics in one call."""

    # --- Patients ---
    patient_q = await session.execute(
        select(Patient.status, func.count(Patient.id))
        .where(Patient.project_id == project_id, Patient.deleted_at.is_(None))
        .group_by(Patient.status)
    )
    patient_rows = patient_q.all()
    patient_total = sum(row[1] for row in patient_rows)
    by_status = {s.value: 0 for s in PatientStatus}
    for status_val, count in patient_rows:
        key = status_val.value if hasattr(status_val, "value") else status_val
        by_status[key] = count

    # --- Notes ---
    notes_q = await session.execute(
        select(func.count(Note.id)).where(
            Note.project_id == project_id, Note.deleted_at.is_(None)
        )
    )
    notes_total = notes_q.scalar_one()

    # --- Sentences ---
    sentences_q = await session.execute(
        select(
            func.count(Sentence.id),
            func.count(case((Sentence.is_target.is_(True), 1))),
            func.count(case((Sentence.is_negated.is_(True), 1))),
        ).where(Sentence.project_id == project_id)
    )
    sent_row = sentences_q.one()
    sentences_total, sentences_target, sentences_negated = sent_row

    # --- Annotations ---
    ann_q = await session.execute(
        select(Annotation.review_status, func.count(Annotation.id))
        .where(Annotation.project_id == project_id)
        .group_by(Annotation.review_status)
    )
    ann_rows = ann_q.all()
    ann_total = sum(row[1] for row in ann_rows)
    ann_by_status: dict[str, int] = {}
    for status_val, count in ann_rows:
        key = status_val.value if hasattr(status_val, "value") else status_val
        ann_by_status[key] = count

    events_q = await session.execute(
        select(func.count(Annotation.id)).where(
            Annotation.project_id == project_id,
            Annotation.event_date.isnot(None),
        )
    )
    events_found = events_q.scalar_one()

    # --- Annotators ---
    annotator_q = await session.execute(
        select(
            Annotation.reviewed_by,
            User.email,
            User.name,
            func.count(Annotation.id),
            func.count(case((Annotation.event_date.isnot(None), 1))),
        )
        .join(User, Annotation.reviewed_by == User.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.reviewed_by.isnot(None),
        )
        .group_by(Annotation.reviewed_by, User.email, User.name)
    )
    annotators = [
        {
            "user_id": row[0],
            "email": row[1],
            "name": row[2],
            "reviewed_count": row[3],
            "events_found": row[4],
        }
        for row in annotator_q.all()
    ]

    # --- Jobs ---
    latest_job_q = await session.execute(
        select(BackgroundJob)
        .where(BackgroundJob.project_id == project_id)
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    latest_job = latest_job_q.scalar_one_or_none()

    active_q = await session.execute(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
    )
    active_count = active_q.scalar_one()

    failed_q = await session.execute(
        select(func.count(BackgroundJob.id)).where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.status == JobStatus.FAILED,
        )
    )
    failed_count = failed_q.scalar_one()

    return {
        "patients": {
            "total": patient_total,
            "by_status": by_status,
        },
        "notes": {"total": notes_total},
        "sentences": {
            "total": sentences_total,
            "target": sentences_target,
            "negated": sentences_negated,
        },
        "annotations": {
            "total": ann_total,
            "reviewed": ann_by_status.get(ReviewStatus.REVIEWED.value, 0),
            "unreviewed": ann_by_status.get(ReviewStatus.UNREVIEWED.value, 0),
            "skipped": ann_by_status.get(ReviewStatus.SKIPPED.value, 0),
            "events_found": events_found,
        },
        "annotators": annotators,
        "jobs": {
            "latest": {
                "id": latest_job.id,
                "job_type": latest_job.job_type.value if hasattr(latest_job.job_type, "value") else latest_job.job_type,
                "status": latest_job.status.value if hasattr(latest_job.status, "value") else latest_job.status,
                "progress": latest_job.progress,
                "started_at": latest_job.started_at.isoformat() if latest_job.started_at else None,
                "completed_at": latest_job.completed_at.isoformat() if latest_job.completed_at else None,
            }
            if latest_job
            else None,
            "active_count": active_count,
            "failed_count": failed_count,
        },
    }
