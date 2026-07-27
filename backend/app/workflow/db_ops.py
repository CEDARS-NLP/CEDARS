"""Async SQL ports of the cedars/app/db.py helpers used by the v1 workflow.

This module is the v2 equivalent of v1's monolithic ``db.py`` data layer, scoped
to the functions the linear workflow (NLP processing, adjudication, results)
relies on. Each function mirrors the behaviour of its v1 counterpart; the only
changes are MongoDB → async SQLAlchemy and Mongo ``ObjectId`` → UUID strings.

Review-status translation
-------------------------
v1 stored ``reviewed`` as an int (0/1/2). v2 stores ``Annotation.review_status``
as the string :class:`~app.annotations.models.ReviewStatus` enum. The
:class:`AdjudicationHandler` still works in the v1 int space, so helpers here
translate at the boundary via :func:`review_status_to_int`.
"""

import logging

from sqlalchemy import delete, func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationToken, ReviewStatus
from app.common.utils import now_utc
from app.connectors.models import Note, NoteTag, Patient, PatientStatus
from app.nlp.models import NotePrediction, SearchQuery
from app.workflow.models import PatientReviewResult

logger = logging.getLogger(__name__)

# v1 ReviewStatus int values (cedars_enums): UNREVIEWED=0, REVIEWED=1, SKIPPED=2
_STR_TO_INT = {
    ReviewStatus.UNREVIEWED.value: 0,
    ReviewStatus.REVIEWED.value: 1,
    ReviewStatus.SKIPPED.value: 2,
}
_INT_TO_STATUS = {
    0: ReviewStatus.UNREVIEWED,
    1: ReviewStatus.REVIEWED,
    2: ReviewStatus.SKIPPED,
}


def review_status_to_int(value) -> int:
    """Normalize a stored review_status (enum or str) to the v1 int value."""
    if isinstance(value, ReviewStatus):
        value = value.value
    return _STR_TO_INT.get(value, 0)


def int_to_review_status(value: int) -> ReviewStatus:
    """Map a v1 int review status back to the v2 ReviewStatus enum."""
    return _INT_TO_STATUS[int(value)]


# ── Search query ─────────────────────────────────────────────────


async def get_active_search_query(session: AsyncSession, project_id: str) -> SearchQuery | None:
    """Return the current active search query for a project (v1 ``get_search_query``).

    v1 keeps a single ``current`` query in the QUERY collection; the v2 analog is
    the most recent non-deleted active ``SearchQuery``.
    """
    result = await session.execute(
        select(SearchQuery)
        .where(
            SearchQuery.project_id == project_id,
            SearchQuery.is_active.is_(True),
            SearchQuery.deleted_at.is_(None),
        )
        .order_by(SearchQuery.created_at.desc())
    )
    return result.scalars().first()


# ── NLP processing helpers ───────────────────────────────────────


async def get_documents_to_annotate(
    session: AsyncSession, project_id: str, patient_id: str | None = None
) -> list[Note]:
    """Return notes with no annotations yet and not marked reviewed.

    Faithful port of v1 ``get_documents_to_annotate``: notes whose annotation
    set is empty (``annotations == []``) and ``reviewed != True``, optionally
    filtered to a single patient.
    """
    ann_exists = (
        select(Annotation.id).where(Annotation.note_id == Note.id).exists()
    )
    stmt = (
        select(Note)
        .where(
            Note.project_id == project_id,
            Note.deleted_at.is_(None),
            Note.reviewed.is_(False),
            ~ann_exists,
        )
        .order_by(Note.created_at.asc())
    )
    if patient_id is not None:
        stmt = stmt.where(Note.patient_id == patient_id)

    result = await session.execute(stmt)
    return list(result.scalars().all())


async def mark_note_reviewed(session: AsyncSession, note_id: str, reviewed_by: str) -> None:
    """Mark a note as reviewed (v1 ``mark_note_reviewed``)."""
    await session.execute(
        update(Note)
        .where(Note.id == note_id)
        .values(reviewed=True, reviewed_by=reviewed_by)
    )


async def mark_patient_reviewed(
    session: AsyncSession, project_id: str, patient_id: str, reviewed_by: str
) -> None:
    """Mark a patient reviewed and refresh their results row (v1 ``mark_patient_reviewed``).

    v1 sets ``reviewed`` + ``reviewed_by`` on the patient and then calls
    ``upsert_patient_records``. The v2 patient's ``status`` enum encodes reviewed
    state (``REVIEWED``).
    """
    patient = await session.get(Patient, patient_id)
    if patient is None:
        return
    patient.status = PatientStatus.REVIEWED
    patient.reviewed_by = reviewed_by
    session.add(patient)
    await upsert_patient_result(session, project_id, patient_id)


async def get_annotated_notes_for_patient(
    session: AsyncSession, project_id: str, patient_id: str
) -> list[str]:
    """List note IDs (dedup, ordered) that have keyword annotations (v1 ``get_annotated_notes_for_patient``)."""
    result = await session.execute(
        select(Annotation.note_id)
        .where(Annotation.project_id == project_id, Annotation.patient_id == patient_id)
        .order_by(Annotation.text_date.asc(), Annotation.note_id.asc())
    )
    note_ids = [row[0] for row in result.all()]
    # Preserve first-seen order while removing duplicates (dict.fromkeys, as in v1).
    return list(dict.fromkeys(note_ids))


async def update_annotation_reviewed(session: AsyncSession, note_id: str) -> int:
    """Mark all annotations for a note as reviewed; return count (v1 ``update_annotation_reviewed``)."""
    result = await session.execute(
        update(Annotation)
        .where(Annotation.note_id == note_id)
        .values(review_status=ReviewStatus.REVIEWED)
    )
    return result.rowcount or 0


# ── Predictions (PINES collection port) ──────────────────────────


async def get_note_prediction(
    session: AsyncSession, note_id: str, predictor_name: str = "PINES"
) -> float | None:
    """Return the stored prediction score for a note (v1 ``get_note_prediction_from_db``)."""
    result = await session.execute(
        select(NotePrediction.score).where(
            NotePrediction.note_id == note_id,
            NotePrediction.predictor_name == predictor_name,
        )
    )
    score = result.scalars().first()
    if score is not None:
        return round(score, 2)
    return None


async def save_note_prediction(
    session: AsyncSession,
    project_id: str,
    note_id: str,
    predictor_name: str,
    score: float,
) -> None:
    """Insert or update a note's prediction score (v1 ``predict_and_save`` persistence)."""
    existing = await session.execute(
        select(NotePrediction).where(
            NotePrediction.note_id == note_id,
            NotePrediction.predictor_name == predictor_name,
        )
    )
    row = existing.scalars().first()
    if row is None:
        session.add(
            NotePrediction(
                project_id=project_id,
                note_id=note_id,
                predictor_name=predictor_name,
                score=score,
            )
        )
    else:
        row.score = score
        session.add(row)


# ── Results (RESULTS collection port) ────────────────────────────


async def upsert_patient_result(
    session: AsyncSession, project_id: str, patient_id: str
) -> None:
    """Rebuild the denormalized results row for a patient (v1 ``upsert_patient_records``).

    Aggregates the columns v1's download emits: note counts, sentence counts,
    first/last note date, max prediction score, event date, and comments.
    """
    patient = await session.get(Patient, patient_id)
    if patient is None:
        return

    total_notes = (
        await session.execute(
            select(func.count(Note.id)).where(
                Note.patient_id == patient_id, Note.deleted_at.is_(None)
            )
        )
    ).scalar_one()
    reviewed_notes = (
        await session.execute(
            select(func.count(Note.id)).where(
                Note.patient_id == patient_id,
                Note.deleted_at.is_(None),
                Note.reviewed.is_(True),
            )
        )
    ).scalar_one()

    # Sentences == non-negated annotations (v1 counts annotation sentences).
    total_sentences = (
        await session.execute(
            select(func.count(Annotation.id)).where(
                Annotation.patient_id == patient_id,
                Annotation.is_negated.is_(False),
            )
        )
    ).scalar_one()
    reviewed_sentences = (
        await session.execute(
            select(func.count(Annotation.id)).where(
                Annotation.patient_id == patient_id,
                Annotation.is_negated.is_(False),
                Annotation.review_status == ReviewStatus.REVIEWED,
            )
        )
    ).scalar_one()

    date_bounds = (
        await session.execute(
            select(func.min(Note.note_date), func.max(Note.note_date)).where(
                Note.patient_id == patient_id, Note.deleted_at.is_(None)
            )
        )
    ).one()
    first_note_date, last_note_date = date_bounds

    max_score = (
        await session.execute(
            select(func.max(NotePrediction.score))
            .join(Note, Note.id == NotePrediction.note_id)
            .where(Note.patient_id == patient_id)
        )
    ).scalar_one_or_none()

    existing = (
        await session.execute(
            select(PatientReviewResult).where(
                PatientReviewResult.project_id == project_id,
                PatientReviewResult.patient_id == patient_id,
            )
        )
    ).scalars().first()

    if existing is None:
        existing = PatientReviewResult(project_id=project_id, patient_id=patient_id)

    existing.event_date = patient.event_date
    existing.first_note_date = first_note_date
    existing.last_note_date = last_note_date
    existing.total_notes = total_notes
    existing.reviewed_notes = reviewed_notes
    existing.total_sentences = total_sentences
    existing.reviewed_sentences = reviewed_sentences
    existing.max_score = max_score
    existing.comments = patient.comments or ""
    existing.reviewed_by = patient.reviewed_by
    session.add(existing)


# ── Patient selection (adjudication) ─────────────────────────────


async def get_patient_ids(session: AsyncSession, project_id: str) -> list[str]:
    """Return IDs of un-reviewed, unlocked patients in upload order (v1 ``get_patient_ids``)."""
    result = await session.execute(
        select(Patient.id)
        .where(
            Patient.project_id == project_id,
            Patient.deleted_at.is_(None),
            Patient.status != PatientStatus.REVIEWED,
            Patient.locked_by.is_(None),
        )
        .order_by(Patient.created_at.asc())
    )
    return list(result.scalars().all())


async def get_patients_to_annotate(session: AsyncSession, project_id: str) -> str | None:
    """Return the next patient with unreviewed, non-negated annotations (v1 ``get_patients_to_annotate``)."""
    ann_exists = (
        select(Annotation.id)
        .where(
            Annotation.patient_id == Patient.id,
            Annotation.review_status == ReviewStatus.UNREVIEWED,
            Annotation.is_negated.is_(False),
        )
        .exists()
    )
    result = await session.execute(
        select(Patient.id)
        .where(
            Patient.project_id == project_id,
            Patient.deleted_at.is_(None),
            Patient.status != PatientStatus.REVIEWED,
            Patient.locked_by.is_(None),
            ann_exists,
        )
        .order_by(Patient.created_at.asc())
        .limit(1)
    )
    return result.scalars().first()


async def get_patient(session: AsyncSession, patient_id: str) -> Patient | None:
    """Return a patient by internal ID."""
    return await session.get(Patient, patient_id)


async def get_patient_by_ext_id(
    session: AsyncSession, project_id: str, patient_id_ext: str
) -> Patient | None:
    """Look up a patient by the external/uploaded patient ID (v1 ``get_patient_by_id``)."""
    result = await session.execute(
        select(Patient).where(
            Patient.project_id == project_id,
            Patient.patient_id_ext == patient_id_ext,
            Patient.deleted_at.is_(None),
        )
    )
    return result.scalars().first()


# ── Annotation retrieval for adjudication ────────────────────────


async def get_all_annotations_for_patient(
    session: AsyncSession, project_id: str, patient_id: str
) -> list[Annotation]:
    """All non-negated annotations for a patient, ordered as v1 (``get_all_annotations_for_patient``).

    v1 orders by (text_date, note_id, note_start_index); the sentence-level v2
    row uses ``sentence_start`` for the intra-note position.
    """
    result = await session.execute(
        select(Annotation)
        .where(
            Annotation.project_id == project_id,
            Annotation.patient_id == patient_id,
            Annotation.is_negated.is_(False),
        )
        .order_by(
            Annotation.text_date.asc(),
            Annotation.note_id.asc(),
            Annotation.sentence_start.asc(),
        )
    )
    return list(result.scalars().all())


async def get_tokens_map(
    session: AsyncSession, annotation_ids: list[str]
) -> dict[str, list[dict]]:
    """Return {annotation_id: [token dicts]} for building handler annotation dicts."""
    if not annotation_ids:
        return {}
    result = await session.execute(
        select(AnnotationToken).where(AnnotationToken.annotation_id.in_(annotation_ids))
    )
    token_map: dict[str, list[dict]] = {}
    for tok in result.scalars().all():
        token_map.setdefault(tok.annotation_id, []).append(
            {
                "token": tok.token,
                "note_start_index": tok.note_start_index,
                "note_end_index": tok.note_end_index,
                "isNegated": tok.is_negated,
            }
        )
    return token_map


async def get_note_tags(session: AsyncSession, note_id: str) -> list[str]:
    """Return a note's display tags ordered by position (v1 text_tag_1..5)."""
    result = await session.execute(
        select(NoteTag.value)
        .where(NoteTag.note_id == note_id)
        .order_by(NoteTag.position.asc())
    )
    return [row[0] for row in result.all()]


async def get_annotations_post_event(
    session: AsyncSession, patient_id: str, event_date
) -> list[str]:
    """Unreviewed annotation IDs on/after the event date (v1 ``get_annotations_post_event``)."""
    result = await session.execute(
        select(Annotation.id).where(
            Annotation.patient_id == patient_id,
            Annotation.text_date >= event_date,
            Annotation.review_status == ReviewStatus.UNREVIEWED,
        )
    )
    return [row[0] for row in result.all()]


# ── Event date / annotation review mutations ─────────────────────


async def get_event_date(session: AsyncSession, patient_id: str):
    """Return a patient's stored event date (v1 ``get_event_date``)."""
    patient = await session.get(Patient, patient_id)
    if patient is not None and patient.event_date is not None:
        return patient.event_date
    return None


async def get_event_annotation_id(session: AsyncSession, patient_id: str):
    """Return the annotation ID where the event date was marked (v1 ``get_event_annotation_id``)."""
    patient = await session.get(Patient, patient_id)
    if patient is not None:
        return patient.event_annotation_id
    return None


async def update_event_date(
    session: AsyncSession, patient_id: str, new_date, annotation_id
) -> None:
    """Store a patient's event date + annotation (v1 ``update_event_date``)."""
    await session.execute(
        update(Patient)
        .where(Patient.id == patient_id)
        .values(event_date=new_date, event_annotation_id=annotation_id)
    )


async def delete_event_date(session: AsyncSession, patient_id: str) -> None:
    """Clear a patient's event date + annotation (v1 ``delete_event_date``)."""
    await session.execute(
        update(Patient)
        .where(Patient.id == patient_id)
        .values(event_date=None, event_annotation_id=None)
    )


async def revert_skipped_annotations(session: AsyncSession, patient_id: str) -> None:
    """Revert SKIPPED annotations back to UNREVIEWED (v1 ``revert_skipped_annotations``)."""
    await session.execute(
        update(Annotation)
        .where(
            Annotation.patient_id == patient_id,
            Annotation.review_status == ReviewStatus.SKIPPED,
        )
        .values(review_status=ReviewStatus.UNREVIEWED)
    )


async def mark_annotations_post_event(
    session: AsyncSession, patient_id: str, event_date
) -> None:
    """Mark unreviewed annotations on/after the event date as SKIPPED (v1 ``mark_annotations_post_event``)."""
    await session.execute(
        update(Annotation)
        .where(
            Annotation.patient_id == patient_id,
            Annotation.text_date >= event_date,
            Annotation.review_status == ReviewStatus.UNREVIEWED,
        )
        .values(review_status=ReviewStatus.SKIPPED)
    )


async def revert_annotation_reviewed(
    session: AsyncSession, patient_id: str, annotation_id: str, reviewed_by: str
) -> None:
    """Un-review an annotation and cascade note/patient un-review (v1 ``revert_annotation_reviewed``).

    Used when an event date is deleted on the current annotation: the annotation
    reverts to UNREVIEWED and its note and patient are reopened for review.
    """
    await session.execute(
        update(Annotation)
        .where(Annotation.id == annotation_id)
        .values(review_status=ReviewStatus.UNREVIEWED)
    )
    annotation = await session.get(Annotation, annotation_id)
    if annotation is not None:
        await session.execute(
            update(Note)
            .where(Note.id == annotation.note_id)
            .values(reviewed=False, reviewed_by=reviewed_by)
        )
    await session.execute(
        update(Patient)
        .where(Patient.id == patient_id)
        .values(status=PatientStatus.REVIEWING, reviewed_by=reviewed_by)
    )


async def mark_annotation_reviewed_batch(
    session: AsyncSession, annotation_ids: list[str], reviewed_by: str
) -> None:
    """Mark annotations reviewed and cascade note review (v1 ``mark_annotation_reviewed_batch``).

    A note is marked reviewed once it has no remaining UNREVIEWED annotations,
    mirroring v1's ``update_batch_note_review_status``.
    """
    if not annotation_ids:
        return
    await session.execute(
        update(Annotation)
        .where(Annotation.id.in_(annotation_ids))
        .values(review_status=ReviewStatus.REVIEWED)
    )
    # Note-level cascade: find the notes touched by these annotations.
    note_rows = await session.execute(
        select(Annotation.note_id).where(Annotation.id.in_(annotation_ids)).distinct()
    )
    for note_id in [row[0] for row in note_rows.all()]:
        unreviewed = (
            await session.execute(
                select(func.count(Annotation.id)).where(
                    Annotation.note_id == note_id,
                    Annotation.review_status == ReviewStatus.UNREVIEWED,
                )
            )
        ).scalar_one()
        if unreviewed == 0:
            await mark_note_reviewed(session, note_id, reviewed_by)


async def add_comment(session: AsyncSession, patient_id: str, comment: str) -> None:
    """Store a patient comment (v1 ``add_comment``)."""
    await session.execute(
        update(Patient).where(Patient.id == patient_id).values(comments=comment.strip())
    )


# ── Patient locking ──────────────────────────────────────────────


async def get_patient_lock_status(session: AsyncSession, patient_id: str) -> bool:
    """True if the patient is currently locked for review (v1 ``get_patient_lock_status``)."""
    patient = await session.get(Patient, patient_id)
    return patient is not None and patient.locked_by is not None


async def set_patient_lock_status(
    session: AsyncSession, patient_id: str, locked: bool, user_id: str | None = None
) -> None:
    """Lock/unlock a patient for review (v1 ``set_patient_lock_status``)."""
    if locked:
        await session.execute(
            update(Patient)
            .where(Patient.id == patient_id)
            .values(locked_by=user_id, locked_at=now_utc())
        )
    else:
        await session.execute(
            update(Patient)
            .where(Patient.id == patient_id)
            .values(locked_by=None, locked_at=None)
        )


async def remove_all_locked(session: AsyncSession, project_id: str) -> None:
    """Unlock every patient in a project (v1 ``remove_all_locked``)."""
    await session.execute(
        update(Patient)
        .where(Patient.project_id == project_id)
        .values(locked_by=None, locked_at=None)
    )


# ── Query save + reset (upload_query support) ────────────────────


async def save_query(
    session: AsyncSession,
    project_id: str,
    query: str,
    *,
    use_negation: bool,
    hide_duplicates: bool,
    skip_after_event: bool,
    nlp_apply: bool,
    tag_exact: bool = False,
    created_by: str | None = None,
) -> bool:
    """Save a new search query, returning True if it changed (v1 ``save_query``).

    v1 treats the query as unchanged when the text, ``skip_after_event`` and
    ``nlp_apply`` all match the current query; only a real change resets state.
    """
    current = await get_active_search_query(session, project_id)
    if (
        current is not None
        and current.query == query
        and current.skip_after_event == skip_after_event
        and current.nlp_apply == nlp_apply
    ):
        logger.info("Query already saved: %s", query)
        return False

    await session.execute(
        update(SearchQuery)
        .where(SearchQuery.project_id == project_id, SearchQuery.is_active.is_(True))
        .values(is_active=False)
    )
    session.add(
        SearchQuery(
            project_id=project_id,
            query=query,
            is_active=True,
            nlp_apply=nlp_apply,
            hide_duplicates=hide_duplicates,
            skip_after_event=skip_after_event,
            use_negation=use_negation,
            tag_exact=tag_exact,
            created_by=created_by,
        )
    )
    logger.info("Saved query: %s", query)
    return True


async def empty_annotations(session: AsyncSession, project_id: str) -> None:
    """Delete all annotations (and their tokens) for a project (v1 ``empty_annotations``)."""
    ann_ids = select(Annotation.id).where(Annotation.project_id == project_id)
    await session.execute(
        delete(AnnotationToken).where(AnnotationToken.annotation_id.in_(ann_ids))
    )
    await session.execute(delete(Annotation).where(Annotation.project_id == project_id))


async def reset_patient_reviewed(session: AsyncSession, project_id: str) -> None:
    """Reset all patients and notes to un-reviewed (v1 ``reset_patient_reviewed``)."""
    await session.execute(
        update(Patient)
        .where(Patient.project_id == project_id)
        .values(
            status=PatientStatus.NEW,
            reviewed_by=None,
            event_annotation_id=None,
            event_date=None,
            comments="",
        )
    )
    await session.execute(
        update(Note)
        .where(Note.project_id == project_id)
        .values(reviewed=False, reviewed_by=None)
    )
