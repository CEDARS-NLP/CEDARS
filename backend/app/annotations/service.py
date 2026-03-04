"""Annotation service: bulk prediction runs, review operations."""

import logging
from datetime import UTC, datetime

import tiktoken
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.audit.models import AuditAction
from app.audit.service import log_action
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.models import SearchQuery, Sentence
from app.predictors.base import PredictionResult, PredictorError
from app.predictors.factory import create_predictor
from app.predictors.llm import SYSTEM_PROMPT
from app.predictors.models import PredictorConfig

logger = logging.getLogger(__name__)


# ── Bulk prediction run ──────────────────────────────────────────


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


# ── Review operations ────────────────────────────────────────────


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


async def get_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
) -> Annotation | None:
    stmt = select(Annotation).where(
        Annotation.id == annotation_id,
        Annotation.project_id == project_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_annotations(
    session: AsyncSession,
    project_id: str,
    status: str | None = None,
    patient_id: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Annotation]:
    """List annotations with optional filtering."""
    stmt = select(Annotation).where(Annotation.project_id == project_id)

    if status:
        stmt = stmt.where(Annotation.review_status == status)
    if patient_id:
        stmt = stmt.where(Annotation.patient_id == patient_id)

    stmt = stmt.order_by(Annotation.created_at).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_next_unreviewed(
    session: AsyncSession,
    project_id: str,
    patient_id: str | None = None,
) -> Annotation | None:
    """Get the next unreviewed annotation for review."""
    stmt = select(Annotation).where(
        Annotation.project_id == project_id,
        Annotation.review_status == ReviewStatus.UNREVIEWED,
    )
    if patient_id:
        stmt = stmt.where(Annotation.patient_id == patient_id)
    stmt = stmt.order_by(Annotation.created_at).limit(1)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


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
    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        return None

    annotation.review_status = ReviewStatus.REVIEWED
    annotation.reviewed_by = user_id
    annotation.reviewed_at = datetime.now(UTC)

    skipped_count = 0

    if event_date:
        annotation.event_date = event_date

        # Check if any active query has skip_after_event
        has_skip = (
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
        ).scalar() or 0

        if has_skip > 0:
            skip_stmt = (
                select(Annotation)
                .join(Note, Annotation.note_id == Note.id)
                .where(
                    Annotation.project_id == project_id,
                    Annotation.patient_id == annotation.patient_id,
                    Annotation.review_status == ReviewStatus.UNREVIEWED,
                    Annotation.id != annotation_id,
                    Note.note_date >= event_date,
                )
            )
            for ann in (await session.execute(skip_stmt)).scalars().all():
                ann.review_status = ReviewStatus.SKIPPED
                skipped_count += 1

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

    return {"annotation": annotation, "skipped_count": skipped_count}


async def skip_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str,
    user_id: str,
) -> Annotation | None:
    """Mark an annotation as skipped."""
    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation:
        return None

    annotation.review_status = ReviewStatus.SKIPPED
    annotation.reviewed_by = user_id
    annotation.reviewed_at = datetime.now(UTC)
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


async def get_annotation_stats(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Get annotation review statistics for the project."""
    base = select(func.count()).select_from(Annotation).where(
        Annotation.project_id == project_id
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
    events_found = (
        await session.execute(
            base.where(Annotation.event_date.isnot(None))
        )
    ).scalar() or 0

    return {
        "total": total,
        "unreviewed": unreviewed,
        "reviewed": reviewed,
        "skipped": skipped,
        "events_found": events_found,
        "is_complete": total > 0 and unreviewed == 0,
    }


async def get_note_context(
    session: AsyncSession,
    note_id: str,
) -> dict | None:
    """Get full note text and all sentences for annotation context display."""
    note = (await session.execute(select(Note).where(Note.id == note_id))).scalar_one_or_none()
    if not note:
        return None

    patient = (
        await session.execute(select(Patient).where(Patient.id == note.patient_id))
    ).scalar_one_or_none()

    sentences = (
        await session.execute(
            select(Sentence)
            .where(Sentence.note_id == note_id)
            .order_by(Sentence.sentence_number)
        )
    ).scalars().all()

    return {
        "note_id": note.id,
        "patient_id": note.patient_id,
        "patient_id_ext": patient.patient_id_ext if patient else note.patient_id,
        "text": note.text,
        "text_id": note.text_id,
        "note_date": note.note_date.isoformat() if note.note_date else None,
        "sentences": [
            {
                "id": s.id,
                "text": s.text,
                "start_pos": s.start_pos,
                "end_pos": s.end_pos,
                "is_target": s.is_target,
                "is_negated": s.is_negated,
                "matched_tokens": s.matched_tokens,
            }
            for s in sentences
        ],
    }


# ── Patient-first review operations ──────────────────────────────


async def get_next_patient_for_review(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> dict:
    """Find next unlocked patient with unreviewed annotations, lock them.

    Returns dict with patient info or all_complete flag.
    """
    # Subquery: patients with at least one UNREVIEWED annotation
    has_unreviewed = (
        select(Annotation.patient_id)
        .where(
            Annotation.project_id == project_id,
            Annotation.review_status == ReviewStatus.UNREVIEWED,
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
        # Check if there are any unreviewed at all (might all be locked by others)
        total_unreviewed = (
            await session.execute(
                select(func.count())
                .select_from(Annotation)
                .where(
                    Annotation.project_id == project_id,
                    Annotation.review_status == ReviewStatus.UNREVIEWED,
                )
            )
        ).scalar() or 0
        return {
            "patient_id": None,
            "patient_id_ext": None,
            "total_annotations": 0,
            "unreviewed_annotations": 0,
            "all_complete": total_unreviewed == 0,
        }

    # Lock the patient
    patient.locked_by = user_id
    patient.locked_at = datetime.now(UTC)
    if patient.status not in (PatientStatus.REVIEWING, PatientStatus.REVIEWED):
        patient.status = PatientStatus.REVIEWING
    session.add(patient)
    await session.commit()

    await log_action(
        session, project_id, AuditAction.PATIENT_LOCKED,
        user_id=user_id, patient_id=patient.id,
    )

    # Count annotations
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

    return {
        "patient_id": patient.id,
        "patient_id_ext": patient.patient_id_ext,
        "total_annotations": total,
        "unreviewed_annotations": unreviewed,
        "all_complete": False,
    }


async def get_patient_annotations(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
) -> list[dict]:
    """All annotations for a patient, sorted by note_date, then sentence position."""
    stmt = (
        select(Annotation, Note.note_date, Note.text_id, Sentence.sentence_number)
        .join(Note, Annotation.note_id == Note.id)
        .join(Sentence, Annotation.sentence_id == Sentence.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.patient_id == patient_id,
        )
        .order_by(
            Note.note_date.asc().nullslast(),
            Note.id,
            Sentence.sentence_number.asc(),
        )
    )
    rows = (await session.execute(stmt)).all()

    results = []
    for annotation, note_date, text_id, sentence_number in rows:
        results.append({
            "id": annotation.id,
            "project_id": annotation.project_id,
            "patient_id": annotation.patient_id,
            "note_id": annotation.note_id,
            "sentence_id": annotation.sentence_id,
            "sentence_text": annotation.sentence_text,
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
    annotation = await get_annotation(session, project_id, annotation_id)
    if not annotation or not annotation.event_date:
        return None

    # Clear event date and reset this annotation
    annotation.event_date = None
    annotation.review_status = ReviewStatus.UNREVIEWED
    annotation.reviewed_by = None
    annotation.reviewed_at = None

    # Revert all SKIPPED annotations for this patient to UNREVIEWED
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

    # Patient should no longer be REVIEWED
    await _check_patient_completion(session, project_id, annotation.patient_id)
    # If patient was REVIEWED, revert to REVIEWING
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
) -> dict:
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

    # Find annotation with event_date set
    event_annotation = (
        await session.execute(
            select(Annotation).where(
                Annotation.project_id == project_id,
                Annotation.patient_id == patient_id,
                Annotation.event_date.isnot(None),
            ).limit(1)
        )
    ).scalar_one_or_none()

    return {
        "total": total,
        "unreviewed": unreviewed,
        "reviewed": reviewed,
        "skipped": skipped,
        "current_event_date": event_annotation.event_date if event_annotation else None,
        "event_annotation_id": event_annotation.id if event_annotation else None,
    }


# ── Token estimation ─────────────────────────────────────────────


async def estimate_bulk_predictions(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Estimate token usage for bulk predictions on unannotated target sentences."""
    # Find target sentences without annotations
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
