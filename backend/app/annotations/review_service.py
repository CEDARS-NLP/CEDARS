"""Review service: patient-first annotation review, skip, event dates."""

import logging
from datetime import datetime

from sqlalchemy import func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.annotations.schemas import NextPatientResponse, PatientReviewStats
from app.audit.models import AuditAction
from app.audit.service import log_action
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.models import SearchQuery
from app.projects.models import Project

logger = logging.getLogger(__name__)


async def _check_patient_completion(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
) -> None:
    """Mark patient as REVIEWED if all their annotations are reviewed/skipped."""
    unreviewed_count = (
        await session.execute(
            select(func.count())
            .select_from(Annotation)
            .where(
                Annotation.project_id == project_id,
                Annotation.patient_id == patient_id,
                Annotation.review_status == ReviewStatus.UNREVIEWED,
            )
        )
    ).scalar() or 0

    if unreviewed_count == 0:
        patient = (
            await session.execute(
                select(Patient).where(Patient.id == patient_id)
            )
        ).scalar_one_or_none()
        if patient and patient.status != PatientStatus.REVIEWED:
            patient.status = PatientStatus.REVIEWED
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
        skip_enabled = (project.settings or {}).get("skip_after_event_date", False) if project else False

        # Fallback: also check per-query flag for backwards compatibility
        if not skip_enabled:
            skip_enabled = bool(
                (
                    await session.execute(
                        select(func.count())
                        .select_from(SearchQuery)
                        .where(
                            SearchQuery.project_id == project_id,
                            SearchQuery.is_active == True,  # noqa: E712
                            SearchQuery.skip_after_event == True,  # noqa: E712
                            SearchQuery.deleted_at.is_(None),
                        )
                    )
                ).scalar()
            )

        if skip_enabled:
            # Bulk-update annotations from notes on or after the event date to SKIPPED.
            # The WHERE review_status = UNREVIEWED predicate is both correct and race-safe:
            # it will only skip annotations that haven't already been acted on.
            notes_on_or_after_subq = (
                select(Note.id)
                .where(Note.note_date >= event_date)
                .scalar_subquery()
            )
            skip_result = await session.execute(
                update(Annotation)
                .where(
                    Annotation.project_id == project_id,
                    Annotation.patient_id == annotation.patient_id,
                    Annotation.review_status == ReviewStatus.UNREVIEWED,
                    Annotation.id != annotation_id,
                    Annotation.note_id.in_(notes_on_or_after_subq),
                )
                .values(review_status=ReviewStatus.SKIPPED)
                .execution_options(synchronize_session="fetch")
            )
            skipped_count = skip_result.rowcount

        # Count remaining unreviewed annotations from notes BEFORE the event date
        earlier_count = (
            await session.execute(
                select(func.count())
                .select_from(Annotation)
                .join(Note, Annotation.note_id == Note.id)
                .where(
                    Annotation.project_id == project_id,
                    Annotation.patient_id == annotation.patient_id,
                    Annotation.review_status == ReviewStatus.UNREVIEWED,
                    Annotation.id != annotation_id,
                    Note.note_date < event_date,
                )
            )
        ).scalar() or 0

    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)
    await _check_patient_completion(session, project_id, annotation.patient_id)

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
    await _check_patient_completion(session, project_id, annotation.patient_id)

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
    has_unreviewed = (
        select(Annotation.patient_id)
        .where(
            Annotation.project_id == project_id,
            Annotation.review_status == ReviewStatus.UNREVIEWED,
            Annotation.predicted_label == 1,
        )
        .distinct()
        .scalar_subquery()
    )

    stmt = (
        select(Patient)
        .where(
            Patient.project_id == project_id,
            Patient.id.in_(has_unreviewed),
            or_(Patient.locked_by.is_(None), Patient.locked_by == user_id),
        )
        .order_by(Patient.created_at)
        .limit(1)
    )
    patient = (await session.execute(stmt)).scalar_one_or_none()

    if not patient:
        total_unreviewed = (
            await session.execute(
                select(func.count())
                .select_from(Annotation)
                .where(
                    Annotation.project_id == project_id,
                    Annotation.review_status == ReviewStatus.UNREVIEWED,
                    Annotation.predicted_label == 1,
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
                Annotation.project_id == project_id,
                Annotation.patient_id == patient.id,
            )
        )
    ).scalar() or 0

    unreviewed = (
        await session.execute(
            select(func.count())
            .select_from(Annotation)
            .where(
                Annotation.project_id == project_id,
                Annotation.patient_id == patient.id,
                Annotation.review_status == ReviewStatus.UNREVIEWED,
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

    stmt = (
        select(
            Annotation, Note.note_date, Note.text_id,
            Sentence.sentence_number, Note.text,
        )
        .join(Note, Annotation.note_id == Note.id)
        .outerjoin(Sentence, Annotation.sentence_id == Sentence.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.patient_id == patient_id,
            Annotation.predicted_label == 1,
        )
        .order_by(
            Note.note_date.asc().nullslast(),
            Note.id,
            Sentence.sentence_number.asc().nullslast(),
        )
    )
    rows = (await session.execute(stmt)).all()

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

        results.append({
            "id": annotation.id,
            "project_id": annotation.project_id,
            "patient_id": annotation.patient_id,
            "note_id": annotation.note_id,
            "sentence_id": annotation.sentence_id,
            "sentence_text": sentence_text,
            "matched_tokens": annotation.matched_tokens,
            "is_negated": annotation.is_negated,
            "predicted_score": annotation.predicted_score,
            "predicted_label": annotation.predicted_label,
            "predictor_model": annotation.predictor_model,
            "reasoning": annotation.reasoning,
            "review_status": annotation.review_status,
            "reviewed_by": annotation.reviewed_by,
            "reviewed_at": annotation.reviewed_at,
            "event_date": annotation.event_date,
            "created_at": annotation.created_at,
            "note_date": note_date,
            "note_text_id": text_id,
            "sentence_number": sentence_number,
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
                Patient.id == patient_id,
                Patient.project_id == project_id,
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
        Annotation.project_id == project_id,
        Annotation.patient_id == annotation.patient_id,
        Annotation.review_status == ReviewStatus.SKIPPED,
    )
    reverted_count = 0
    for ann in (await session.execute(stmt)).scalars().all():
        ann.review_status = ReviewStatus.UNREVIEWED
        reverted_count += 1

    session.add(annotation)
    await session.commit()
    await session.refresh(annotation)

    await _check_patient_completion(session, project_id, annotation.patient_id)
    patient = (
        await session.execute(select(Patient).where(Patient.id == annotation.patient_id))
    ).scalar_one_or_none()
    if patient and patient.status == PatientStatus.REVIEWED:
        patient.status = PatientStatus.REVIEWING
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
            Annotation.project_id == project_id,
            Annotation.patient_id == patient_id,
        )
    )

    total = (await session.execute(base)).scalar() or 0
    unreviewed = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.UNREVIEWED)
        )
    ).scalar() or 0
    reviewed = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.REVIEWED)
        )
    ).scalar() or 0
    skipped = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.SKIPPED)
        )
    ).scalar() or 0

    event_annotation = (
        await session.execute(
            select(Annotation).where(
                Annotation.project_id == project_id,
                Annotation.patient_id == patient_id,
                Annotation.event_date.isnot(None),
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
    """Reopen a REVIEWED patient: revert all annotations to UNREVIEWED."""
    patient = (
        await session.execute(
            select(Patient).where(
                Patient.id == patient_id,
                Patient.project_id == project_id,
            )
        )
    ).scalar_one_or_none()

    if not patient or patient.status != PatientStatus.REVIEWED:
        return False

    patient.status = PatientStatus.REVIEWING
    session.add(patient)

    stmt = select(Annotation).where(
        Annotation.project_id == project_id,
        Annotation.patient_id == patient_id,
    )
    for ann in (await session.execute(stmt)).scalars().all():
        ann.review_status = ReviewStatus.UNREVIEWED
        ann.reviewed_by = None
        ann.reviewed_at = None
        ann.event_date = None

    await session.commit()

    await log_action(
        session, project_id, AuditAction.PATIENT_REOPENED,
        user_id=user_id, patient_id=patient_id,
    )

    return True
