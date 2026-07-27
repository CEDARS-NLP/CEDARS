"""Workflow service: v2 port of the ops.py adjudication + NLP-dispatch routes.

The :class:`AdjudicationHandler` state machine is reused unchanged; this module
supplies it data from SQL, persists its ``patient_data`` to the
``review_sessions`` table (replacing Flask session state), and performs the DB
mutations v1 enqueued on its ``ops_queue`` (``enter_patient_date``,
``delete_patient_date``, ``update_patient_data``).
"""

import logging
from datetime import UTC, date, datetime

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.adjudication_handler import (
    AdjudicationHandler,
    PatientStatus as HandlerPatientStatus,
    ReviewStatus as HandlerReviewStatus,
)
from app.connectors.models import Note, Patient, PatientStatus
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp import processor
from app.workflow import db_ops
from app.workflow.models import ReviewSession
from app.workflow.schemas import AnnotationView

logger = logging.getLogger(__name__)


# ── patient_data (de)serialization for JSON storage ──────────────


def _serialize_patient_data(patient_data: dict) -> dict:
    """Convert handler patient_data to a JSON-safe dict for review_sessions.

    review_statuses (enum) → int, dates → ISO strings. Mirrors v1's
    ``backup_session_data``.
    """
    out = dict(patient_data)
    out["review_statuses"] = [rs.value for rs in patient_data.get("review_statuses", [])]
    event_date = patient_data.get("event_date")
    out["event_date"] = event_date.isoformat() if event_date is not None else None
    annotations = []
    for annotation in patient_data.get("annotations", []):
        copy = dict(annotation)
        text_date = copy.get("text_date")
        if hasattr(text_date, "isoformat"):
            copy["text_date"] = text_date.isoformat()
        annotations.append(copy)
    out["annotations"] = annotations
    return out


def _deserialize_patient_data(patient_data: dict) -> dict:
    """Inverse of :func:`_serialize_patient_data` (mirrors ``restore_session_data``)."""
    out = dict(patient_data)
    out["review_statuses"] = [
        HandlerReviewStatus(int(x)) for x in patient_data.get("review_statuses", [])
    ]
    event_date = patient_data.get("event_date")
    # Tolerate both date ("YYYY-MM-DD") and datetime ISO strings — v1 stored the
    # event date as a datetime, so a stored value may carry a time component.
    out["event_date"] = date.fromisoformat(event_date.split("T")[0]) if event_date else None
    annotations = []
    for annotation in patient_data.get("annotations", []):
        copy = dict(annotation)
        text_date = copy.get("text_date")
        if isinstance(text_date, str):
            copy["text_date"] = datetime.fromisoformat(text_date)
        annotations.append(copy)
    out["annotations"] = annotations
    return out


def _build_annotation_dict(annotation, tokens: list[dict]) -> dict:
    """Build the dict the AdjudicationHandler expects from an ORM annotation + tokens."""
    if tokens:
        note_start_index = min(t["note_start_index"] for t in tokens)
    else:
        note_start_index = annotation.sentence_start or 0
    return {
        "_id": annotation.id,
        "note_id": annotation.note_id,
        "patient_id": annotation.patient_id,
        "sentence": annotation.sentence_text,
        "sentence_number": annotation.sentence_number,
        "sentence_start": annotation.sentence_start,
        "sentence_end": annotation.sentence_end,
        "note_start_index": note_start_index,
        "isNegated": annotation.is_negated,
        "text_date": annotation.text_date,
        "reviewed": db_ops.review_status_to_int(annotation.review_status),
        "tokens": tokens,
    }


# ── review_sessions persistence ──────────────────────────────────


async def _load_review_session(
    session: AsyncSession, project_id: str, patient_id: str
) -> ReviewSession | None:
    result = await session.execute(
        select(ReviewSession).where(
            ReviewSession.project_id == project_id,
            ReviewSession.patient_id == patient_id,
        )
    )
    return result.scalars().first()


async def _load_user_review_session(
    session: AsyncSession, project_id: str, user_id: str
) -> ReviewSession | None:
    result = await session.execute(
        select(ReviewSession)
        .where(
            ReviewSession.project_id == project_id,
            ReviewSession.user_id == user_id,
        )
        .order_by(ReviewSession.updated_at.desc())
    )
    return result.scalars().first()


async def _save_review_session(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    user_id: str,
    patient_data: dict,
    reviewed_annotation_ids: list[str],
    patient_comments: str,
    skip_after_event: bool,
) -> None:
    existing = await _load_review_session(session, project_id, patient_id)
    if existing is None:
        existing = ReviewSession(
            project_id=project_id, patient_id=patient_id, user_id=user_id
        )
    existing.user_id = user_id
    existing.patient_data = _serialize_patient_data(patient_data)
    existing.reviewed_annotation_ids = reviewed_annotation_ids
    existing.patient_comments = patient_comments
    existing.skip_after_event = skip_after_event
    existing.updated_at = datetime.now(UTC)
    session.add(existing)


async def _delete_review_session(
    session: AsyncSession, project_id: str, patient_id: str
) -> None:
    existing = await _load_review_session(session, project_id, patient_id)
    if existing is not None:
        await session.delete(existing)


# ── annotation payload (show_annotation) ─────────────────────────


async def _current_annotation_payload(
    session: AsyncSession,
    project_id: str,
    handler: AdjudicationHandler,
    comments: str,
) -> AnnotationView | None:
    annotation = handler.get_curr_annotation()
    note = await session.get(Note, annotation["note_id"])
    if note is None:
        return None
    tags = await db_ops.get_note_tags(session, note.id)
    padded = (tags + ["", "", "", "", ""])[:5]
    note_dict = {
        "text": note.text,
        "text_tag_1": padded[0],
        "text_tag_2": padded[1],
        "text_tag_3": padded[2],
        "text_tag_4": padded[3],
        "text_tag_5": padded[4],
    }
    annotations_for_note = handler.get_all_annotations_for_curr_note()
    annotations_for_sentence = handler.get_all_annotations_for_curr_sentence()
    details = handler.get_annotation_details(
        annotation, note_dict, comments, annotations_for_note, annotations_for_sentence
    )
    # get_annotation_details may yield datetimes; the response schema expects dates.
    for key in ("note_date", "event_date"):
        value = details.get(key)
        if isinstance(value, datetime):
            details[key] = value.date()
    return AnnotationView(**details)


# ── ops_queue ports (DB persistence of adjudication actions) ─────


async def _update_patient_data(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    comments: str,
    reviewed_by: str,
    reviewed_annotation_ids: list[str],
    is_patient_reviewed: bool = True,
) -> None:
    """Port of ops.py ``update_patient_data``."""
    await db_ops.mark_annotation_reviewed_batch(session, reviewed_annotation_ids, reviewed_by)
    await db_ops.add_comment(session, patient_id, (comments or "").strip())
    await db_ops.upsert_patient_result(session, project_id, patient_id)
    if is_patient_reviewed:
        await db_ops.set_patient_lock_status(session, patient_id, False)


async def _enter_patient_date(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    new_date: datetime,
    current_annotation_id: str,
    reviewed_by: str,
    comments: str,
    reviewed_annotation_ids: list[str],
    skip_after_event: bool,
    is_patient_reviewed: bool,
) -> None:
    """Port of ops.py ``enter_patient_date``."""
    if skip_after_event:
        await db_ops.mark_annotations_post_event(session, patient_id, new_date)
    await db_ops.mark_annotation_reviewed_batch(session, [current_annotation_id], reviewed_by)
    await db_ops.update_event_date(session, patient_id, new_date, current_annotation_id)
    await _update_patient_data(
        session, project_id, patient_id, comments, reviewed_by,
        reviewed_annotation_ids, is_patient_reviewed,
    )


async def _delete_patient_date(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    current_annotation_id: str,
    reviewed_by: str,
    comments: str,
    reviewed_annotation_ids: list[str],
    is_patient_reviewed: bool,
) -> None:
    """Port of ops.py ``delete_patient_date``."""
    await db_ops.delete_event_date(session, patient_id)
    await db_ops.revert_skipped_annotations(session, patient_id)
    await db_ops.revert_annotation_reviewed(
        session, patient_id, current_annotation_id, reviewed_by
    )
    await _update_patient_data(
        session, project_id, patient_id, comments, reviewed_by,
        reviewed_annotation_ids, is_patient_reviewed,
    )


# ── adjudicate_records (get next / resume) ───────────────────────


async def get_next_patient(
    session: AsyncSession,
    project_id: str,
    user_id: str,
    user_name: str,
    search: str | None = None,
) -> tuple[str | None, HandlerPatientStatus | None, AnnotationView | None]:
    """Return (patient_id, status, annotation) for the next patient to review.

    Faithful port of ops.py ``adjudicate_records`` GET flow, including resuming
    an in-progress review session and skipping patients with no annotations.
    """
    # Resume an in-progress session if this user already holds one.
    if search is None:
        resume = await _load_user_review_session(session, project_id, user_id)
        if resume is not None:
            patient = await session.get(Patient, resume.patient_id)
            if patient is not None and patient.locked_by == user_id:
                handler = AdjudicationHandler(resume.patient_id)
                handler.load_from_patient_data(
                    resume.patient_id, _deserialize_patient_data(resume.patient_data)
                )
                payload = await _current_annotation_payload(
                    session, project_id, handler, resume.patient_comments
                )
                return resume.patient_id, handler.get_patient_status(), payload

    query = await db_ops.get_active_search_query(session, project_id)
    hide_duplicates = query.hide_duplicates if query else True
    skip_after_event = query.skip_after_event if query else False

    while True:
        patient_id = None
        if search:
            patient = await db_ops.get_patient_by_ext_id(session, project_id, search)
            if patient is not None and not await db_ops.get_patient_lock_status(
                session, patient.id
            ):
                patient_id = patient.id
            search = None  # only honour the search term once
        if patient_id is None:
            patient_id = await db_ops.get_patients_to_annotate(session, project_id)
        if patient_id is None:
            return None, None, None

        raw = await db_ops.get_all_annotations_for_patient(session, project_id, patient_id)
        token_map = await db_ops.get_tokens_map(session, [a.id for a in raw])
        raw_dicts = [_build_annotation_dict(a, token_map.get(a.id, [])) for a in raw]

        stored_event_date = await db_ops.get_event_date(session, patient_id)
        stored_annotation_id = await db_ops.get_event_annotation_id(session, patient_id)
        patient = await session.get(Patient, patient_id)
        patient_comments = patient.comments if patient else ""

        handler = AdjudicationHandler(patient_id)
        patient_data, annotations_with_duplicates = handler.init_patient_data(
            raw_dicts, hide_duplicates, stored_event_date, stored_annotation_id
        )
        await db_ops.mark_annotation_reviewed_batch(
            session, annotations_with_duplicates, user_name
        )

        if len(patient_data["annotation_ids"]) > 0:
            await db_ops.set_patient_lock_status(session, patient_id, True, user_id)

        status = handler.get_patient_status()
        if status == HandlerPatientStatus.NO_ANNOTATIONS:
            await db_ops.upsert_patient_result(session, project_id, patient_id)
            await db_ops.set_patient_lock_status(session, patient_id, False)
            await session.commit()
            continue  # skip to the next patient

        await _save_review_session(
            session, project_id, patient_id, user_id, patient_data,
            [], patient_comments or "", skip_after_event,
        )
        await session.commit()
        payload = await _current_annotation_payload(
            session, project_id, handler, patient_comments or ""
        )
        return patient_id, status, payload


async def get_current_annotation(
    session: AsyncSession, project_id: str, patient_id: str
) -> AnnotationView | None:
    """Port of ops.py ``show_annotation`` — render the current annotation."""
    review = await _load_review_session(session, project_id, patient_id)
    if review is None:
        return None
    handler = AdjudicationHandler(patient_id)
    handler.load_from_patient_data(patient_id, _deserialize_patient_data(review.patient_data))
    return await _current_annotation_payload(
        session, project_id, handler, review.patient_comments
    )


# ── save_adjudications (apply one action) ────────────────────────


_SHIFT_ACTIONS = {"first_anno", "prev_10", "prev_1", "next_1", "next_10", "last_anno"}


async def apply_action(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    user_id: str,
    user_name: str,
    action: str,
    comment: str,
    event_date_str: str | None,
) -> tuple[bool, AnnotationView | None]:
    """Apply one adjudication action; returns (patient_complete, annotation).

    Faithful port of ops.py ``save_adjudications``.
    """
    review = await _load_review_session(session, project_id, patient_id)
    if review is None:
        raise HTTPException(status_code=404, detail="No active review session for patient")

    handler = AdjudicationHandler(patient_id)
    handler.load_from_patient_data(patient_id, _deserialize_patient_data(review.patient_data))

    current_annotation_id = handler.get_curr_annotation_id()
    comments = (comment or "").strip()
    reviewed_annotation_ids = list(review.reviewed_annotation_ids or [])
    skip_after_event = review.skip_after_event

    db_results_updated = False
    is_shift_performed = False

    if action == "new_date":
        # Remove any existing skip marks before entering a new date.
        await db_ops.revert_skipped_annotations(session, patient_id)
        handler.reset_all_skipped()
        if not event_date_str:
            raise HTTPException(status_code=400, detail="event_date is required for new_date")
        new_date = datetime.strptime(event_date_str, "%Y-%m-%d").replace(tzinfo=UTC)
        annotations_after_event: list[str] = []
        if skip_after_event:
            annotations_after_event = await db_ops.get_annotations_post_event(
                session, patient_id, new_date
            )
        db_results_updated = True
        handler.mark_event_date(new_date, current_annotation_id, annotations_after_event)
        await _enter_patient_date(
            session, project_id, patient_id, new_date, current_annotation_id,
            user_name, comments, reviewed_annotation_ids, skip_after_event,
            handler.is_patient_reviewed(),
        )
    elif action == "del_date":
        db_results_updated = True
        handler.delete_event_date()
        await _delete_patient_date(
            session, project_id, patient_id, current_annotation_id, user_name,
            comments, reviewed_annotation_ids, handler.is_patient_reviewed(),
        )
    elif action == "adjudicate":
        reviewed_annotation_ids.append(current_annotation_id)
        handler._adjudicate_annotation()
    elif action in _SHIFT_ACTIONS:
        handler.perform_shift(action)
        is_shift_performed = True
    else:
        raise HTTPException(status_code=400, detail=f"Unknown action: {action}")

    patient_data = handler.get_patient_data()
    is_reviewed = handler.is_patient_reviewed()

    if is_reviewed and not is_shift_performed:
        await db_ops.mark_patient_reviewed(session, project_id, patient_id, user_name)
        if not db_results_updated:
            await _update_patient_data(
                session, project_id, patient_id, comments, user_name,
                reviewed_annotation_ids, is_patient_reviewed=True,
            )
        await _delete_review_session(session, project_id, patient_id)
        await session.commit()
        return True, None

    await _save_review_session(
        session, project_id, patient_id, user_id, patient_data,
        reviewed_annotation_ids, comments, skip_after_event,
    )
    await session.commit()
    payload = await _current_annotation_payload(session, project_id, handler, comments)
    return False, payload


async def release_patient(
    session: AsyncSession, project_id: str, patient_id: str, user_name: str
) -> None:
    """Finalize and unlock a patient without completing review (ops.py POST finalize)."""
    review = await _load_review_session(session, project_id, patient_id)
    if review is not None:
        await db_ops.add_comment(session, patient_id, (review.patient_comments or "").strip())
        await db_ops.mark_annotation_reviewed_batch(
            session, list(review.reviewed_annotation_ids or []), user_name
        )
        await db_ops.upsert_patient_result(session, project_id, patient_id)
    await db_ops.set_patient_lock_status(session, patient_id, False)
    await _delete_review_session(session, project_id, patient_id)
    await session.commit()


async def unlock_patient(
    session: AsyncSession, project_id: str, patient_id: str
) -> None:
    """Unlock a patient and drop any review session (ops.py ``unlock_patient``)."""
    await db_ops.set_patient_lock_status(session, patient_id, False)
    await _delete_review_session(session, project_id, patient_id)
    await session.commit()


# ── upload_query + do_nlp_processing ─────────────────────────────


async def save_query_and_dispatch(
    session: AsyncSession,
    project_id: str,
    user_id: str,
    *,
    query: str,
    hide_duplicates: bool,
    skip_after_event: bool,
    use_negation: bool,
    nlp_apply: bool,
) -> tuple[bool, int, str, str | None]:
    """Port of ops.py ``upload_query`` POST + ``do_nlp_processing``.

    Saves the query, resets state when it changed, then dispatches NLP.
    Returns (changed, dispatched_patients, mode, job_id).
    """
    if not query or not query.strip():
        raise HTTPException(status_code=400, detail="Search query is required")

    changed = await db_ops.save_query(
        session,
        project_id,
        query.strip(),
        use_negation=use_negation,
        hide_duplicates=hide_duplicates,
        skip_after_event=skip_after_event,
        nlp_apply=nlp_apply,
        created_by=user_id,
    )
    if changed:
        await db_ops.empty_annotations(session, project_id)
        await db_ops.reset_patient_reviewed(session, project_id)
    await session.commit()

    dispatched, mode, job_id = await dispatch_nlp(session, project_id, user_id)
    return changed, dispatched, mode, job_id


async def dispatch_nlp(
    session: AsyncSession, project_id: str, user_id: str
) -> tuple[int, str, str | None]:
    """Port of ops.py ``do_nlp_processing`` — enqueue one NLP job per patient.

    Falls back to synchronous processing when ARQ/Redis is unavailable (tests).
    """
    patient_ids = await db_ops.get_patient_ids(session, project_id)
    for pid in patient_ids:
        patient = await session.get(Patient, pid)
        if patient is not None:
            patient.status = PatientStatus.NLP_PROCESSING
            session.add(patient)

    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.NLP,
        status=JobStatus.PENDING,
        created_by=user_id,
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    use_sync = True
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        health = await redis.exists(b"arq:queue:health-check")
        if health:
            for pid in patient_ids:
                await redis.enqueue_job("run_v1_nlp_patient", project_id, pid)
            use_sync = False
        else:
            logger.warning("No ARQ workers found; running v1 NLP synchronously.")
        await redis.aclose()
    except Exception:
        logger.warning("ARQ unavailable; running v1 NLP synchronously.")

    if use_sync:
        for pid in patient_ids:
            await processor.process_patient_notes(session, project_id, pid)
            patient = await session.get(Patient, pid)
            if patient is not None and patient.status == PatientStatus.NLP_PROCESSING:
                patient.status = PatientStatus.NLP_COMPLETE
                session.add(patient)
        bg_job.status = JobStatus.COMPLETED
        session.add(bg_job)
        await session.commit()

    return len(patient_ids), ("sync" if use_sync else "queued"), bg_job.id
