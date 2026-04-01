"""Evaluation service: session CRUD, search query execution, funnel stats, LLM run, review, metrics, commit."""

import logging
import math
import random
from datetime import UTC, datetime
from types import SimpleNamespace

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
from app.pipeline.classifier import classify_patient
from app.pipeline.models import EventConfig, PipelineRun, PipelineRunStatus


async def _enqueue_eval_pipeline_run(run_id: str) -> None:
    """Enqueue the eval-specific pipeline job (processes PatientResult rows)."""
    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        await redis.enqueue_job("run_eval_pipeline_job", run_id)
        await redis.aclose()
        logger.info("Enqueued eval pipeline run %s to ARQ", run_id)
    except Exception:
        logger.exception("Failed to enqueue eval pipeline run %s", run_id)

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
            f"Cannot create session: project already has a {getattr(blocking.status, 'value', blocking.status)} session"
        )

    # Handle cloning
    queries = search_queries or []
    event_name = None
    event_description = None
    include_criteria = None
    exclude_criteria = None

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
            f"Cannot discard session in {getattr(session.status, 'value', session.status)} status; "
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
        "event_name", "event_description", "include_criteria", "exclude_criteria",
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


# ── LLM classification ──────────────────────────────────────────


async def run_llm_on_sample(
    db: AsyncSession,
    session_id: str,
    project_id: str,
) -> dict:
    """Enqueue background LLM classification on matched patients in the sample.

    Validates config, clears previous sample results, marks session as
    classifying, and enqueues an ARQ job. Returns immediately with status.
    """
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    # Check if already running
    metrics = session.metrics or {}
    if metrics.get("llm_status") == "running":
        raise ValueError("LLM classification is already running for this session.")

    # Validate LLM config
    from app.projects.models import Project
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()

    if not project.llm_provider or not project.llm_model:
        raise ValueError(
            "Project LLM configuration is required. Set the LLM provider and model in project settings."
        )

    # Clear previous sample results (pipeline_run_id IS NULL)
    await db.execute(
        delete(PatientResult).where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id.is_(None),
        )
    )

    # Count matched patients for progress tracking
    matched_stmt = select(func.count(func.distinct(SearchMatch.patient_id))).where(
        SearchMatch.session_id == session_id,
        SearchMatch.is_negated.is_(False),
    )
    matched_count = (await db.execute(matched_stmt)).scalar() or 0

    # Mark session as classifying
    session.metrics = {
        **(session.metrics or {}),
        "llm_status": "running",
        "llm_total": matched_count,
        "llm_completed": 0,
        "llm_failed": 0,
    }
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    # Enqueue background job
    try:
        from arq import create_pool
        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        await redis.enqueue_job("run_sample_llm_job", session_id, project_id)
        await redis.aclose()
    except Exception:
        logger.exception("Failed to enqueue sample LLM job for session %s", session_id)
        # Roll back the running status
        session.metrics = {
            **(session.metrics or {}),
            "llm_status": "failed",
        }
        db.add(session)
        await db.commit()
        raise ValueError("Failed to enqueue LLM classification job. Check worker status.")

    return {
        "status": "started",
        "matched_patients": matched_count,
    }


async def execute_sample_llm(
    session_id: str,
    project_id: str,
    db_session: AsyncSession | None = None,
) -> dict:
    """Background job: classify all matched patients in the evaluation sample.

    Uses its own database session unless db_session is provided (for testing).
    Updates session metrics with progress. Sets session status to REVIEWING on completion.
    """
    from app.projects.models import Project

    if db_session is not None:
        return await _execute_sample_llm_impl(db_session, session_id, project_id)

    from app.common.database import async_session
    async with async_session() as db:
        return await _execute_sample_llm_impl(db, session_id, project_id)


async def _execute_sample_llm_impl(
    db: AsyncSession,
    session_id: str,
    project_id: str,
) -> dict:
    from app.projects.models import Project

    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    sample_patient_ids = set(session.sample_patient_ids or [])

    # Find matched patient IDs from non-negated SearchMatch records
    matched_stmt = select(func.distinct(SearchMatch.patient_id)).where(
        SearchMatch.session_id == session_id,
        SearchMatch.is_negated.is_(False),
    )
    result = await db.execute(matched_stmt)
    matched_patient_ids = {r[0] for r in result.all()}

    # Read LLM config from project
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()

    config = SimpleNamespace(
        name=session.event_name or "",
        description=session.event_description or "",
        include_criteria=session.include_criteria or "",
        exclude_criteria=session.exclude_criteria or "",
        llm_provider=project.llm_provider,
        llm_model=project.llm_model,
        llm_api_base=project.llm_api_base,
    )

    patients_classified = 0
    patients_failed = 0
    total_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for patient_id in matched_patient_ids:
        notes_stmt = (
            select(Note)
            .where(
                Note.patient_id == patient_id,
                Note.id.in_(
                    select(SearchMatch.note_id).where(
                        SearchMatch.session_id == session_id,
                        SearchMatch.patient_id == patient_id,
                        SearchMatch.is_negated.is_(False),
                    )
                ),
            )
            .order_by(Note.note_date)
        )
        notes_result = await db.execute(notes_stmt)
        notes = notes_result.scalars().all()

        excerpts = [
            {
                "note_id": note.id,
                "text": note.text,
                "note_date": note.note_date.isoformat() if note.note_date else "unknown",
            }
            for note in notes
        ]

        try:
            classification = await classify_patient(excerpts, config)
            pr = PatientResult(
                session_id=session_id,
                patient_id=patient_id,
                notes_searched=len(notes),
                notes_matched=len(notes),
                finding_label=classification.label,
                finding_reasoning=classification.reasoning,
                finding_evidence=classification.evidence,
                event_date=classification.event_date,
                predicted_score=classification.confidence,
                token_usage=classification.token_usage,
                status=PatientResultStatus.COMPLETED,
                completed_at=datetime.now(UTC),
            )
            db.add(pr)
            patients_classified += 1

            if classification.token_usage:
                for key in total_token_usage:
                    total_token_usage[key] += classification.token_usage.get(key, 0)

        except Exception as exc:
            logger.warning("LLM classification failed for patient %s: %s", patient_id, exc)
            pr = PatientResult(
                session_id=session_id,
                patient_id=patient_id,
                notes_searched=len(notes),
                notes_matched=len(notes),
                status=PatientResultStatus.FAILED,
                error_message=str(exc),
                completed_at=datetime.now(UTC),
            )
            db.add(pr)
            patients_failed += 1

        # Update progress in session metrics
        session.metrics = {
            **(session.metrics or {}),
            "llm_status": "running",
            "llm_total": len(matched_patient_ids),
            "llm_completed": patients_classified,
            "llm_failed": patients_failed,
        }
        db.add(session)
        await db.commit()
        await db.refresh(session)

    # Create NO_MATCH results for unmatched sample patients
    unmatched_ids = sample_patient_ids - matched_patient_ids
    for patient_id in unmatched_ids:
        pr = PatientResult(
            session_id=session_id,
            patient_id=patient_id,
            status=PatientResultStatus.NO_MATCH,
            completed_at=datetime.now(UTC),
        )
        db.add(pr)

    # Finalize session
    session.status = SessionStatus.REVIEWING
    session.metrics = {
        **(session.metrics or {}),
        "llm_status": "completed",
        "llm_total": len(matched_patient_ids),
        "llm_completed": patients_classified,
        "llm_failed": patients_failed,
        "llm_no_match": len(unmatched_ids),
        "token_usage": total_token_usage,
    }
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    return {
        "patients_classified": patients_classified,
        "patients_no_match": len(unmatched_ids),
        "patients_failed": patients_failed,
        "token_usage": total_token_usage,
    }


# ── Review & results ─────────────────────────────────────────────


async def list_patient_results(
    db: AsyncSession,
    session_id: str,
    label_filter: str | None = None,
    reviewed_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """Return paginated patient results with optional filtering.

    Args:
        label_filter: Filter by finding_label (e.g. "positive", "negative"). "all" or None = no filter.
        reviewed_filter: "unreviewed" to show only unreviewed results.
        page: 1-based page number.
        page_size: Results per page.

    Returns:
        Dict with results, total, page, page_size, total_pages.
    """
    base = select(PatientResult).where(PatientResult.session_id == session_id)

    if label_filter and label_filter != "all":
        base = base.where(PatientResult.finding_label == label_filter)

    if reviewed_filter == "unreviewed":
        base = base.where(PatientResult.review_judgment.is_(None))

    # Order by predicted_score desc, nulls last
    base = base.order_by(PatientResult.predicted_score.desc().nullslast())

    # Count total
    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await db.execute(count_stmt)).scalar() or 0

    # Paginate
    offset = (page - 1) * page_size
    results_stmt = base.offset(offset).limit(page_size)
    result = await db.execute(results_stmt)
    results = list(result.scalars().all())

    total_pages = math.ceil(total / page_size) if page_size > 0 else 0

    return {
        "results": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }


async def submit_judgment(
    db: AsyncSession,
    patient_result_id: int,
    judgment: str,
    user_id: str,
    event_date_override: str | None = None,
) -> PatientResult:
    """Submit clinician judgment on a patient result.

    Args:
        patient_result_id: The PatientResult row ID.
        judgment: e.g. "correct", "wrong", "skipped".
        user_id: The reviewing clinician's user ID.
        event_date_override: Optional corrected event date (ISO string).

    Returns:
        Updated PatientResult.
    """
    pr = (
        await db.execute(
            select(PatientResult).where(PatientResult.id == patient_result_id)
        )
    ).scalar_one()

    pr.review_judgment = judgment
    pr.reviewed_by = user_id
    pr.reviewed_at = datetime.now(UTC)
    if event_date_override is not None:
        pr.reviewer_date_override = event_date_override

    db.add(pr)
    await db.commit()
    await db.refresh(pr)
    return pr


async def get_next_unreviewed_result(
    db: AsyncSession,
    session_id: str,
    after_id: int | None = None,
) -> dict | None:
    """Get the next unreviewed patient result for sequential review."""
    total_stmt = select(func.count()).where(
        PatientResult.session_id == session_id,
        PatientResult.status == PatientResultStatus.COMPLETED,
    )
    total_results = (await db.execute(total_stmt)).scalar() or 0

    unreviewed_stmt = select(func.count()).where(
        PatientResult.session_id == session_id,
        PatientResult.status == PatientResultStatus.COMPLETED,
        PatientResult.review_judgment.is_(None),
    )
    total_unreviewed = (await db.execute(unreviewed_stmt)).scalar() or 0

    if total_unreviewed == 0:
        return None

    next_stmt = (
        select(PatientResult)
        .where(
            PatientResult.session_id == session_id,
            PatientResult.status == PatientResultStatus.COMPLETED,
            PatientResult.review_judgment.is_(None),
        )
        .order_by(PatientResult.predicted_score.desc().nullslast(), PatientResult.id)
    )
    if after_id is not None:
        next_stmt = next_stmt.where(PatientResult.id > after_id)
    next_stmt = next_stmt.limit(1)
    result = (await db.execute(next_stmt)).scalar_one_or_none()

    if result is None and after_id is not None:
        next_stmt = (
            select(PatientResult)
            .where(
                PatientResult.session_id == session_id,
                PatientResult.status == PatientResultStatus.COMPLETED,
                PatientResult.review_judgment.is_(None),
            )
            .order_by(PatientResult.predicted_score.desc().nullslast(), PatientResult.id)
            .limit(1)
        )
        result = (await db.execute(next_stmt)).scalar_one_or_none()

    if result is None:
        return None

    position = total_results - total_unreviewed + 1

    return {
        "id": result.id,
        "patient_id": result.patient_id,
        "status": result.status.value if hasattr(result.status, "value") else result.status,
        "finding_label": result.finding_label,
        "finding_reasoning": result.finding_reasoning,
        "finding_evidence": result.finding_evidence,
        "event_date": result.event_date,
        "predicted_score": result.predicted_score,
        "review_judgment": result.review_judgment,
        "reviewer_date_override": result.reviewer_date_override,
        "notes_searched": result.notes_searched,
        "notes_matched": result.notes_matched,
        "position": position,
        "total_unreviewed": total_unreviewed,
        "total_results": total_results,
    }


# ── Metrics ──────────────────────────────────────────────────────


async def compute_metrics(
    db: AsyncSession,
    session_id: str,
) -> dict:
    """Compute live accuracy metrics from reviewed patient results.

    Only considers sample results (pipeline_run_id IS NULL) that are
    COMPLETED (excludes NO_MATCH). Skipped judgments are excluded from
    the confusion matrix.

    Returns:
        Dict with tp, fp, tn, fn, accuracy, precision, recall, f1, total_reviewed.
    """
    stmt = select(PatientResult).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.is_(None),
        PatientResult.status == PatientResultStatus.COMPLETED,
    )
    result = await db.execute(stmt)
    all_results = result.scalars().all()

    tp = fp = tn = fn = 0
    for pr in all_results:
        if not pr.review_judgment or pr.review_judgment == "skipped":
            continue
        is_positive = pr.finding_label == "positive"
        is_correct = pr.review_judgment == "correct"

        if is_positive and is_correct:
            tp += 1
        elif is_positive and not is_correct:
            fp += 1
        elif not is_positive and is_correct:
            tn += 1
        else:  # negative and wrong
            fn += 1

    total_reviewed = tp + fp + tn + fn
    accuracy = (tp + tn) / total_reviewed if total_reviewed > 0 else 0.0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0.0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0.0
    f1 = (2 * precision * recall) / (precision + recall) if (precision + recall) > 0 else 0.0

    metrics = {
        "tp": tp,
        "fp": fp,
        "tn": tn,
        "fn": fn,
        "accuracy": round(accuracy, 4),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "f1": round(f1, 4),
        "total_reviewed": total_reviewed,
    }

    # Persist metrics on session
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()
    session.metrics = metrics
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    return metrics


# ── Commit ───────────────────────────────────────────────────────


async def commit_session(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    confidence_threshold: float | None = None,
) -> EvaluationSession:
    """Lock the session configuration and mark as COMMITTED.

    Only REVIEWING sessions can be committed. Snapshots all config into
    committed_config JSON for reproducibility.

    Args:
        session_id: The evaluation session to commit.
        user_id: The user performing the commit.
        confidence_threshold: Optional threshold to include in committed config.

    Returns:
        Updated EvaluationSession with status COMMITTED.
    """
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    if session.status != SessionStatus.REVIEWING:
        raise ValueError(
            f"Cannot commit session in {getattr(session.status, 'value', session.status)} status; "
            "only REVIEWING sessions can be committed"
        )

    # Read LLM config from project
    from app.projects.models import Project
    project = (
        await db.execute(select(Project).where(Project.id == session.project_id))
    ).scalar_one()

    if not project.llm_provider or not project.llm_model:
        raise ValueError(
            "Project LLM configuration is required. Set the LLM provider and model in project settings before committing."
        )

    committed_config = {
        "search_queries": session.search_queries,
        "event_name": session.event_name,
        "event_description": session.event_description,
        "include_criteria": session.include_criteria,
        "exclude_criteria": session.exclude_criteria,
        "llm_provider": project.llm_provider,
        "llm_model": project.llm_model,
        "llm_api_base": project.llm_api_base,
        "sample_size": session.sample_size,
        "metrics": session.metrics,
    }
    if confidence_threshold is not None:
        committed_config["confidence_threshold"] = confidence_threshold

    session.committed_config = committed_config
    session.committed_at = datetime.now(UTC)
    session.committed_by = user_id
    session.status = SessionStatus.COMMITTED
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Pipeline Dispatch ────────────────────────────────────────────


async def _get_or_create_event_config_for_session(
    db: AsyncSession, eval_session: EvaluationSession
) -> EventConfig:
    """Create a synthetic EventConfig from the committed session config.

    This bridges the new evaluation session model with the existing pipeline
    infrastructure which requires an EventConfig.
    """
    # Read LLM config from project
    from app.projects.models import Project
    project = (
        await db.execute(select(Project).where(Project.id == eval_session.project_id))
    ).scalar_one()

    ec = EventConfig(
        project_id=eval_session.project_id,
        name=eval_session.event_name or "Evaluation Session",
        description=eval_session.event_description or "",
        include_criteria=eval_session.include_criteria or "",
        exclude_criteria=eval_session.exclude_criteria or "",
        search_patterns={"queries": eval_session.search_queries or []},
        llm_provider=project.llm_provider or "",
        llm_model=project.llm_model or "",
        llm_api_base=project.llm_api_base,
        is_committed=True,
    )
    db.add(ec)
    await db.flush()
    return ec


async def dispatch_full_pipeline_run(
    db: AsyncSession, eval_session: EvaluationSession
) -> PipelineRun:
    """Create a PipelineRun for the committed session and dispatch to workers."""
    # Create synthetic EventConfig for pipeline compatibility
    ec = await _get_or_create_event_config_for_session(db, eval_session)

    # Count all patients in project
    stmt = select(func.count(Patient.id)).where(
        Patient.project_id == eval_session.project_id,
        Patient.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    total_patients = result.scalar() or 0

    run = PipelineRun(
        project_id=eval_session.project_id,
        event_config_id=ec.id,
        run_type="full",
        status=PipelineRunStatus.QUEUED,
        config_snapshot=eval_session.committed_config or {},
        total_patients=total_patients,
        created_by=eval_session.committed_by or "",
    )
    db.add(run)
    await db.flush()

    # Get ALL patient IDs
    stmt = select(Patient.id).where(
        Patient.project_id == eval_session.project_id,
        Patient.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    all_patient_ids = [row[0] for row in result.all()]

    # Copy completed sample results
    sample_result_map = {}
    stmt = select(PatientResult).where(
        PatientResult.session_id == eval_session.id,
        PatientResult.pipeline_run_id.is_(None),
        PatientResult.status.in_([PatientResultStatus.COMPLETED, PatientResultStatus.NO_MATCH]),
    )
    result = await db.execute(stmt)
    for sr in result.scalars().all():
        sample_result_map[sr.patient_id] = sr

    for pid in all_patient_ids:
        if pid in sample_result_map:
            sr = sample_result_map[pid]
            pr = PatientResult(
                session_id=eval_session.id,
                pipeline_run_id=run.id,
                patient_id=pid,
                status=sr.status,
                notes_searched=sr.notes_searched,
                notes_matched=sr.notes_matched,
                finding_label=sr.finding_label,
                finding_reasoning=sr.finding_reasoning,
                finding_evidence=sr.finding_evidence,
                event_date=sr.event_date,
                predicted_score=sr.predicted_score,
                token_usage=sr.token_usage,
                completed_at=sr.completed_at,
            )
        else:
            pr = PatientResult(
                session_id=eval_session.id,
                pipeline_run_id=run.id,
                patient_id=pid,
                status=PatientResultStatus.QUEUED,
            )
        db.add(pr)

    await db.commit()
    await db.refresh(run)
    await _enqueue_eval_pipeline_run(run.id)
    return run


async def get_pipeline_stats(db: AsyncSession, session_id: str) -> dict:
    """Get pipeline run stats for a committed session."""
    session = await db.get(EvaluationSession, session_id)
    if not session or session.status not in (SessionStatus.COMMITTED, SessionStatus.COMPLETED):
        raise ValueError("No committed pipeline for this session")

    # Find the pipeline run via PatientResult linkage
    stmt = select(PatientResult.pipeline_run_id).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.isnot(None),
    ).distinct().limit(1)
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise ValueError("Pipeline run not found for this session")

    run_id = row[0]
    run = await db.get(PipelineRun, run_id)
    if not run:
        raise ValueError("Pipeline run not found")

    # Aggregate PatientResult statuses for the pipeline run
    stmt = (
        select(PatientResult.status, func.count())
        .where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id == run_id,
        )
        .group_by(PatientResult.status)
    )
    result = await db.execute(stmt)
    counts = {(s.value if hasattr(s, "value") else s): c for s, c in result.all()}

    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0),
        "processing": counts.get("processing", 0),
        "completed": counts.get("completed", 0),
        "failed": counts.get("failed", 0),
        "no_match": counts.get("no_match", 0),
        "is_cancelled": run.is_cancelled,
    }


async def cancel_pipeline_run(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Cancel the pipeline run for a committed session."""
    from app.pipeline.orchestrator import cancel_run

    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")

    # Find associated pipeline run
    stmt = select(PatientResult.pipeline_run_id).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.isnot(None),
    ).distinct().limit(1)
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise ValueError("No pipeline run found for this session")

    run = await cancel_run(db, project_id, row[0])
    if not run:
        raise ValueError("Pipeline run not found")

    # Move session to discarded so new sessions can be created
    session.status = SessionStatus.DISCARDED
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    return {"status": "cancelled", "run_id": run.id}


async def retry_failed_pipeline(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Retry failed patients in the full pipeline run."""
    stmt = select(PatientResult.pipeline_run_id).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.isnot(None),
    ).distinct().limit(1)
    result = await db.execute(stmt)
    row = result.first()
    if not row:
        raise ValueError("No pipeline run found for this session")

    run_id = row[0]

    # Reset failed PatientResults to queued
    stmt = select(PatientResult).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id == run_id,
        PatientResult.status == PatientResultStatus.FAILED,
    )
    result = await db.execute(stmt)
    failed = list(result.scalars().all())

    if not failed:
        raise ValueError("No failed patients to retry")

    for pr in failed:
        pr.status = PatientResultStatus.QUEUED
        pr.error_message = None
        pr.started_at = None
        pr.completed_at = None
        db.add(pr)

    await db.commit()
    await _enqueue_eval_pipeline_run(run_id)
    return {"requeued": len(failed), "run_id": run_id}


async def rerun_pipeline(
    db: AsyncSession, session_id: str, project_id: str, user_id: str
) -> dict:
    """Re-run the pipeline for a committed session after cancel or completion.

    Creates a fresh PipelineRun. Copies already-completed PatientResults,
    re-queues the rest.
    """
    session = await db.get(EvaluationSession, session_id)
    if not session or session.project_id != project_id:
        raise ValueError("Session not found")
    if session.status not in (SessionStatus.COMMITTED, SessionStatus.COMPLETED):
        raise ValueError("Session must be in committed or completed state to re-run")

    # Reset session to COMMITTED if it was COMPLETED
    if session.status == SessionStatus.COMPLETED:
        session.status = SessionStatus.COMMITTED
        db.add(session)

    run = await dispatch_full_pipeline_run(db, session)
    return {"run_id": run.id, "total_patients": run.total_patients}
