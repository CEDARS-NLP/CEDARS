"""Patient-first annotation review adapters for the production schema."""

from datetime import date, datetime, timedelta

from sqlalchemy import Integer, exists, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.adjudication_compat import ReviewStatus
from app.annotations.adjudication_service import (
    _lock_run_identity,
    _refresh_note_reviews,
    _refresh_result,
    _skip_after_event_enabled,
    _sync_cursor,
    _update_patient_completion,
    apply_review_action,
    delete_patient_event,
    get_review_cursor,
    navigate_review,
)
from app.annotations.models import Annotation
from app.annotations.query_service import _patient_review_ready, _production_search_finished
from app.annotations.review_jobs import PatientReviewJob
from app.annotations.schemas import NextPatientResponse, PatientReviewStats
from app.audit.models import AuditAction
from app.audit.service import log_action
from app.common.utils import now_utc
from app.connectors.models import Patient, PatientStatus
from app.production.models import NotePrediction

_REVIEW_LEASE = timedelta(minutes=15)


class ReopenConflictError(ValueError):
    pass


async def _check_patient_completion(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str
) -> None:
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient:
        return
    run_id, generation = await _lock_run_identity(session, project_id)
    if patient.locked_by not in (None, user_id):
        return
    cursor = await _sync_cursor(session, project_id, patient, user_id, run_id, generation)
    state = cursor["handler_state"]
    review_type = await _refresh_note_reviews(
        session, project_id, patient, run_id, user_id, now_utc()
    )
    is_reviewed = all(
        status != ReviewStatus.UNREVIEWED for status in state["review_statuses"]
    )
    await _update_patient_completion(
        session, project_id, patient, user_id, run_id, is_reviewed, review_type
    )
    await _refresh_result(session, project_id, patient.id)
    await session.commit()


async def review_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
    user_id: str,
    event_date: date | datetime | None = None,
    skip_after_event: bool | None = None,
) -> dict | None:
    result = await apply_review_action(
        session, project_id, annotation_id, user_id,
        action="event" if event_date is not None else "negative",
        event_date=event_date,
        skip_after_event=skip_after_event,
    )
    if not result:
        return None
    state = result["cursor"]["handler_state"]
    canonical_date = result["patient"].event_date
    earlier_count = sum(
        status == ReviewStatus.UNREVIEWED and row.text_date < canonical_date
        for row, status in zip(state["annotations"], state["review_statuses"])
    ) if canonical_date else 0
    return {
        "annotation": result["annotation"],
        "skipped_count": result["skipped_count"],
        "earlier_count": earlier_count,
        "current_annotation_id": result["cursor"]["current_annotation_id"],
        "next_annotation_id": result["cursor"]["next_annotation_id"],
    }


async def skip_annotation(
    session: AsyncSession, project_id: str, annotation_id: str, user_id: str
) -> Annotation | None:
    result = await apply_review_action(
        session, project_id, annotation_id, user_id, action="skip"
    )
    if result:
        return result["annotation"]
    return None


async def get_next_patient_for_review(
    session: AsyncSession, project_id: str, user_id: str
) -> NextPatientResponse:
    run_id, generation = await _lock_run_identity(session, project_id)
    stale_before = now_utc() - _REVIEW_LEASE
    active_job_for_patient = exists(
        select(PatientReviewJob.id).where(
            col(PatientReviewJob.patient_uuid) == col(Patient.id),
            col(PatientReviewJob.status).in_(("queued", "running")),
        )
    )
    await session.execute(
        update(Patient)
        .where(
            col(Patient.project_id) == project_id,
            col(Patient.locked_by).is_not(None),
            col(Patient.locked_at) < stale_before,
            ~active_job_for_patient,
        )
        .values(locked_by=None, locked_at=None)
    )

    # Refetching patient/next (including React Query focus behavior) returns the
    # reviewer’s existing display lease instead of silently claiming another.
    patient = await session.scalar(
        select(Patient)
        .where(
            col(Patient.project_id) == project_id,
            col(Patient.locked_by) == user_id,
            ~active_job_for_patient,
        )
        .order_by(col(Patient.locked_at).desc())
        .limit(1)
    )
    if patient and not await _patient_review_ready(
        session, project_id, patient.patient_id_ext, run_id
    ):
        patient = None
        was_claimed = patient is None
    candidate_query = (
        select(Patient)
        .join(
            Annotation,
            or_(
                col(Annotation.patient_uuid) == col(Patient.id),
                (col(Annotation.project_id) == col(Patient.project_id))
                & (col(Annotation.patient_id) == col(Patient.patient_id_ext)),
            ),
        )
        .where(
            col(Patient.project_id) == project_id,
            col(Annotation.status) == "U",
            or_(
                col(Annotation.review_reason).is_(None),
                col(Annotation.review_reason).notin_(
                    ("llm_negative", "duplicate", "negated")
                ),
            ),
            col(Patient.locked_by).is_(None),
            ~active_job_for_patient,
        )
        .order_by(col(Patient.created_at))
    )
    if run_id:
        candidate_query = candidate_query.where(
            col(Annotation.production_run_id) == run_id
        )
    if patient is None:
        candidates = (
            await session.execute(candidate_query)
        ).scalars().unique().all()
        for candidate in candidates:
            if not await _patient_review_ready(
                session, project_id, candidate.patient_id_ext, run_id
            ):
                continue
            claim = await session.execute(
                update(Patient)
                .where(
                    col(Patient.id) == candidate.id,
                    col(Patient.locked_by).is_(None),
                )
                .values(locked_by=user_id, locked_at=now_utc())
            )
            if claim.rowcount == 1:
                patient = candidate
                break
    if not patient:
        pending = bool(
            (
                await session.execute(
                    select(col(Annotation.annotation_id)).where(
                        col(Annotation.project_id) == project_id,
                        col(Annotation.status) == "U",
                        or_(
                            col(Annotation.review_reason).is_(None),
                            col(Annotation.review_reason).notin_(
                                ("llm_negative", "duplicate", "negated")
                            ),
                        ),
                        *(
                            [col(Annotation.production_run_id) == run_id]
                            if run_id else []
                        ),
                    ).limit(1)
                )
            ).scalar_one_or_none()
        )
        if run_id:
            pending = pending or not await _production_search_finished(session, project_id, run_id)
            pending = pending or bool(await session.scalar(
                select(col(NotePrediction.id)).where(
                    col(NotePrediction.project_id) == project_id,
                    col(NotePrediction.run_id) == run_id,
                    col(NotePrediction.status) != "succeeded",
                ).limit(1)
            ))
        pending_job_count = await session.scalar(
            select(func.count()).select_from(PatientReviewJob).where(
                col(PatientReviewJob.project_id) == project_id,
                col(PatientReviewJob.status).in_(("queued", "running")),
            )
        ) or 0
        await session.rollback()
        return NextPatientResponse(
            all_complete=not pending and pending_job_count == 0,
            pending_review_jobs=pending_job_count,
        )
    was_claimed = patient.locked_by is None
    patient.locked_by = user_id
    patient.locked_at = now_utc()
    if was_claimed:
        patient.status = PatientStatus.REVIEWING
    session.add(patient)
    cursor = await _sync_cursor(session, project_id, patient, user_id, run_id, generation)
    skip_after_event = await _skip_after_event_enabled(session, project_id, None)
    pending_jobs = await session.scalar(
        select(func.count()).select_from(PatientReviewJob).where(
            col(PatientReviewJob.project_id) == project_id,
            col(PatientReviewJob.status).in_(("queued", "running")),
        )
    ) or 0
    total, pending = (
        await session.execute(
            select(
                func.count(Annotation.annotation_id),
                func.sum(func.cast(Annotation.status == "U", Integer)),
            ).where(
                col(Annotation.project_id) == project_id,
                or_(col(Annotation.patient_uuid) == patient.id,
                    col(Annotation.patient_id) == patient.patient_id_ext),
                *([col(Annotation.production_run_id) == run_id] if run_id else []),
            )
        )
    ).one()
    await session.commit()
    if was_claimed:
        await log_action(
            session, project_id, AuditAction.PATIENT_LOCKED,
            user_id=user_id, patient_id=patient.id,
        )
    failed_job_id = await session.scalar(
        select(PatientReviewJob.id)
        .where(
            col(PatientReviewJob.patient_uuid) == patient.id,
            col(PatientReviewJob.status) == "failed",
        )
        .order_by(col(PatientReviewJob.created_at).desc())
        .limit(1)
    )
    skip_after_event = await _skip_after_event_enabled(session, project_id, None)
    return NextPatientResponse(
        patient_id=patient.id,
        patient_id_ext=patient.patient_id_ext,
        total_annotations=total or 0,
        unreviewed_annotations=pending or 0,
        current_annotation_id=cursor["current_annotation_id"],
        next_annotation_id=cursor["next_annotation_id"],
        skip_after_event=skip_after_event,
        pending_review_jobs=pending_jobs,
        failed_review_job_id=failed_job_id,
    )


async def patient_review_cursor(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str
) -> dict | None:
    return await get_review_cursor(session, project_id, patient_id, user_id)


async def navigate_patient_review(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str, action: str
) -> dict | None:
    return await navigate_review(session, project_id, patient_id, user_id, action)


async def get_patient_annotations(
    session: AsyncSession, project_id: str, patient_id: str
) -> list[dict]:
    from app.annotations.query_service import get_patient_annotations as query_patient_annotations

    return await query_patient_annotations(session, project_id, patient_id)


async def unlock_patient(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str
) -> None:
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient or patient.locked_by != user_id:
        return
    patient.locked_by = None
    patient.locked_at = None
    session.add(patient)
    await session.commit()
    await log_action(
        session, project_id, AuditAction.PATIENT_UNLOCKED,
        user_id=user_id, patient_id=patient.id,
    )
    await _check_patient_completion(session, project_id, patient.id, user_id)


async def delete_event_date(
    session: AsyncSession, project_id: str, annotation_id: str, user_id: str
) -> dict | None:
    result = await delete_patient_event(session, project_id, annotation_id, user_id)
    if not result:
        return None
    return {"annotation": result["annotation"], "reverted_count": result["reverted_count"]}


async def get_patient_review_stats(
    session: AsyncSession, project_id: str, patient_id: str
) -> PatientReviewStats:
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient:
        return PatientReviewStats(total=0, unreviewed=0, reviewed=0, skipped=0)
    rows = (
        await session.execute(
            select(Annotation.status, func.count())
            .where(
                col(Annotation.project_id) == project_id,
                or_(col(Annotation.patient_uuid) == patient.id,
                    col(Annotation.patient_id) == patient.patient_id_ext),
            )
            .group_by(col(Annotation.status))
        )
    ).all()
    counts = {status: count for status, count in rows}
    return PatientReviewStats(
        total=sum(counts.values()),
        unreviewed=counts.get("U", 0),
        reviewed=counts.get("R", 0),
        skipped=counts.get("S", 0),
        current_event_date=patient.event_date,
        event_annotation_id=(
            str(patient.event_annotation_id) if patient.event_annotation_id is not None else None
        ),
    )


async def reopen_patient(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str
) -> bool:
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient or patient.status != PatientStatus.REVIEWED:
        return False
    count = (
        await session.execute(
            select(func.count()).select_from(Annotation).where(
                col(Annotation.project_id) == project_id,
                or_(col(Annotation.patient_uuid) == patient.id,
                    col(Annotation.patient_id) == patient.patient_id_ext),
            )
        )
    ).scalar() or 0
    if not count:
        raise ReopenConflictError("No stored annotations are available to reopen.")
    patient.status = PatientStatus.REVIEWING
    patient.review_source = None
    patient.review_reason = None
    patient.reviewed_by = None
    patient.reviewed_at = None
    patient.locked_by = None
    patient.locked_at = None
    patient.updated_at = now_utc()
    session.add(patient)
    await _refresh_result(session, project_id, patient.id)
    await session.commit()
    await log_action(
        session, project_id, AuditAction.PATIENT_REOPENED,
        user_id=user_id, patient_id=patient.id,
    )
    return True
