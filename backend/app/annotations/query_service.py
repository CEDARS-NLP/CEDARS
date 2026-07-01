"""Query service: annotation lookups, listing, stats, context."""

import logging

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.annotations.schemas import AnnotationStatsResponse
from app.connectors.models import Note, Patient
from app.evaluation.models import EvaluationSession, PatientResult, SearchMatch
from app.nlp.models import Sentence

logger = logging.getLogger(__name__)


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


async def get_annotation_stats(
    session: AsyncSession,
    project_id: str,
) -> AnnotationStatsResponse:
    """Get annotation review statistics for the project.

    Only counts annotations with predicted_label='1' (positive predictions)
    to match the review queue, which only surfaces positive predictions.
    """
    base = select(func.count()).select_from(Annotation).where(
        Annotation.project_id == project_id,
        Annotation.predicted_label == "1",
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
        "note_tags": note.metadata_ or {},
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
            select(PatientResult.session_id)
            .where(PatientResult.pipeline_run_id == pipeline_run_id)
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
            SearchMatch.session_id == session_id,
            SearchMatch.patient_id == patient_id,
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
        .where(Note.id.in_(note_ids))
        .order_by(Note.note_date)
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
    """Reconstruct matched-notes for a patient from their annotations.

    Used for full-pipeline patients that have no SearchMatch rows. The full
    pipeline stores the keyword sentences on the Annotation (``sentence_text``,
    joined with ``"; "``) and the matched tokens on ``matched_tokens``
    (comma-separated), so we can rebuild everything the review UI needs.
    """
    ann_stmt = (
        select(Annotation)
        .where(
            Annotation.project_id == project_id,
            Annotation.patient_id == patient_id,
        )
        .order_by(Annotation.created_at)
    )
    annotations = list((await session.execute(ann_stmt)).scalars().all())
    if not annotations:
        return []

    # Group annotations by note.
    anns_by_note: dict[str, list[Annotation]] = {}
    for a in annotations:
        anns_by_note.setdefault(a.note_id, []).append(a)

    note_ids = list(anns_by_note.keys())
    notes_stmt = (
        select(Note)
        .where(Note.id.in_(note_ids))
        .order_by(Note.note_date)
    )
    notes = list((await session.execute(notes_stmt)).scalars().all())

    def _find_positions(text: str, keywords: list[str]) -> list[dict]:
        """Locate case-insensitive keyword occurrences in the note text."""
        lowered = text.lower()
        positions = []
        for kw in keywords:
            if not kw:
                continue
            start = lowered.find(kw)
            while start != -1:
                positions.append({"start": start, "end": start + len(kw)})
                start = lowered.find(kw, start + 1)
        return positions

    result = []
    for note in notes:
        note_anns = anns_by_note.get(note.id, [])

        # Keywords come from the comma-separated matched_tokens.
        keywords: list[str] = []
        for a in note_anns:
            for tok in (a.matched_tokens or "").split(","):
                tok = tok.strip()
                if len(tok) >= 2:
                    keywords.append(tok.lower())
        keywords = sorted(set(keywords))

        # Matched sentences come from the "; "-joined sentence_text.
        matched_sentences: list[str] = []
        for a in note_anns:
            for sent in (a.sentence_text or "").split(";"):
                sent = sent.strip()
                if sent and sent not in matched_sentences:
                    matched_sentences.append(sent)

        result.append({
            "note_id": note.id,
            "text_id": note.text_id,
            "text": note.text,
            "note_date": note.note_date.isoformat() if note.note_date else None,
            "note_tags": note.metadata_ or {},
            "matched_sentences": matched_sentences,
            "match_positions": _find_positions(note.text, keywords),
            "search_keywords": keywords,
        })

    return result
