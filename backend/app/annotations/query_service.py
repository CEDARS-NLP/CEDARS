"""Query service: annotation lookups, listing, stats, context."""

import logging

from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.filters import reviewable_filter
from app.annotations.models import Annotation
from app.annotations.schemas import AnnotationStatsResponse
from app.connectors.models import Note, Patient
from app.evaluation.models import EvaluationSession, PatientResult, SearchMatch
from app.nlp.models import SearchQuery, Sentence
from app.production.models import NotePrediction, ProductionRun, ProductionState

logger = logging.getLogger(__name__)
_STATUS_TO_API = {"U": "unreviewed", "R": "reviewed", "S": "skipped"}
_API_TO_STATUS = {value: key for key, value in _STATUS_TO_API.items()}


async def _production_search_finished(
    session: AsyncSession, project_id: str, run_id: str
) -> bool:
    if not run_id:
        return True
    run = await session.get(ProductionRun, run_id, populate_existing=True)
    if not run or run.project_id != project_id:
        return False
    scanned = (run.progress_metadata or {}).get("scanned_note_match_counts", {})
    return run.status == "completed" or len(scanned) >= run.total_notes


async def _patient_review_ready(
    session: AsyncSession, project_id: str, patient_id: str, run_id: str
) -> bool:
    if not run_id:
        return True
    if not await _production_search_finished(session, project_id, run_id):
        return False
    predictions = (
        await session.scalars(
            select(NotePrediction).where(
                col(NotePrediction.project_id) == project_id,
                col(NotePrediction.run_id) == run_id,
                col(NotePrediction.patient_id) == patient_id,
            )
        )
    ).all()
    if any(row.status != "succeeded" for row in predictions):
        return False
    from app.production.service import _llm_enabled

    run = await session.get(ProductionRun, run_id)
    if _llm_enabled(run.config_snapshot):
        matched_notes = set(
            await session.scalars(
                select(col(Annotation.text_id)).where(
                    col(Annotation.project_id) == project_id,
                    col(Annotation.production_run_id) == run_id,
                    col(Annotation.patient_id) == patient_id,
                )
            )
        )
        return matched_notes.issubset({row.text_id for row in predictions})
    return True


async def serialize_annotation(
    session: AsyncSession, annotation: Annotation
) -> dict:
    """Build the legacy API shape from external IDs and current linked records."""
    note = None
    if annotation.note_uuid:
        note = await session.get(Note, annotation.note_uuid)
    if note is None:
        note = (
            await session.execute(
                select(Note).where(
                    col(Note.project_id) == annotation.project_id,
                    col(Note.text_id) == annotation.text_id,
                    col(Note.patient_id_ext) == annotation.patient_id,
                )
            )
        ).scalar_one_or_none()
    patient = None
    if annotation.patient_uuid:
        patient = await session.get(Patient, annotation.patient_uuid)
    if patient is None:
        patient = (
            await session.execute(
                select(Patient).where(
                    col(Patient.project_id) == annotation.project_id,
                    col(Patient.patient_id_ext) == annotation.patient_id,
                )
            )
        ).scalar_one_or_none()

    production_state = await session.get(ProductionState, annotation.project_id)
    prediction = None
    if production_state and production_state.active_run_id:
        prediction = (
            await session.execute(
                select(NotePrediction).where(
                    col(NotePrediction.project_id) == annotation.project_id,
                    col(NotePrediction.run_id) == production_state.active_run_id,
                    col(NotePrediction.text_id) == annotation.text_id,
                )
            )
        ).scalar_one_or_none()

    current_event_date = (
        patient.event_date
        if patient and patient.event_annotation_id == annotation.annotation_id
        else None
    )
    return {
        "id": str(annotation.annotation_id),
        "project_id": annotation.project_id,
        "patient_id": patient.id if patient else annotation.patient_id,
        "patient_id_ext": annotation.patient_id,
        "note_id": note.id if note else (annotation.note_uuid or annotation.text_id),
        "sentence_id": None,
        "sentence_text": annotation.sentence,
        "matched_tokens": annotation.token,
        "is_negated": annotation.isNegated,
        "review_excluded": annotation.review_reason in {"llm_negative", "duplicate", "negated"},
        "manual_review_override": False,
        "token": annotation.token,
        "note_start_index": annotation.note_start_index,
        "note_end_index": annotation.note_end_index,
        "sentence_number": annotation.sentence_number,
        "sentence_start": annotation.sentence_start,
        "sentence_end": annotation.sentence_end,
        "text_date": annotation.text_date,
        "predicted_score": prediction.score if prediction else None,
        "predicted_label": prediction.label if prediction else None,
        "evidence_spans": prediction.evidence_spans if prediction else None,
        "predictor_model": (prediction.model_fingerprint or "") if prediction else "",
        "reasoning": prediction.reasoning if prediction else None,
        "review_status": _STATUS_TO_API[annotation.status],
        "review_type": annotation.review_type,
        "reviewed_by": annotation.reviewed_by,
        "reviewed_at": annotation.reviewed_at,
        "event_date": current_event_date,
        "created_at": annotation.created_at,
        "note_date": note.note_date if note else None,
        "note_text_id": annotation.text_id,
    }


async def get_annotation(
    session: AsyncSession,
    project_id: str,
    annotation_id: str | int,
) -> Annotation | None:
    try:
        numeric_id = int(annotation_id)
    except (TypeError, ValueError):
        return None
    stmt = select(Annotation).where(
        col(Annotation.annotation_id) == numeric_id,
        col(Annotation.project_id) == project_id,
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
) -> list[dict]:
    """List annotations through explicit compatibility serialization."""
    stmt = select(Annotation).where(col(Annotation.project_id) == project_id)

    if status:
        stmt = stmt.where(col(Annotation.status) == _API_TO_STATUS.get(status, status))
    if patient_id:
        stmt = stmt.where(
            or_(col(Annotation.patient_id) == patient_id,
                col(Annotation.patient_uuid) == patient_id)
        )

    stmt = stmt.order_by(
        col(Annotation.text_date), col(Annotation.text_id), col(Annotation.note_start_index)
    ).offset(offset).limit(limit)
    result = await session.execute(stmt)
    return [await serialize_annotation(session, row) for row in result.scalars().all()]


async def get_patient_annotations(
    session: AsyncSession, project_id: str, patient_id: str
) -> list[dict]:
    """Return a patient's annotations in note chronology and occurrence order."""
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient:
        return []
    rows = (
        await session.execute(
            select(Annotation, Note)
            .join(
                Note,
                and_(
                    col(Note.project_id) == col(Annotation.project_id),
                    col(Note.text_id) == col(Annotation.text_id),
                    col(Note.patient_id_ext) == col(Annotation.patient_id),
                ),
            )
            .where(
                col(Annotation.project_id) == project_id,
                or_(col(Annotation.patient_uuid) == patient.id,
                    col(Annotation.patient_id) == patient.patient_id_ext),
            )
            .order_by(
                col(Note.note_date), col(Note.text_id),
                col(Annotation.sentence_number), col(Annotation.note_start_index),
            )
        )
    ).all()
    annotations = []
    for annotation, note in rows:
        item = await serialize_annotation(session, annotation)
        item["note_date"] = note.note_date
        item["note_text_id"] = note.text_id
        annotations.append(item)
    return annotations


async def get_next_unreviewed(
    session: AsyncSession,
    project_id: str,
    patient_id: str | None = None,
) -> dict | None:
    """Get the next unreviewed annotation for review."""
    stmt = select(Annotation).where(
        col(Annotation.project_id) == project_id,
        col(Annotation.status) == "U",
        reviewable_filter(),
    )

    production_state = await session.get(ProductionState, project_id, populate_existing=True)
    run_id = production_state.active_run_id if production_state else None
    if run_id:
        stmt = stmt.where(col(Annotation.production_run_id) == run_id)
    if patient_id:
        stmt = stmt.where(
            or_(col(Annotation.patient_id) == patient_id,
                col(Annotation.patient_uuid) == patient_id)
        )
    stmt = stmt.order_by(
        col(Annotation.text_date), col(Annotation.text_id), col(Annotation.note_start_index)
    )
    result = await session.execute(stmt)
    readiness = {}
    for annotation in result.scalars():
        if annotation.patient_id not in readiness:
            readiness[annotation.patient_id] = await _patient_review_ready(
                session, project_id, annotation.patient_id, run_id or ""
            )
        if readiness[annotation.patient_id]:
            return await serialize_annotation(session, annotation)
    return None


async def get_annotation_stats(
    session: AsyncSession,
    project_id: str,
) -> AnnotationStatsResponse:
    """Get annotation review statistics for the project.

    Scoped to the same set the review queue surfaces: annotations not ruled out
    by an optional predictor.
    """
    base = select(func.count()).select_from(Annotation).where(
        col(Annotation.project_id) == project_id,
        reviewable_filter(),
    )

    total = (await session.execute(base)).scalar() or 0
    unreviewed = (
        await session.execute(
            base.where(col(Annotation.status) == "U")
        )
    ).scalar() or 0
    reviewed = (
        await session.execute(
            base.where(col(Annotation.status) == "R")
        )
    ).scalar() or 0
    skipped = (
        await session.execute(
            base.where(col(Annotation.status) == "S")
        )
    ).scalar() or 0
    events_found = (
        await session.execute(
            select(func.count()).select_from(Patient).where(
                col(Patient.project_id) == project_id,
                col(Patient.event_date).isnot(None),
            )
        )
    ).scalar() or 0

    return AnnotationStatsResponse(
        total=total,
        unreviewed=unreviewed,
        reviewed=reviewed,
        skipped=skipped,
        events_found=events_found,
        is_complete=total > 0 and unreviewed == 0,
    )


async def get_note_context(
    session: AsyncSession,
    note_id: str,
) -> dict | None:
    """Get full note text and all sentences for annotation context display."""
    note = (await session.execute(select(Note).where(col(Note.id) == note_id))).scalar_one_or_none()
    if not note:
        return None

    production_state = await session.get(ProductionState, note.project_id)
    prediction = None
    if production_state and production_state.active_run_id:
        prediction = (
            await session.execute(
                select(NotePrediction).where(
                    col(NotePrediction.project_id) == note.project_id,
                    col(NotePrediction.run_id) == production_state.active_run_id,
                    col(NotePrediction.text_id) == note.text_id,
                )
            )
        ).scalar_one_or_none()
    active_query = (
        await session.execute(
            select(SearchQuery).where(
                col(SearchQuery.project_id) == note.project_id,
                col(SearchQuery.is_active).is_(True),
                col(SearchQuery.deleted_at).is_(None),
            ).limit(1)
        )
    ).scalar_one_or_none()
    exclude_negated = bool(active_query and active_query.exclude_negated)

    patient = (
        await session.execute(select(Patient).where(col(Patient.id) == note.patient_id))
    ).scalar_one_or_none()

    sentences = (
        await session.execute(
            select(Sentence)
            .where(col(Sentence.note_id) == note_id)
            .order_by(col(Sentence.sentence_number))
        )
    ).scalars().all()
    excluded_sentence_ids = set(
        (
            await session.execute(
                select(col(Annotation.sentence_number)).where(
                    col(Annotation.note_uuid) == note_id,
                    col(Annotation.review_reason).in_(
                        ("llm_negative", "duplicate", "negated")
                        if exclude_negated else ("llm_negative", "duplicate")
                    ),
                )
            )
        ).scalars().all()
    )

    return {
        "note_id": note.id,
        "patient_id": note.patient_id,
        "patient_id_ext": patient.patient_id_ext if patient else note.patient_id,
        "text": note.text,
        "text_id": note.text_id,
        "note_date": note.note_date.isoformat() if note.note_date else None,
        "note_tags": note.metadata_ or {},
        "current_note_evidence": prediction.evidence_spans if prediction else [],
        "sentences": [
            {
                "id": s.id,
                "text": s.text,
                "start_pos": s.start_pos,
                "end_pos": s.end_pos,
                "is_target": s.is_target,
                "is_negated": s.is_negated,
                "review_excluded": s.sentence_number in excluded_sentence_ids,
                "matched_tokens": s.matched_tokens,
            }
            for s in sentences
        ],
        "annotation_spans": [
            {
                "annotation_id": str(row.annotation_id),
                "start": row.note_start_index,
                "end": row.note_end_index,
                "sentence_start": row.sentence_start,
                "sentence_end": row.sentence_end,
                "sentence_number": row.sentence_number,
                "is_negated": row.isNegated,
            }
            for row in (
                await session.execute(
                    select(Annotation).where(
                        col(Annotation.project_id) == note.project_id,
                        col(Annotation.text_id) == note.text_id,
                        col(Annotation.patient_id) == (patient.patient_id_ext if patient else ""),
                        *([col(Annotation.isNegated).is_(False)] if exclude_negated else []),
                    )
                    .order_by(col(Annotation.note_start_index))
                )
            ).scalars().all()
        ],
    }


async def get_patient_matched_notes(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    pipeline_run_id: str | None,
) -> list[dict]:
    """Get all notes with keyword matches for a patient, using SearchMatch data.

    Returns notes ordered chronologically, each with:
    - note metadata (id, text_id, date, tags)
    - matched_sentences: list of {text, start, end} from match_positions
    - full note text
    - search_keywords

    SearchMatch rows only exist for the sample/preview phase. Patients processed
    by the full pipeline have no SearchMatch rows (the full job discards keyword
    matches after building the annotation), so fall back to reconstructing the
    payload from the patient's annotations.
    """
    session_id = None
    if pipeline_run_id:
        # Trace pipeline_run → eval session
        stmt = (
            select(col(PatientResult.session_id))
            .where(col(PatientResult.pipeline_run_id) == pipeline_run_id)
            .distinct()
            .limit(1)
        )
        row = (await session.execute(stmt)).first()
        if row and row[0]:
            session_id = row[0]

    search_matches: list = []
    if session_id:
        # Get SearchMatch records for this patient in this session
        matches_stmt = select(SearchMatch).where(
            col(SearchMatch.session_id) == session_id,
            col(SearchMatch.patient_id) == patient_id,
        )
        search_matches = list((await session.execute(matches_stmt)).scalars().all())

    if not search_matches:
        # Full-pipeline patients have no SearchMatch rows; build from annotations.
        return await _matched_notes_from_annotations(session, project_id, patient_id)

    # Group by note_id
    matches_by_note: dict[str, list] = {}
    for m in search_matches:
        matches_by_note.setdefault(m.note_id, []).append(m)

    # Fetch notes
    note_ids = list(matches_by_note.keys())
    notes_stmt = (
        select(Note)
        .where(col(Note.id).in_(note_ids))
        .order_by(col(Note.note_date))
    )
    notes = list((await session.execute(notes_stmt)).scalars().all())

    # Get search keywords
    eval_session = await session.get(EvaluationSession, session_id)
    search_keywords: list[str] = []
    if eval_session and eval_session.search_queries:
        import re
        for sq in eval_session.search_queries:
            query = sq.get("query", "")
            cleaned = re.sub(r"\b(AND|OR|NOT)\b", " ", query, flags=re.IGNORECASE)
            cleaned = re.sub(r"[()\"']", " ", cleaned)
            for token in cleaned.split():
                token = token.strip().rstrip("*")
                if len(token) >= 2:
                    search_keywords.append(token.lower())
        search_keywords = sorted(set(search_keywords))

    # Build response
    result = []
    for note in notes:
        note_matches = matches_by_note.get(note.id, [])
        all_positions = []
        matched_sentences = []
        for m in note_matches:
            for pos in (m.match_positions or []):
                all_positions.append(pos)
                if pos.get("text"):
                    matched_sentences.append(pos["text"])

        result.append({
            "note_id": note.id,
            "text_id": note.text_id,
            "text": note.text,
            "note_date": note.note_date.isoformat() if note.note_date else None,
            "note_tags": note.metadata_ or {},
            "matched_sentences": matched_sentences,
            "match_positions": all_positions,
            "search_keywords": search_keywords,
        })

    return result


async def _matched_notes_from_annotations(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
) -> list[dict]:
    """Build production review context from actual stored match offsets."""
    patient = (
        await session.execute(
            select(Patient).where(
                col(Patient.project_id) == project_id,
                or_(col(Patient.id) == patient_id, col(Patient.patient_id_ext) == patient_id),
            )
        )
    ).scalar_one_or_none()
    if not patient:
        return []
    rows = (
        await session.execute(
            select(Annotation, Note)
            .join(
                Note,
                and_(
                    col(Note.project_id) == col(Annotation.project_id),
                    col(Note.text_id) == col(Annotation.text_id),
                    col(Note.patient_id_ext) == col(Annotation.patient_id),
                ),
            )
            .where(
                col(Annotation.project_id) == project_id,
                col(Annotation.patient_id) == patient.patient_id_ext,
            )
            .order_by(
                col(Note.note_date), col(Note.text_id), col(Annotation.sentence_number),
                col(Annotation.note_start_index),
            )
        )
    ).all()
    notes_by_text_id: dict[str, dict] = {}
    for annotation, note in rows:
        item = notes_by_text_id.setdefault(
            note.text_id,
            {
                "note_id": note.id,
                "text_id": note.text_id,
                "text": note.text,
                "note_date": note.note_date.isoformat() if note.note_date else None,
                "note_tags": note.metadata_ or {},
                "matched_sentences": [],
                "match_positions": [],
                "search_keywords": [],
            },
        )
        if annotation.sentence not in item["matched_sentences"]:
            item["matched_sentences"].append(annotation.sentence)
        item["match_positions"].append({
            "start": annotation.note_start_index,
            "end": annotation.note_end_index,
            "text": annotation.token,
            "sentence": annotation.sentence,
            "sentence_start": annotation.sentence_start,
            "sentence_end": annotation.sentence_end,
            "sentence_number": annotation.sentence_number,
            "is_negated": annotation.isNegated,
        })
        if annotation.token and annotation.token not in item["search_keywords"]:
            item["search_keywords"].append(annotation.token)
    return list(notes_by_text_id.values())
