"""Evaluation service: session CRUD, search query execution, funnel stats."""

import logging
import random
from datetime import UTC, datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.connectors.models import Note, Patient
from app.evaluation.models import (
    EvaluationSession,
    PatientResult,
    PatientResultStatus,
    SearchMatch,
    SessionStatus,
)
from app.nlp.engine import parse_query, process_note

logger = logging.getLogger(__name__)


# ── Session CRUD ─────────────────────────────────────────────────


async def create_session(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    search_queries: list[dict] | None = None,
    cloned_from_id: str | None = None,
) -> EvaluationSession:
    """Create a new evaluation session with patient sampling.

    Rules:
    - Block if an active session (DRAFT or REVIEWING) already exists for the project.
    - Block if a COMMITTED session exists for the project.
    - Sample min(100, total_patients) patients from the project.
    - If cloned_from_id is provided, copy queries + LLM config from that session.
    """
    # Check for blocking sessions
    blocking_stmt = select(EvaluationSession).where(
        EvaluationSession.project_id == project_id,
        EvaluationSession.status.in_([
            SessionStatus.DRAFT,
            SessionStatus.REVIEWING,
            SessionStatus.COMMITTED,
        ]),
    )
    result = await db.execute(blocking_stmt)
    blocking = result.scalars().first()
    if blocking:
        raise ValueError(
            f"Cannot create session: project already has a {blocking.status.value} session"
        )

    # Handle cloning
    queries = search_queries or []
    event_name = None
    event_description = None
    include_criteria = None
    exclude_criteria = None
    llm_provider = None
    llm_model = None
    llm_api_base = None

    if cloned_from_id:
        clone_source = (
            await db.execute(
                select(EvaluationSession).where(EvaluationSession.id == cloned_from_id)
            )
        ).scalar_one_or_none()
        if clone_source:
            queries = queries or clone_source.search_queries or []
            event_name = clone_source.event_name
            event_description = clone_source.event_description
            include_criteria = clone_source.include_criteria
            exclude_criteria = clone_source.exclude_criteria
            llm_provider = clone_source.llm_provider
            llm_model = clone_source.llm_model
            llm_api_base = clone_source.llm_api_base

    # Sample patients
    patient_stmt = select(Patient.id).where(Patient.project_id == project_id)
    result = await db.execute(patient_stmt)
    all_patient_ids = [r[0] for r in result.all()]

    sample_size = min(100, len(all_patient_ids))
    sampled_ids = random.sample(all_patient_ids, sample_size) if all_patient_ids else []

    session = EvaluationSession(
        project_id=project_id,
        created_by=user_id,
        status=SessionStatus.DRAFT,
        search_queries=queries,
        sample_patient_ids=sampled_ids,
        sample_size=sample_size,
        cloned_from_id=cloned_from_id,
        event_name=event_name,
        event_description=event_description,
        include_criteria=include_criteria,
        exclude_criteria=exclude_criteria,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_base=llm_api_base,
    )
    db.add(session)
    await db.flush()
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(
    db: AsyncSession,
    session_id: str,
) -> EvaluationSession | None:
    """Get an evaluation session by ID."""
    result = await db.execute(
        select(EvaluationSession).where(EvaluationSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def list_sessions(
    db: AsyncSession,
    project_id: str,
) -> list[EvaluationSession]:
    """List all sessions for a project, ordered by created_at desc."""
    stmt = (
        select(EvaluationSession)
        .where(EvaluationSession.project_id == project_id)
        .order_by(EvaluationSession.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def discard_session(
    db: AsyncSession,
    session_id: str,
) -> EvaluationSession:
    """Set session status to DISCARDED. Only allowed from DRAFT or REVIEWING."""
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    if session.status not in (SessionStatus.DRAFT, SessionStatus.REVIEWING):
        raise ValueError(
            f"Cannot discard session in {session.status.value} status; "
            "only DRAFT or REVIEWING sessions can be discarded"
        )

    session.status = SessionStatus.DISCARDED
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def update_queries(
    db: AsyncSession,
    session_id: str,
    search_queries: list[dict],
) -> EvaluationSession:
    """Update the query list and clear old SearchMatch records."""
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    session.search_queries = search_queries
    session.updated_at = datetime.now(UTC)
    db.add(session)

    # Clear old search matches
    await db.execute(
        delete(SearchMatch).where(SearchMatch.session_id == session_id)
    )

    await db.commit()
    await db.refresh(session)
    return session


async def update_llm_config(
    db: AsyncSession,
    session_id: str,
    **kwargs,
) -> EvaluationSession:
    """Update LLM configuration fields on the session."""
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    allowed_fields = {
        "event_name", "event_description", "include_criteria",
        "exclude_criteria", "llm_provider", "llm_model", "llm_api_base",
    }
    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(session, key, value)

    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Search execution ─────────────────────────────────────────────


async def execute_search_queries(
    db: AsyncSession,
    session_id: str,
) -> EvaluationSession:
    """Run spaCy search on sample notes for each include query.

    For each include query, uses parse_query and process_note from app.nlp.engine
    to find matching sentences. Stores SearchMatch records for each match.
    """
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    # Clear existing matches
    await db.execute(
        delete(SearchMatch).where(SearchMatch.session_id == session_id)
    )

    sample_patient_ids = session.sample_patient_ids or []
    if not sample_patient_ids:
        await db.commit()
        await db.refresh(session)
        return session

    # Get all notes for sampled patients
    notes_stmt = select(Note).where(Note.patient_id.in_(sample_patient_ids))
    result = await db.execute(notes_stmt)
    notes = result.scalars().all()

    queries = session.search_queries or []
    include_queries = [q for q in queries if q.get("type") == "include"]

    for query_index, query_def in enumerate(include_queries):
        query_str = query_def.get("query", "")
        if not query_str:
            continue

        query_groups = parse_query(query_str)
        if not query_groups:
            continue

        for note in notes:
            sentences = process_note(note.text, query_groups)
            for sent in sentences:
                if sent.get("is_target") and not sent.get("is_negated"):
                    match = SearchMatch(
                        session_id=session_id,
                        query_index=query_index,
                        patient_id=note.patient_id,
                        note_id=note.id,
                        matched_tokens=sent.get("matched_tokens", []),
                        match_positions=[{
                            "start": sent["start_pos"],
                            "end": sent["end_pos"],
                            "sentence_number": sent["sentence_number"],
                            "text": sent["text"],
                        }],
                        is_negated=sent.get("is_negated", False),
                    )
                    db.add(match)

    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Stats & queries ──────────────────────────────────────────────


async def get_funnel_stats(
    db: AsyncSession,
    session_id: str,
) -> dict:
    """Return funnel statistics for an evaluation session.

    Returns:
        sample_patients: number of sampled patients
        sample_notes: number of notes for sampled patients
        matched_patients: patients with at least one search match
        matched_notes: notes with at least one search match
        filter_percent: percentage of notes filtered by search
        llm_stats: LLM processing statistics (from patient results)
    """
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    sample_patient_ids = session.sample_patient_ids or []
    sample_patients = len(sample_patient_ids)

    # Count notes for sampled patients
    if sample_patient_ids:
        notes_count_result = await db.execute(
            select(func.count(Note.id)).where(Note.patient_id.in_(sample_patient_ids))
        )
        sample_notes = notes_count_result.scalar() or 0
    else:
        sample_notes = 0

    # Count matched patients and notes from SearchMatch
    matched_patients_result = await db.execute(
        select(func.count(func.distinct(SearchMatch.patient_id))).where(
            SearchMatch.session_id == session_id
        )
    )
    matched_patients = matched_patients_result.scalar() or 0

    matched_notes_result = await db.execute(
        select(func.count(func.distinct(SearchMatch.note_id))).where(
            SearchMatch.session_id == session_id
        )
    )
    matched_notes = matched_notes_result.scalar() or 0

    filter_percent = (
        round((1 - matched_notes / sample_notes) * 100, 1) if sample_notes > 0 else 0.0
    )

    # LLM stats from patient results
    llm_completed_result = await db.execute(
        select(func.count(PatientResult.id)).where(
            PatientResult.session_id == session_id,
            PatientResult.status == PatientResultStatus.COMPLETED,
        )
    )
    llm_completed = llm_completed_result.scalar() or 0

    llm_pending_result = await db.execute(
        select(func.count(PatientResult.id)).where(
            PatientResult.session_id == session_id,
            PatientResult.status.in_([
                PatientResultStatus.QUEUED,
                PatientResultStatus.PROCESSING,
            ]),
        )
    )
    llm_pending = llm_pending_result.scalar() or 0

    llm_failed_result = await db.execute(
        select(func.count(PatientResult.id)).where(
            PatientResult.session_id == session_id,
            PatientResult.status == PatientResultStatus.FAILED,
        )
    )
    llm_failed = llm_failed_result.scalar() or 0

    return {
        "sample_patients": sample_patients,
        "sample_notes": sample_notes,
        "matched_patients": matched_patients,
        "matched_notes": matched_notes,
        "filter_percent": filter_percent,
        "llm_stats": {
            "completed": llm_completed,
            "pending": llm_pending,
            "failed": llm_failed,
        },
    }


async def get_query_matches(
    db: AsyncSession,
    session_id: str,
    query_index: int,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Return paginated note previews with match highlights for a query.

    Returns:
        total: total number of matches
        page: current page
        page_size: items per page
        matches: list of match dicts with note text and highlights
    """
    # Count total matches
    count_result = await db.execute(
        select(func.count(SearchMatch.id)).where(
            SearchMatch.session_id == session_id,
            SearchMatch.query_index == query_index,
        )
    )
    total = count_result.scalar() or 0

    # Get paginated matches
    offset = (page - 1) * page_size
    matches_stmt = (
        select(SearchMatch)
        .where(
            SearchMatch.session_id == session_id,
            SearchMatch.query_index == query_index,
        )
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(matches_stmt)
    matches = result.scalars().all()

    # Enrich with note text
    items = []
    for match in matches:
        note = (
            await db.execute(select(Note).where(Note.id == match.note_id))
        ).scalar_one_or_none()

        note_text = note.text if note else ""
        # Build highlight context from match_positions
        highlights = []
        for pos in (match.match_positions or []):
            highlights.append({
                "text": pos.get("text", ""),
                "start": pos.get("start", 0),
                "end": pos.get("end", 0),
                "sentence_number": pos.get("sentence_number", 0),
            })

        items.append({
            "match_id": match.id,
            "note_id": match.note_id,
            "patient_id": match.patient_id,
            "matched_tokens": match.matched_tokens,
            "is_negated": match.is_negated,
            "highlights": highlights,
            "note_text": note_text,
        })

    return {
        "total": total,
        "page": page,
        "page_size": page_size,
        "matches": items,
    }
