"""Review service: patient-first annotation review, skip, event dates."""

import logging
from datetime import datetime
from typing import cast as typing_cast

from sqlalchemy import CursorResult, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.filters import reviewable_filter as _reviewable_filter
from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
from app.annotations.schemas import NextPatientResponse, PatientReviewStats
from app.audit.models import AuditAction
from app.audit.service import log_action
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.models import SearchQuery
from app.predictors.service import get_active_predictor_config
from app.projects.models import Project

logger = logging.getLogger(__name__)


class ReopenConflictError(ValueError):
    pass


async def _check_patient_completion(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    user_id: str,
) -> None:
    """Mark patient as REVIEWED if all their annotations are reviewed/skipped."""
    active = await get_active_predictor_config(session, project_id)
    unreviewed_count = (
        await session.execute(
            select(func.count())
            .select_from(Annotation)
            .where(
                col(Annotation.project_id) == project_id,
                col(Annotation.patient_id) == patient_id,
                col(Annotation.review_status) == ReviewStatus.UNREVIEWED,
                col(Annotation.review_excluded).is_(False),
                _reviewable_filter(active.id if active else None),
            )
        )
    ).scalar() or 0

    if unreviewed_count == 0:
        patient = (
            await session.execute(
                select(Patient).where(col(Patient.id) == patient_id)
            )
        ).scalar_one_or_none()
        if patient:
            patient.status = PatientStatus.REVIEWED
            patient.review_source = "human"
            patient.review_reason = "manual_review"
            patient.reviewed_by = user_id
            patient.reviewed_at = now_utc()
            patient.locked_by = None
            patient.locked_at = None
            session.add(patient)
            await session.commit()


async def review_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
    user_id: str,
    event_date: datetime | None = None,
) -> dict | None:
    """Mark an annotation as reviewed, optionally setting event date.

    If event_date is set, skips unreviewed annotations whose note_date >= event_date,
    but only when at least one active SearchQuery has skip_after_event=True.

    Returns dict with annotation and skipped_count.
    """
    from app.annotations.query_service import get_annotation

    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        return None

    annotation.review_status = ReviewStatus.REVIEWED
    annotation.reviewed_by = user_id
    annotation.reviewed_at = now_utc()

    skipped_count = 0
    earlier_count = 0

    if event_date:
        annotation.event_date = event_date

        # Check project setting for skip_after_event_date
        project = await session.get(Project, project_id)
        skip_enabled = (project.settings or {}).get("skip_after_event_date",
                                                    False) if project else False

        # Fallback: also check per-query flag for backwards compatibility
        if not skip_enabled:
            skip_enabled = bool(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(SearchQuery)
                        .where(
                            col(SearchQuery.project_id) == project_id,
                            col(SearchQuery.is_active) == True,  # noqa: E712
                            col(SearchQuery.skip_after_event) == True,  # noqa: E712
                            col(SearchQuery.deleted_at).is_(None),
                        )
                    )
                ).scalar()
            )

        if skip_enabled:
            # Bulk-update annotations from notes on or after the event date to SKIPPED.
            # The WHERE review_status = UNREVIEWED predicate is both correct and race-safe:
            # it will only skip annotations that haven't already been acted on.
            notes_on_or_after_subq = (
                select(col(Note.id))
                .where(col(Note.note_date) >= event_date)
                .scalar_subquery()
            )
            skip_result = await session.execute(
                update(Annotation)
                .where(
                    col(Annotation.project_id) == project_id,
                    col(Annotation.patient_id) == annotation.patient_id,
                    col(Annotation.review_status) == ReviewStatus.UNREVIEWED,
                    col(Annotation.review_excluded).is_(False),
                    col(Annotation.id) != annotation_id,
                    col(Annotation.note_id).in_(notes_on_or_after_subq),
                )
                .values(review_status=ReviewStatus.SKIPPED)
                .execution_options(synchronize_session="fetch")
            )
            skipped_count = typing_cast(CursorResult, skip_result).rowcount

        # Count remaining unreviewed annotations from notes BEFORE the event date
        earlier_count = (
            await session.execute(
                select(func.count())
                .select_from(Annotation)
                .join(Note, col(Annotation.note_id) == col(Note.id))
                .where(
                    col(Annotation.project_id) == project_id,
                    col(Annotation.patient_id) == annotation.patient_id,
                    col(Annotation.review_status) == ReviewStatus.UNREVIEWED,
                    col(Annotation.review_excluded).is_(False),
                    col(Annotation.id) != annotation_id,
                    col(Note.note_date) < event_date,
                )
            )
        ).scalar() or 0

    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)
    await _check_patient_completion(session, project_id, annotation.patient_id, user_id)

    await log_action(
        session, project_id, AuditAction.ANNOTATION_REVIEWED,
        user_id=user_id, patient_id=annotation.patient_id,
        detail={"annotation_id": annotation_id, "skipped_count": skipped_count},
    )
    if event_date:
        await log_action(
            session, project_id, AuditAction.EVENT_DATE_SET,
            user_id=user_id, patient_id=annotation.patient_id,
            detail={"annotation_id": annotation_id, "event_date": event_date.isoformat()},
        )

    return {
        "annotation": annotation,
        "skipped_count": skipped_count,
        "earlier_count": earlier_count,
    }


async def skip_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
    user_id: str,
) -> Annotation | None:
    """Mark an annotation as skipped."""
    from app.annotations.query_service import get_annotation

    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        return None

    annotation.review_status = ReviewStatus.SKIPPED
    annotation.reviewed_by = user_id
    annotation.reviewed_at = now_utc()
    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)
    await _check_patient_completion(session, project_id, annotation.patient_id, user_id)

    await log_action(
        session, project_id, AuditAction.ANNOTATION_SKIPPED,
        user_id=user_id, patient_id=annotation.patient_id,
        detail={"annotation_id": annotation_id},
    )

    return annotation


async def get_next_patient_for_review(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> NextPatientResponse:
    """Find next unlocked patient with unreviewed annotations, lock them.

    Returns dict with patient info or all_complete flag.
    """
    active = await get_active_predictor_config(session, project_id)
    _reviewable = _reviewable_filter(active.id if active else None)
    has_unreviewed = (
        select(col(Annotation.patient_id))
        .where(
            col(Annotation.project_id) == project_id,
            col(Annotation.review_status) == ReviewStatus.UNREVIEWED,
            col(Annotation.review_excluded).is_(False),
            _reviewable,
        )
        .distinct()
        .scalar_subquery()
    )

    stmt = (
        select(Patient)
        .where(
            col(Patient.project_id) == project_id,
            col(Patient.id).in_(has_unreviewed),
            or_(col(Patient.locked_by).is_(None), col(Patient.locked_by) == user_id),
        )
        .order_by(col(Patient.created_at))
        .limit(1)
    )
    patient = (await session.execute(stmt)).scalar_one_or_none()

    if not patient:
        total_unreviewed = (
            await session.execute(
                select(func.count())
                .select_from(Annotation)
                .where(
                    col(Annotation.project_id) == project_id,
                    col(Annotation.review_status) == ReviewStatus.UNREVIEWED,
                    col(Annotation.review_excluded).is_(False),
                    _reviewable,
                )
            )
        ).scalar() or 0
        return NextPatientResponse(
            patient_id=None,
            patient_id_ext=None,
            total_annotations=0,
            unreviewed_annotations=0,
            all_complete=total_unreviewed == 0,
        )

    patient.locked_by = user_id
    patient.locked_at = now_utc()
    if patient.status not in (PatientStatus.REVIEWING, PatientStatus.REVIEWED):
        patient.status = PatientStatus.REVIEWING
    session.add(patient)
    await session.commit()

    await log_action(
        session, project_id, AuditAction.PATIENT_LOCKED,
        user_id=user_id, patient_id=patient.id,
    )

    total = (
        await session.execute(
            select(func.count())
            .select_from(Annotation)
            .where(
                col(Annotation.project_id) == project_id,
                col(Annotation.patient_id) == patient.id,
            )
        )
    ).scalar() or 0

    unreviewed = (
        await session.execute(
            select(func.count())
            .select_from(Annotation)
            .where(
                col(Annotation.project_id) == project_id,
                col(Annotation.patient_id) == patient.id,
                col(Annotation.review_status) == ReviewStatus.UNREVIEWED,
            )
        )
    ).scalar() or 0

    return NextPatientResponse(
        patient_id=patient.id,
        patient_id_ext=patient.patient_id_ext,
        total_annotations=total,
        unreviewed_annotations=unreviewed,
        all_complete=False,
    )


async def get_patient_annotations(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
) -> list[dict]:
    """All annotations for a patient, sorted by note_date, then sentence position."""
    from app.nlp.models import Sentence

    active = await get_active_predictor_config(session, project_id)
    active_id = active.id if active else None

    stmt = (
        select(
            Annotation, col(Note.note_date), col(Note.text_id),
            col(Sentence.sentence_number), col(Note.text),
        )
        .join(Note, col(Annotation.note_id) == col(Note.id))
        .outerjoin(Sentence, col(Annotation.sentence_id) == col(Sentence.id))
        .where(
            col(Annotation.project_id) == project_id,
            col(Annotation.patient_id) == patient_id,
            col(Annotation.review_excluded).is_(False),
            _reviewable_filter(active_id),
        )
        .order_by(
            col(Note.note_date).asc().nullslast(),
            col(Note.id),
            col(Sentence.sentence_number).asc().nullslast(),
        )
    )
    rows = (await session.execute(stmt)).all()

    if not rows:
        predictions = {}
    else:
        pred_stmt = select(AnnotationPrediction).where(
            col(AnnotationPrediction.project_id) == project_id,
            col(AnnotationPrediction.annotation_id).in_([r[0].id for r in rows]),
        )
        # Only the active predictor's verdict is authoritative.
        if active_id is not None:
            pred_stmt = pred_stmt.where(
                col(AnnotationPrediction.predictor_config_id) == active_id
            )
        predictions = {
            p.annotation_id: p
            for p in (await session.execute(pred_stmt)).scalars()
        }

    results = []
    for annotation, note_date, text_id, sentence_number, note_text in rows:
        sentence_text = annotation.sentence_text

        # If sentence_text is the LLM reasoning (fallback from older pipeline),
        # replace with actual note text excerpt
        if (
            sentence_text
            and annotation.reasoning
            and sentence_text == annotation.reasoning
            and note_text
        ):
            sentence_text = note_text[:1000]

        prediction = predictions.get(annotation.id)

        results.append({
            "id": annotation.id,
            "project_id": annotation.project_id,
            "patient_id": annotation.patient_id,
            "note_id": annotation.note_id,
            "sentence_id": annotation.sentence_id,
            "sentence_text": sentence_text,
            "matched_tokens": annotation.matched_tokens,
            "is_negated": annotation.is_negated,
            "review_excluded": annotation.review_excluded,
            "manual_review_override": annotation.manual_review_override,
            "token": annotation.token,
            "note_start_index": annotation.note_start_index,
            "note_end_index": annotation.note_end_index,
            "sentence_start": annotation.sentence_start,
            "sentence_end": annotation.sentence_end,
            "text_date": annotation.text_date,
            "predicted_score": (
                prediction.predicted_score if prediction else annotation.predicted_score
            ),
            "predicted_label": (
                prediction.predicted_label if prediction else annotation.predicted_label
            ),
            "predictor_model": (
                prediction.predictor_model if prediction else annotation.predictor_model
            ),
            "reasoning": prediction.reasoning if prediction else annotation.reasoning,
            "review_status": annotation.review_status,
            "reviewed_by": annotation.reviewed_by,
            "reviewed_at": annotation.reviewed_at,
            "event_date": annotation.event_date,
            "created_at": annotation.created_at,
            "note_date": note_date,
            "note_text_id": text_id,
            "sentence_number": (
                annotation.sentence_number if annotation.sentence_number is not None
                else sentence_number
            ),
        })
    return results


async def unlock_patient(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    user_id: str,
) -> None:
    """Clear locked_by/locked_at. Only the locking user can unlock."""
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.id) == patient_id,
                col(Patient.project_id) == project_id,
            )
        )
    ).scalar_one_or_none()

    if not patient:
        return
    if patient.locked_by != user_id:
        return

    patient.locked_by = None
    patient.locked_at = None
    session.add(patient)
    await session.commit()

    await log_action(
        session, project_id, AuditAction.PATIENT_UNLOCKED,
        user_id=user_id, patient_id=patient_id,
    )

    # A predictor run can hide the last unreviewed annotations while a reviewer holds the lock
    # (the completion pass skips locked patients), so close the patient once the lock is gone.
    if patient.status == PatientStatus.REVIEWING:
        await _check_patient_completion(session, project_id, patient_id, user_id)


async def delete_event_date(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
    user_id: str,
) -> dict | None:
    """Clear event_date, revert SKIPPED annotations for same patient to UNREVIEWED."""
    from app.annotations.query_service import get_annotation

    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation or not annotation.event_date:
        return None

    annotation.event_date = None
    annotation.review_status = ReviewStatus.UNREVIEWED
    annotation.reviewed_by = None
    annotation.reviewed_at = None

    stmt = select(Annotation).where(
        col(Annotation.project_id) == project_id,
        col(Annotation.patient_id) == annotation.patient_id,
        col(Annotation.review_status) == ReviewStatus.SKIPPED,
    )
    reverted_count = 0
    for ann in (await session.execute(stmt)).scalars().all():
        ann.review_status = ReviewStatus.UNREVIEWED
        reverted_count += 1

    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)

    await _check_patient_completion(session, project_id, annotation.patient_id, user_id)
    patient = (
        await session.execute(
            select(Patient).where(col(Patient.id) == annotation.patient_id)
        )
    ).scalar_one_or_none()
    if patient and patient.status == PatientStatus.REVIEWED:
        patient.status = PatientStatus.REVIEWING
        patient.review_source = None
        patient.review_reason = None
        patient.reviewed_by = None
        patient.reviewed_at = None
        session.add(patient)
        await session.commit()

    await log_action(
        session, project_id, AuditAction.EVENT_DATE_DELETED,
        user_id=user_id, patient_id=annotation.patient_id,
        detail={"annotation_id": annotation_id, "reverted_count": reverted_count},
    )

    return {"annotation": annotation, "reverted_count": reverted_count}


async def get_patient_review_stats(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
) -> PatientReviewStats:
    """Return review stats for a specific patient."""
    base = (
        select(func.count())
        .select_from(Annotation)
        .where(
            col(Annotation.project_id) == project_id,
            col(Annotation.patient_id) == patient_id,
        )
    )

    total = (await session.execute(base)).scalar() or 0
    unreviewed = (
        await session.execute(
            base.where(col(Annotation.review_status) == ReviewStatus.UNREVIEWED)
        )
    ).scalar() or 0
    reviewed = (
        await session.execute(
            base.where(col(Annotation.review_status) == ReviewStatus.REVIEWED)
        )
    ).scalar() or 0
    skipped = (
        await session.execute(
            base.where(col(Annotation.review_status) == ReviewStatus.SKIPPED)
        )
    ).scalar() or 0

    event_annotation = (
        await session.execute(
            select(Annotation).where(
                col(Annotation.project_id) == project_id,
                col(Annotation.patient_id) == patient_id,
                col(Annotation.event_date).isnot(None),
            ).limit(1)
        )
    ).scalar_one_or_none()

    return PatientReviewStats(
        total=total,
        unreviewed=unreviewed,
        reviewed=reviewed,
        skipped=skipped,
        current_event_date=event_annotation.event_date if event_annotation else None,
        event_annotation_id=event_annotation.id if event_annotation else None,
    )


async def reopen_patient(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    user_id: str,
) -> bool:
    """Restore all stored annotations for explicit human review."""
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.id) == patient_id,
                col(Patient.project_id) == project_id,
            )
        )
    ).scalar_one_or_none()

    if not patient or patient.status != PatientStatus.REVIEWED:
        return False

    stmt = select(Annotation).where(
        col(Annotation.project_id) == project_id,
        col(Annotation.patient_id) == patient_id,
    )
    annotations = list((await session.execute(stmt)).scalars().all())
    if not annotations:
        raise ReopenConflictError(
            "No stored annotations are available to reopen. Run a new search first."
        )
    for ann in annotations:
        ann.review_excluded = False
        ann.manual_review_override = True
        ann.review_status = ReviewStatus.UNREVIEWED
        ann.reviewed_by = None
        ann.reviewed_at = None
        ann.event_date = None

    patient.status = PatientStatus.REVIEWING
    patient.review_source = None
    patient.review_reason = None
    patient.reviewed_by = None
    patient.reviewed_at = None
    patient.updated_at = now_utc()
    session.add(patient)

    await session.commit()

    await log_action(
        session, project_id, AuditAction.PATIENT_REOPENED,
        user_id=user_id, patient_id=patient_id,
    )

    return True
