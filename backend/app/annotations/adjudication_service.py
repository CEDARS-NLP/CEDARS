"""Database-backed manual adjudication using the reference handler algorithms."""

from datetime import date, datetime

from sqlalchemy import or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.adjudication_compat import ReviewStatus
from app.annotations.adjudication_handler import AdjudicationHandler
from app.annotations.models import Annotation, ReviewType
from app.annotations.models import ReviewStatus as ReviewStatusEnum
from app.annotations.query_service import _patient_review_ready
from app.annotations.review_jobs import PatientReviewJob
from app.annotations.review_state import ReviewStateStore
from app.audit.models import AuditAction, AuditEntry
from app.audit.service import log_action
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.models import SearchQuery
from app.production.models import NotePrediction, ProductionState

_state_store = ReviewStateStore()
_EXCLUDED_REASONS = {"llm_negative", "duplicate", "negated"}


class AdjudicationConflictError(ValueError):
    """The requested mutation conflicts with the active run or reviewer lock."""


async def _run_identity(session: AsyncSession, project_id: str) -> tuple[str, int]:
    state = await session.get(ProductionState, project_id)
    return (state.active_run_id or "", state.generation) if state else ("", 0)


async def _lock_run_identity(session: AsyncSession, project_id: str) -> tuple[str, int]:
    state = await session.scalar(
        select(ProductionState)
        .where(col(ProductionState.project_id) == project_id)
        .execution_options(populate_existing=True)
        .with_for_update()
    )
    return (state.active_run_id or "", state.generation) if state else ("", 0)


async def _refresh_result(session: AsyncSession, project_id: str, patient_uuid: str) -> None:
    try:
        from app.production.results import refresh_patient_result
    except ModuleNotFoundError as exc:
        if exc.name != "app.production.results":
            raise
        return
    await refresh_patient_result(session, project_id, patient_uuid)


async def _update_patient_completion(
    session: AsyncSession,
    project_id: str,
    patient: Patient,
    user_id: str,
    run_id: str,
    is_reviewed: bool,
    review_type: str | None = None,
) -> None:
    ready = await _patient_review_ready(session, project_id, patient.patient_id_ext, run_id)
    if is_reviewed and ready:
        patient.status = PatientStatus.REVIEWED
        patient.review_source = "human"
        patient.review_reason = "manual_review"
        patient.review_type = review_type
        patient.reviewed_by = user_id
        patient.reviewed_at = now_utc()
        patient.locked_by = None
        patient.locked_at = None
    else:
        patient.status = PatientStatus.REVIEWING if ready else PatientStatus.NLP_PROCESSING
        patient.review_source = None
        patient.review_reason = None
        patient.review_type = None
        patient.reviewed_by = None
        patient.reviewed_at = None
    session.add(patient)


async def _refresh_note_reviews(
    session: AsyncSession,
    project_id: str,
    patient: Patient,
    run_id: str,
    user_id: str,
    now: datetime,
) -> str:
    """Recompute per-note review status/type and return the patient review type.

    A note is marked REVIEWED when it has no annotations, only negated
    annotations (with keep-negations off), only LLM-negative annotations, or
    every annotation has been resolved by a human. Otherwise it stays
    UNREVIEWED while any annotation is still unreviewed.
    """
    notes = list(
        (
            await session.execute(
                select(Note).where(
                    col(Note.project_id) == project_id,
                    col(Note.patient_id) == patient.id,
                    col(Note.deleted_at).is_(None),
                )
            )
        ).scalars().all()
    )
    annotation_query = select(Annotation).where(
        col(Annotation.project_id) == project_id,
        or_(
            col(Annotation.patient_uuid) == patient.id,
            col(Annotation.patient_id) == patient.patient_id_ext,
        ),
    )
    if run_id:
        annotation_query = annotation_query.where(
            col(Annotation.production_run_id) == run_id
        )
    annotations = list((await session.execute(annotation_query)).scalars().all())
    by_text: dict[str, list[Annotation]] = {}
    for annotation in annotations:
        by_text.setdefault(annotation.text_id, []).append(annotation)

    patient_type: str | None = None
    for note in notes:
        rows = by_text.get(note.text_id, [])
        if not rows:
            note.review_status = ReviewStatusEnum.REVIEWED.value
            note.review_type = ReviewType.NO_ANNOTATION.value
            note.reviewed_by = user_id
            note.reviewed_at = now
        elif any(row.status == "U" for row in rows):
            note.review_status = ReviewStatusEnum.UNREVIEWED.value
            note.review_type = None
            note.reviewed_by = None
            note.reviewed_at = None
        else:
            human_rows = [
                row for row in rows
                if row.actor_type == "human" and row.status in ("R", "S")
            ]
            if human_rows:
                note_type = ReviewType.HUMAN.value
            elif any(row.review_reason == "llm_negative" for row in rows):
                note_type = ReviewType.LLM.value
            elif any(row.review_reason == "negated" for row in rows):
                note_type = ReviewType.NEGATION.value
            else:
                note_type = ReviewType.HUMAN.value
            note.review_status = ReviewStatusEnum.REVIEWED.value
            note.review_type = note_type
            note.reviewed_by = user_id
            note.reviewed_at = now
        session.add(note)
        patient_type = _merge_review_type(patient_type, note.review_type)
    return patient_type or ReviewType.NO_ANNOTATION.value


_REVIEW_TYPE_PRIORITY = {
    ReviewType.NO_ANNOTATION.value: 0,
    ReviewType.NEGATION.value: 1,
    ReviewType.LLM.value: 2,
    ReviewType.HUMAN.value: 3,
}


def _merge_review_type(current: str | None, candidate: str | None) -> str | None:
    if candidate is None:
        return current
    if current is None:
        return candidate
    if _REVIEW_TYPE_PRIORITY.get(candidate, 0) > _REVIEW_TYPE_PRIORITY.get(current, 0):
        return candidate
    return current


async def _patient_for_annotation(
    session: AsyncSession, project_id: str, annotation: Annotation
) -> Patient | None:
    if annotation.patient_uuid:
        patient = await session.get(Patient, annotation.patient_uuid)
        if patient and patient.project_id == project_id:
            return patient
    return (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                col(Patient.patient_id_ext) == annotation.patient_id,
            )
        )
    ).scalar_one_or_none()


async def _validate_current_run(
    session: AsyncSession, project_id: str, annotation: Annotation
) -> tuple[str, int]:
    run_id, generation = await _lock_run_identity(session, project_id)
    if run_id and annotation.production_run_id != run_id:
        raise AdjudicationConflictError("Annotation belongs to a stale production run")
    if not run_id and annotation.production_run_id:
        raise AdjudicationConflictError("Annotation has no active production run")
    return run_id, generation


async def _claim_patient(
    session: AsyncSession, project_id: str, patient: Patient, user_id: str
) -> None:
    result = await session.execute(
        update(Patient)
        .where(
            col(Patient.id) == patient.id,
            col(Patient.project_id) == project_id,
            or_(col(Patient.locked_by).is_(None), col(Patient.locked_by) == user_id),
        )
        .values(locked_by=user_id, locked_at=now_utc())
        .execution_options(synchronize_session="fetch")
        .returning(col(Patient.id))
    )
    if result.scalar_one_or_none() is None:
        await session.rollback()
        raise AdjudicationConflictError("Patient is locked by another reviewer")
    await session.flush()
    await session.refresh(patient)


async def _skip_after_event_enabled(
    session: AsyncSession, project_id: str, explicit_value: bool | None
) -> bool:
    if explicit_value is not None:
        return explicit_value
    from app.common.project_registry import load_project

    project = await load_project(project_id)
    enabled = bool((project.settings or {}).get("skip_after_event_date", False)) if project else False
    if enabled:
        return True
    return bool(
        (
            await session.execute(
                select(col(SearchQuery.id)).where(
                    col(SearchQuery.project_id) == project_id,
                    col(SearchQuery.is_active).is_(True),
                    col(SearchQuery.skip_after_event).is_(True),
                    col(SearchQuery.deleted_at).is_(None),
                ).limit(1)
            )
        ).scalar_one_or_none()
    )


async def _annotation_and_note(
    session: AsyncSession, project_id: str, annotation_id: str | int
) -> tuple[Annotation | None, Note | None]:
    try:
        numeric_id = int(annotation_id)
    except (TypeError, ValueError):
        return None, None
    row = (
        await session.execute(
            select(Annotation, Note)
            .outerjoin(
                Note,
                or_(
                    col(Annotation.note_uuid) == col(Note.id),
                    (col(Annotation.project_id) == col(Note.project_id))
                    & (col(Annotation.text_id) == col(Note.text_id))
                    & (col(Annotation.patient_id) == col(Note.patient_id_ext)),
                ),
            )
            .where(
                col(Annotation.project_id) == project_id,
                col(Annotation.annotation_id) == numeric_id,
            )
        )
    ).first()
    return (row[0], row[1]) if row else (None, None)


async def _sync_cursor(
    session: AsyncSession,
    project_id: str,
    patient: Patient,
    user_id: str,
    run_id: str,
    generation: int,
    preferred_id: str | None = None,
    persist: bool = True,
) -> dict:
    annotation_query = select(Annotation).where(
        col(Annotation.project_id) == project_id,
        or_(
            col(Annotation.patient_uuid) == patient.id,
            col(Annotation.patient_id) == patient.patient_id_ext,
        ),
    )
    if run_id:
        annotation_query = annotation_query.where(
            col(Annotation.production_run_id) == run_id
        )
    annotations = list(
        (
            await session.execute(
                annotation_query.order_by(
                    col(Annotation.text_date),
                    col(Annotation.text_id),
                    col(Annotation.note_start_index),
                )
            )
        ).scalars().all()
    )
    prediction_labels: dict[str, int | None] = {}
    if run_id:
        predictions = (
            await session.execute(
                select(NotePrediction).where(
                    col(NotePrediction.project_id) == project_id,
                    col(NotePrediction.run_id) == run_id,
                    col(NotePrediction.patient_id) == patient.patient_id_ext,
                )
            )
        ).scalars().all()
        prediction_labels = {row.text_id: row.label for row in predictions}

    original_fields = {
        row.annotation_id: (row.status, row.review_reason, row.actor_type, row.duplicate_of)
        for row in annotations
    }
    for annotation in annotations:
        if annotation.status != "U":
            continue
        if prediction_labels.get(annotation.text_id) == 0 and annotation.review_reason is None:
            annotation.status = "R"
            annotation.review_reason = "llm_negative"
            annotation.actor_type = "system"
        elif annotation.isNegated and annotation.review_reason is None:
            query = (
                await session.execute(
                    select(SearchQuery).where(
                        col(SearchQuery.project_id) == project_id,
                        col(SearchQuery.is_active).is_(True),
                        col(SearchQuery.deleted_at).is_(None),
                    ).limit(1)
                )
            ).scalar_one_or_none()
            if query and query.exclude_negated:
                annotation.status = "R"
                annotation.review_reason = "negated"
                annotation.actor_type = "system"

    query = (
        await session.execute(
            select(SearchQuery).where(
                col(SearchQuery.project_id) == project_id,
                col(SearchQuery.is_active).is_(True),
                col(SearchQuery.deleted_at).is_(None),
            ).limit(1)
        )
    ).scalar_one_or_none()
    visible = [
        row for row in annotations
        if row.review_reason not in _EXCLUDED_REASONS
        and not (query and query.exclude_negated and row.isNegated)
        and prediction_labels.get(row.text_id) != 0
    ]
    handler = AdjudicationHandler(patient.patient_id_ext)
    state, duplicate_ids = handler.init_patient_data(
        list(visible), bool(query.hide_duplicates) if query else True,
        patient.event_date, str(patient.event_annotation_id) if patient.event_annotation_id else None,
    )
    duplicate_set = set(duplicate_ids)
    if duplicate_set:
        survivors: dict[tuple[str, str], int | None] = {}
        hide_across_patient = bool(query.hide_duplicates) if query else True
        for row in visible:
            normalized = row.sentence.lower().strip()
            key = ("", normalized) if hide_across_patient else (row.text_id, normalized)
            if str(row.annotation_id) in duplicate_set:
                survivor = survivors.get(key)
                row.status = "R"
                row.review_reason = "duplicate"
                row.duplicate_of = survivor
                row.actor_type = "system"
            else:
                survivors.setdefault(key, row.annotation_id)
    cached = await _state_store.load(project_id, user_id, run_id)
    if cached is None:
        cached = _state_store.load_from_patient(patient, user_id, run_id, generation)
    if cached and cached.get("generation") == generation:
        current_id = cached.get("current_id")
        if current_id in state["annotation_ids"]:
            state["current_index"] = state["annotation_ids"].index(current_id)
    if preferred_id and preferred_id in state["annotation_ids"]:
        state["current_index"] = state["annotation_ids"].index(preferred_id)
    if state["annotation_ids"]:
        current_id = state["annotation_ids"][state["current_index"]]
        next_id = next(
            (
                state["annotation_ids"][index]
                for index in list(range(state["current_index"] + 1, len(state["annotation_ids"])))
                + list(range(0, state["current_index"]))
                if state["review_statuses"][index] == ReviewStatus.UNREVIEWED
            ),
            None,
        )
    else:
        current_id = next_id = None
    if persist:
        await session.flush()
        await _state_store.save(
            project_id, user_id, run_id, generation, state["annotation_ids"], current_id
        )
        _state_store.save_to_patient(
            patient, user_id, run_id, generation, state["annotation_ids"], current_id
        )
        session.add(patient)
    else:
        for row in annotations:
            row.status, row.review_reason, row.actor_type, row.duplicate_of = original_fields[
                row.annotation_id
            ]
    return {
        "patient_id": patient.id,
        "current_annotation_id": current_id,
        "next_annotation_id": next_id,
        "annotation_ids": state["annotation_ids"],
        "handler": handler,
        "handler_state": state,
    }


async def get_review_cursor(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str
) -> dict | None:
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient:
        return None
    run_id, generation = await _lock_run_identity(session, project_id)
    if patient.locked_by not in (None, user_id):
        raise AdjudicationConflictError("Patient is locked by another reviewer")
    was_unlocked = patient.locked_by is None
    await _claim_patient(session, project_id, patient, user_id)
    if was_unlocked:
        patient.status = PatientStatus.REVIEWING
        session.add(patient)

    cursor = await _sync_cursor(session, project_id, patient, user_id, run_id, generation)
    await session.commit()
    if was_unlocked:
        await log_action(
            session, project_id, AuditAction.PATIENT_LOCKED,
            user_id=user_id, patient_id=patient.id,
        )
    return cursor


async def _save_handler_cursor(
    session: AsyncSession,
    patient: Patient,
    project_id: str,
    user_id: str,
    run_id: str,
    generation: int,
    handler: AdjudicationHandler,
    cursor: dict,
) -> dict:
    state = handler.get_patient_data()
    ids = state["annotation_ids"]
    statuses = state["review_statuses"]
    index = state["current_index"]
    current_id = ids[index] if ids and index >= 0 else None
    next_id = None
    if current_id is not None:
        next_id = next(
            (
                ids[candidate]
                for candidate in list(range(index + 1, len(ids))) + list(range(index))
                if statuses[candidate] == ReviewStatus.UNREVIEWED
            ),
            None,
        )
    await _state_store.save(
        project_id, user_id, run_id, generation, ids, current_id
    )
    _state_store.save_to_patient(
        patient, user_id, run_id, generation, ids, current_id
    )
    session.add(patient)
    cursor["current_annotation_id"] = current_id
    cursor["next_annotation_id"] = next_id
    cursor["annotation_ids"] = ids
    cursor["handler_state"] = state
    return cursor


async def apply_review_action(
    session: AsyncSession,
    project_id: str,
    annotation_id: str | int,
    user_id: str,
    *,
    action: str,
    event_date: date | datetime | None = None,
    skip_after_event: bool | None = None,
) -> dict | None:
    if action not in {"event", "negative", "skip"}:
        raise ValueError(f"Unsupported review action: {action}")
    if action == "event" and event_date is None:
        raise ValueError("event_date is required for a human event")
    annotation, _ = await _annotation_and_note(session, project_id, annotation_id)
    if not annotation:
        return None
    run_id, generation = await _validate_current_run(session, project_id, annotation)
    patient = await _patient_for_annotation(session, project_id, annotation)
    if not patient:
        return None
    await _claim_patient(session, project_id, patient, user_id)
    cursor = await _sync_cursor(
        session, project_id, patient, user_id, run_id, generation
    )
    handler = cursor["handler"]
    state = cursor["handler_state"]
    target_id = str(annotation.annotation_id)
    if target_id not in state["annotation_ids"]:
        raise AdjudicationConflictError("Annotation is not eligible for manual review")
    if cursor["current_annotation_id"] != target_id:
        raise AdjudicationConflictError("Annotation is not the backend-selected review cursor")
    handler.load_from_patient_data(patient.patient_id_ext, state)
    now = now_utc()

    if action == "event":
        canonical_date = event_date.date() if isinstance(event_date, datetime) else event_date
        rows = (
            await session.execute(
                select(Annotation).where(
                    col(Annotation.project_id) == project_id,
                    or_(col(Annotation.patient_uuid) == patient.id,
                        col(Annotation.patient_id) == patient.patient_id_ext),
                    col(Annotation.review_reason) == "event_date_skip",
                    col(Annotation.status) == "S",
                )
            )
        ).scalars().all()
        for row in rows:
            row.status = "U"
            row.review_reason = None
            row.skipped_by_event_annotation_id = None
            row.reviewed_by = None
            row.reviewed_at = None
        cursor = await _sync_cursor(
            session, project_id, patient, user_id, run_id, generation,
            preferred_id=target_id,
        )
        handler = cursor["handler"]
        state = cursor["handler_state"]
        handler.load_from_patient_data(patient.patient_id_ext, state)
        if cursor["current_annotation_id"] != target_id:
            raise AdjudicationConflictError("Annotation is not the backend-selected review cursor")
        patient.event_date = canonical_date
        patient.event_annotation_id = annotation.annotation_id
        patient.event_reviewer = user_id
        annotation.status = "R"
        annotation.review_reason = "human_event"
        annotation.reviewed_by = user_id
        annotation.reviewed_at = now
        annotation.actor_type = "human"
        skipped_count = 0
        event_skip_ids: list[str] = []
        if await _skip_after_event_enabled(session, project_id, skip_after_event):
            annotations_with_notes = (
                await session.execute(
                    select(Annotation, Note)
                    .join(
                        Note,
                        or_(
                            col(Annotation.note_uuid) == col(Note.id),
                            (col(Annotation.project_id) == col(Note.project_id))
                            & (col(Annotation.text_id) == col(Note.text_id))
                            & (col(Annotation.patient_id) == col(Note.patient_id_ext)),
                        ),
                    )
                    .where(
                        col(Annotation.project_id) == project_id,
                        or_(col(Annotation.patient_uuid) == patient.id,
                            col(Annotation.patient_id) == patient.patient_id_ext),
                        col(Annotation.status) == "U",
                        col(Annotation.annotation_id) != annotation.annotation_id,
                        col(Annotation.review_reason).is_(None),
                    )
                )
            ).all()
            visible_ids = set(state["annotation_ids"])
            for row, source_note in annotations_with_notes:
                note_date = source_note.note_date.date() if source_note.note_date else row.text_date
                if note_date >= canonical_date and str(row.annotation_id) in visible_ids:
                    event_skip_ids.append(str(row.annotation_id))
        handler.mark_event_date(canonical_date, target_id, [int(row_id) for row_id in event_skip_ids])
        state = handler.get_patient_data()
        for index, row_id in enumerate(state["annotation_ids"]):
            if row_id in event_skip_ids:
                row = next(item for item in state["annotations"] if str(item.annotation_id) == row_id)
                row.status = "S"
                row.review_reason = "event_date_skip"
                row.reviewed_by = user_id
                row.reviewed_at = now
                row.actor_type = "human"
                row.skipped_by_event_annotation_id = annotation.annotation_id
                skipped_count += 1
        annotation.status = "R"
        annotation.review_reason = "human_event"
        audit_action = AuditAction.EVENT_DATE_SET
    elif action == "skip":
        index = state["current_index"]
        state["review_statuses"][index] = ReviewStatus.SKIPPED
        for candidate in list(range(index + 1, len(state["annotation_ids"]))) + list(range(index)):
            if state["review_statuses"][candidate] == ReviewStatus.UNREVIEWED:
                state["current_index"] = candidate
                break
        annotation.status = "S"
        annotation.review_reason = None
        annotation.reviewed_by = user_id
        annotation.reviewed_at = now
        annotation.actor_type = "human"
        audit_action = AuditAction.ANNOTATION_SKIPPED
        skipped_count = 0
    else:
        handler._adjudicate_annotation()
        annotation.status = "R"
        annotation.review_reason = "human_negative"
        annotation.reviewed_by = user_id
        annotation.reviewed_at = now
        annotation.actor_type = "human"
        audit_action = AuditAction.ANNOTATION_REVIEWED
        skipped_count = 0

    cursor = await _save_handler_cursor(
        session, patient, project_id, user_id, run_id, generation, handler, cursor
    )
    await _update_patient_completion(
        session, project_id, patient, user_id, run_id, handler.is_patient_reviewed()
    )
    session.add_all([patient, annotation])
    await _refresh_result(session, project_id, patient.id)
    await session.commit()
    await log_action(
        session, project_id, audit_action, user_id=user_id, patient_id=patient.id,
        detail={
            "annotation_id": str(annotation.annotation_id),
            "skipped_count": skipped_count,
        },
    )
    return {
        "annotation": annotation,
        "patient": patient,
        "skipped_count": skipped_count,
        "cursor": cursor,
    }


async def navigate_review(
    session: AsyncSession, project_id: str, patient_id: str, user_id: str, action: str
) -> dict | None:
    cursor = await get_review_cursor(session, project_id, patient_id, user_id)
    if not cursor:
        return None
    handler = cursor["handler"]
    handler.load_from_patient_data(patient_id, cursor["handler_state"])
    handler.perform_shift(action)
    state = handler.get_patient_data()
    run_id, generation = await _run_identity(session, project_id)
    current_id = (
        state["annotation_ids"][state["current_index"]]
        if state["annotation_ids"] else None
    )
    await _state_store.save(
        project_id, user_id, run_id, generation, state["annotation_ids"], current_id
    )
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id,
                    col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if patient:
        _state_store.save_to_patient(
            patient, user_id, run_id, generation, state["annotation_ids"], current_id
        )
        session.add(patient)
        await session.commit()
    cursor["current_annotation_id"] = current_id
    return cursor


async def delete_patient_event(
    session: AsyncSession, project_id: str, annotation_id: str | int, user_id: str
) -> dict | None:
    annotation, _ = await _annotation_and_note(session, project_id, annotation_id)
    if not annotation:
        return None
    run_id, generation = await _validate_current_run(session, project_id, annotation)
    patient = await _patient_for_annotation(session, project_id, annotation)
    if not patient or patient.event_annotation_id != annotation.annotation_id:
        return None
    await _claim_patient(session, project_id, patient, user_id)
    cursor = await _sync_cursor(
        session, project_id, patient, user_id, run_id, generation
    )
    state = cursor["handler_state"]
    target_id = str(annotation.annotation_id)
    if cursor["current_annotation_id"] != target_id:
        raise AdjudicationConflictError("Annotation is not the backend-selected review cursor")
    handler = cursor["handler"]
    handler.load_from_patient_data(patient.patient_id_ext, state)
    event_annotation_id = patient.event_annotation_id
    rows = (
        await session.execute(
            select(Annotation).where(
                col(Annotation.project_id) == project_id,
                or_(col(Annotation.patient_uuid) == patient.id,
                    col(Annotation.patient_id) == patient.patient_id_ext),
                col(Annotation.review_reason) == "event_date_skip",
                col(Annotation.skipped_by_event_annotation_id) == event_annotation_id,
            )
        )
    ).scalars().all()
    event_skip_ids = {str(row.annotation_id) for row in rows}
    statuses = list(state["review_statuses"])
    handler.delete_event_date()
    for index, row_id in enumerate(state["annotation_ids"]):
        if row_id != target_id and row_id not in event_skip_ids:
            state["review_statuses"][index] = statuses[index]
    for row in rows:
        row.status = "U"
        row.review_reason = None
        row.skipped_by_event_annotation_id = None
        row.reviewed_by = None
        row.reviewed_at = None
    patient.event_date = None
    patient.event_annotation_id = None
    patient.event_reviewer = None
    annotation.status = "U"
    annotation.review_reason = None
    annotation.reviewed_by = None
    annotation.reviewed_at = None
    annotation.actor_type = "human"
    cursor = await _save_handler_cursor(
        session, patient, project_id, user_id, run_id, generation, handler, cursor
    )
    await _update_patient_completion(
        session, project_id, patient, user_id, run_id, handler.is_patient_reviewed()
    )
    await _refresh_result(session, project_id, patient.id)
    await session.commit()
    await log_action(
        session, project_id, AuditAction.EVENT_DATE_DELETED,
        user_id=user_id, patient_id=patient.id,
        detail={"annotation_id": str(annotation.annotation_id), "reverted_count": len(rows)},
    )
    return {"annotation": annotation, "patient": patient, "reverted_count": len(rows), "cursor": cursor}


def _normalize_batch(decisions: list[dict]) -> list[dict]:
    normalized: list[dict] = []
    seen: set[str] = set()
    for item in decisions:
        annotation_id = str(item.get("annotation_id", ""))
        raw_status = item.get("status")
        event_date = item.get("event_date")
        if not annotation_id:
            raise AdjudicationConflictError("Review batch contains an invalid decision")
        try:
            status = ReviewStatusEnum(raw_status)
        except ValueError as exc:
            raise AdjudicationConflictError("Review batch contains an invalid status") from exc
        if status not in (ReviewStatusEnum.REVIEWED, ReviewStatusEnum.SKIPPED):
            raise AdjudicationConflictError("Review batch contains an invalid status")
        if annotation_id in seen:
            raise AdjudicationConflictError("Review batch contains a duplicate annotation")
        if status == ReviewStatusEnum.SKIPPED and event_date is not None:
            raise AdjudicationConflictError("Only a reviewed decision may include an event date")
        if isinstance(event_date, datetime):
            event_date = event_date.date()
        if event_date is not None and not isinstance(event_date, date):
            try:
                event_date = date.fromisoformat(str(event_date))
            except ValueError as exc:
                raise AdjudicationConflictError("Event date must be an ISO date") from exc
        seen.add(annotation_id)
        normalized.append({
            "annotation_id": annotation_id,
            "status": status.value,
            "event_date": event_date.isoformat() if event_date else None,
        })
    return normalized


async def _validate_review_snapshot(
    session: AsyncSession,
    project_id: str,
    patient: Patient,
    user_id: str,
    run_id: str,
    generation: int,
    decisions: list[dict],
    skip_after_event: bool | None,
) -> bool:
    """Validate a snapshot without mutating state; returns whether skip is enabled."""
    cursor = await _sync_cursor(
        session, project_id, patient, user_id, run_id, generation, persist=False
    )
    eligible_ids = set(cursor["handler_state"]["annotation_ids"])
    event_count = 0
    for decision in decisions:
        if decision["annotation_id"] not in eligible_ids:
            raise AdjudicationConflictError("Review batch contains an ineligible annotation")
        if decision["event_date"] is not None:
            event_count += 1
    if event_count > 1:
        raise AdjudicationConflictError("Review batch contains multiple event dates")
    return await _skip_after_event_enabled(session, project_id, skip_after_event)


async def _apply_review_snapshot(
    session: AsyncSession,
    project_id: str,
    patient: Patient,
    user_id: str,
    run_id: str,
    generation: int,
    decisions: list[dict],
    skip_after_event: bool | None,
) -> dict:
    """Apply a full, order-independent review snapshot for a patient.

    The snapshot is authoritative: every decision is applied by annotation id
    regardless of order, and any prior event-date skips are recomputed. The
    batch accepts incomplete snapshots (annotations left unreviewed stay
    unreviewed).
    """
    cursor = await _sync_cursor(
        session, project_id, patient, user_id, run_id, generation, persist=False
    )
    state = cursor["handler_state"]
    rows_by_id = {str(row.annotation_id): row for row in state["annotations"]}
    eligible_ids = set(state["annotation_ids"])
    now = now_utc()

    event_decision: dict | None = None
    for decision in decisions:
        target_id = decision["annotation_id"]
        if target_id not in eligible_ids:
            raise AdjudicationConflictError("Review batch contains an ineligible annotation")
        if decision["event_date"] is not None:
            if event_decision is not None:
                raise AdjudicationConflictError("Review batch contains multiple event dates")
            event_decision = decision

    skip_enabled = await _skip_after_event_enabled(session, project_id, skip_after_event)
    event_annotation_id: int | None = None
    event_date: date | None = None
    if event_decision is not None:
        event_annotation_id = int(event_decision["annotation_id"])
        event_date = date.fromisoformat(event_decision["event_date"])

    # A new snapshot is authoritative: clear any prior event-date skips first.
    for row in state["annotations"]:
        if row.review_reason == "event_date_skip":
            row.status = "U"
            row.review_reason = None
            row.skipped_by_event_annotation_id = None
            row.reviewed_by = None
            row.reviewed_at = None
            row.actor_type = None
            row.review_type = None

    for decision in decisions:
        row = rows_by_id[decision["annotation_id"]]
        if decision["status"] == ReviewStatusEnum.SKIPPED.value:
            row.status = "S"
            row.review_reason = None
        else:
            row.status = "R"
            row.review_reason = (
                "human_event" if decision["event_date"] is not None else "human_negative"
            )
        row.skipped_by_event_annotation_id = None
        row.reviewed_by = user_id
        row.reviewed_at = now
        row.actor_type = "human"
        row.review_type = ReviewType.HUMAN.value

    skipped_by_event: dict[str, int] = {}
    if event_annotation_id is not None and skip_enabled:
        for row in state["annotations"]:
            row_id = str(row.annotation_id)
            if row_id == str(event_annotation_id):
                continue
            if row.status == "U" and row.text_date is not None and row.text_date >= event_date:
                row.status = "S"
                row.review_reason = "event_date_skip"
                row.skipped_by_event_annotation_id = event_annotation_id
                row.reviewed_by = user_id
                row.reviewed_at = now
                row.actor_type = "human"
                row.review_type = ReviewType.HUMAN.value
                skipped_by_event[row_id] = event_annotation_id

    for row in state["annotations"]:
        session.add(row)

    if event_annotation_id is not None:
        patient.event_annotation_id = event_annotation_id
        patient.event_date = event_date
        patient.event_reviewer = user_id

    await session.flush()
    cursor = await _sync_cursor(
        session, project_id, patient, user_id, run_id, generation, persist=True
    )
    return {
        "cursor": cursor,
        "handler": cursor["handler"],
        "state": cursor["handler_state"],
        "rows_by_id": {
            str(row.annotation_id): row for row in cursor["handler_state"]["annotations"]
        },
        "event_annotation_id": event_annotation_id,
        "event_date": event_date,
        "skipped_by_event": skipped_by_event,
        "skip_enabled": skip_enabled,
    }


async def submit_review_batch(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    user_id: str,
    idempotency_key: str,
    decisions: list[dict],
    skip_after_event: bool | None = None,
) -> PatientReviewJob:
    payload = _normalize_batch(decisions)
    existing = await session.scalar(
        select(PatientReviewJob).where(
            col(PatientReviewJob.project_id) == project_id,
            col(PatientReviewJob.reviewer_id) == user_id,
            col(PatientReviewJob.idempotency_key) == idempotency_key,
        )
    )
    if existing:
        if existing.payload != payload:
            raise AdjudicationConflictError("Idempotency key was reused for another review batch")
        return existing

    patient = await session.scalar(
        select(Patient)
        .where(
            col(Patient.project_id) == project_id,
            or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
        )
        .with_for_update()
    )
    if not patient:
        raise AdjudicationConflictError("Patient not found")
    if patient.locked_by != user_id:
        raise AdjudicationConflictError("Patient is not locked by this reviewer")

    run_id, generation = await _lock_run_identity(session, project_id)
    if not run_id:
        raise AdjudicationConflictError("No active production run")
    active_job = await session.scalar(
        select(col(PatientReviewJob.id)).where(
            col(PatientReviewJob.patient_uuid) == patient.id,
            col(PatientReviewJob.status).in_(("queued", "running")),
        ).limit(1)
    )
    if active_job:
        raise AdjudicationConflictError("A patient review batch is already processing")

    skip_enabled = await _validate_review_snapshot(
        session, project_id, patient, user_id, run_id, generation, payload,
        skip_after_event,
    )
    patient.locked_at = now_utc()
    session.add(patient)
    job = PatientReviewJob(
        project_id=project_id,
        patient_uuid=patient.id,
        reviewer_id=user_id,
        production_run_id=run_id,
        idempotency_key=idempotency_key,
        payload=payload,
        skip_after_event=skip_enabled,
        status="queued",
    )
    session.add(job)
    await session.commit()
    await session.refresh(job)
    return job


async def enqueue_patient_review_job(project_id: str, job_id: str) -> None:
    """Best-effort enqueue; worker startup recovers durable queued jobs."""
    from app.jobs.review import enqueue_review_job

    await enqueue_review_job(project_id, job_id, attempt=0)


async def apply_patient_review_job(session: AsyncSession, job_id: str) -> PatientReviewJob:
    job = await session.scalar(
        select(PatientReviewJob)
        .where(col(PatientReviewJob.id) == job_id)
        .with_for_update()
    )
    if not job or job.status != "running":
        raise AdjudicationConflictError("Patient review job is not running")
    patient = await session.scalar(
        select(Patient)
        .where(
            col(Patient.id) == job.patient_uuid,
            col(Patient.project_id) == job.project_id,
        )
        .with_for_update()
    )
    if not patient or patient.locked_by != job.reviewer_id:
        raise AdjudicationConflictError("Patient lock no longer belongs to this review job")

    run_id, generation = await _lock_run_identity(session, job.project_id)
    if run_id != job.production_run_id:
        raise AdjudicationConflictError("Review job belongs to a stale production run")

    replay = await _apply_review_snapshot(
        session,
        job.project_id,
        patient,
        job.reviewer_id,
        run_id,
        generation,
        job.payload,
        job.skip_after_event,
    )
    state = replay["state"]
    rows_by_id = replay["rows_by_id"]
    now = now_utc()
    for annotation_id in state["annotation_ids"]:
        annotation = rows_by_id[annotation_id]
        session.add(annotation)

    if replay["event_annotation_id"] is not None:
        patient.event_annotation_id = int(replay["event_annotation_id"])
        patient.event_date = replay["event_date"]
        patient.event_reviewer = job.reviewer_id

    review_type = await _refresh_note_reviews(
        session, job.project_id, patient, run_id, job.reviewer_id, now
    )
    is_reviewed = all(
        status != ReviewStatus.UNREVIEWED for status in state["review_statuses"]
    )
    await _update_patient_completion(
        session, job.project_id, patient, job.reviewer_id, run_id, is_reviewed, review_type
    )
    await _refresh_result(session, job.project_id, patient.id)
    for decision in job.payload:
        action = (
            AuditAction.EVENT_DATE_SET
            if decision["event_date"] is not None
            else AuditAction.ANNOTATION_REVIEWED
        )
        session.add(AuditEntry(
            project_id=job.project_id,
            patient_id=patient.id,
            user_id=job.reviewer_id,
            action=action,
            detail={
                "annotation_id": decision["annotation_id"],
                "review_job_id": job.id,
                "status": decision["status"],
                "event_date": decision["event_date"],
            },
        ))
    job.status = "completed"
    job.last_error = None
    job.completed_at = now
    job.updated_at = now
    session.add_all([job, patient])
    await session.commit()
    await session.refresh(job)
    return job
