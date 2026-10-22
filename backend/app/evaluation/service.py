"""Evaluation service: session CRUD, search query execution,
funnel stats, LLM run, review, metrics, commit."""

import logging
import math
import random
from datetime import UTC, timedelta
from types import SimpleNamespace

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils import now_utc
from app.config import settings
from app.connectors.models import Note, Patient
from app.evaluation.models import (
    EvaluationSession,
    EvaluationSessionQuerySection,
    PatientResult,
    PatientResultStatus,
    SearchMatch,
    SessionStatus,
)
from app.evaluation.query_expression import normalize_queries
from app.llm.pricing import estimate_cost
from app.llm.usage import LlmUsage, add_usage
from app.nlp.engine import parse_query, process_note
from app.nlp.schemas import ReprocessRequest
from app.pipeline.classifier import SYSTEM_PROMPT, classify_patient

# True when running against PostgreSQL (supports SELECT FOR UPDATE).
# SQLite (used in tests) does not support FOR UPDATE.
_USE_DB_LOCKING = "sqlite" not in settings.database_url

# How many patients to fetch matched notes for per query in the sample LLM run.
# Bounds both DB round-trips (avoids an N+1 over patients) and peak memory
# (avoids loading every matched note — potentially millions — at once).
_LLM_PATIENT_BATCH_SIZE = 100

# A sample LLM run writes progress to session.metrics after every patient. If a
# run has been "running" for longer than this without a write, the worker that
# owned it is gone and the user may start a new run — otherwise a killed worker
# would lock the session out of classification permanently.
_STALLED_LLM_RUN = timedelta(minutes=15)


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
    # Check for blocking sessions, locking the rows to prevent concurrent creation
    blocking_stmt = select(EvaluationSession).where(
        EvaluationSession.project_id == project_id,
        EvaluationSession.status.in_([
            SessionStatus.DRAFT,
            SessionStatus.REVIEWING,
            SessionStatus.COMMITTED,
        ]),
    )
    if _USE_DB_LOCKING:
        blocking_stmt = blocking_stmt.with_for_update()
    result = await db.execute(blocking_stmt)
    blocking = result.scalars().first()
    if blocking:
        raise ValueError(
            f"Cannot create session: project already has a {getattr(blocking.status,
                                                                    'value',
                                                                    blocking.status)} session"
        )

    # Handle cloning
    queries = search_queries or []
    query_sections = list(queries)
    raw_input = True
    event_name = None
    event_description = None
    include_criteria = None
    exclude_criteria = None
    exclude_negated = True

    if cloned_from_id:
        clone_source = (
            await db.execute(
                select(EvaluationSession).where(EvaluationSession.id == cloned_from_id)
            )
        ).scalar_one_or_none()
        if clone_source:
            stored_sections = (
                await db.execute(
                    select(EvaluationSessionQuerySection)
                    .where(EvaluationSessionQuerySection.session_id == cloned_from_id)
                    .order_by(EvaluationSessionQuerySection.position)
                )
            ).scalars().all()
            if not search_queries:
                query_sections = [
                    {"query": section.query, "type": section.type}
                    for section in stored_sections
                ] or list(clone_source.search_queries or [])
                queries = query_sections
                raw_input = bool(stored_sections)
            event_name = clone_source.event_name
            event_description = clone_source.event_description
            include_criteria = clone_source.include_criteria
            exclude_criteria = clone_source.exclude_criteria
            exclude_negated = clone_source.exclude_negated

    queries = normalize_queries(queries, allow_empty=True, raw_input=raw_input)

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
        exclude_negated=exclude_negated,
        event_name=event_name,
        event_description=event_description,
        include_criteria=include_criteria,
        exclude_criteria=exclude_criteria,
    )
    db.add(session)
    await db.flush()
    for position, section in enumerate(_clean_query_sections(query_sections)):
        db.add(
            EvaluationSessionQuerySection(
                session_id=session.id,
                position=position,
                query=section["query"],
                type=section["type"],
            )
        )
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


async def get_query_sections(
    db: AsyncSession,
    session_id: str,
) -> list[dict[str, str]]:
    result = await db.execute(
        select(EvaluationSessionQuerySection)
        .where(EvaluationSessionQuerySection.session_id == session_id)
        .order_by(EvaluationSessionQuerySection.position)
    )
    sections = result.scalars().all()
    if sections:
        return [{"query": section.query, "type": section.type} for section in sections]

    session = await get_session(db, session_id)
    return _clean_query_sections(session.search_queries or []) if session else []


def _clean_query_sections(search_queries: list[dict]) -> list[dict[str, str]]:
    return [
        {"query": query["query"].strip(), "type": query.get("type", "include")}
        for query in search_queries
        if query.get("query", "").strip()
    ]


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
    session.updated_at = now_utc()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def update_queries(
    db: AsyncSession,
    session_id: str,
    search_queries: list[dict],
    exclude_negated: bool = True,
) -> EvaluationSession:
    """Update the query list and negation option, and clear old SearchMatch records."""
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()

    ensure_editable_session(session)
    canonical_echo = search_queries == session.search_queries
    normalized_queries = normalize_queries(search_queries, raw_input=not canonical_echo)
    if canonical_echo:
        stored_sections = (
            await db.execute(
                select(EvaluationSessionQuerySection)
                .where(EvaluationSessionQuerySection.session_id == session_id)
                .order_by(EvaluationSessionQuerySection.position)
            )
        ).scalars().all()
        search_queries = [
            {"query": section.query, "type": section.type} for section in stored_sections
        ] or search_queries
    query_sections = _clean_query_sections(search_queries)
    session.search_queries = normalized_queries
    session.exclude_negated = exclude_negated
    session.updated_at = now_utc()
    db.add(session)

    await db.execute(
        delete(EvaluationSessionQuerySection).where(
            EvaluationSessionQuerySection.session_id == session_id
        )
    )
    for position, section in enumerate(query_sections):
        db.add(
            EvaluationSessionQuerySection(
                session_id=session_id,
                position=position,
                query=section["query"],
                type=section["type"],
            )
        )

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

    ensure_editable_session(session)
    allowed_fields = {
        "event_name", "event_description", "include_criteria", "exclude_criteria",
    }
    for key, value in kwargs.items():
        if key in allowed_fields:
            setattr(session, key, value)

    session.updated_at = now_utc()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Search execution ─────────────────────────────────────────────


class SessionLockedError(ValueError):
    pass


def ensure_editable_session(session: EvaluationSession) -> None:
    if session.status not in (SessionStatus.DRAFT, SessionStatus.REVIEWING):
        raise SessionLockedError("Only draft or reviewing sessions can be edited or searched")
    if (session.metrics or {}).get("llm_status") == "running":
        raise SessionLockedError("Wait for sample classification to finish before editing or searching")


async def _activate_session_query(
    db: AsyncSession,
    session: EvaluationSession,
    user_id: str,
    confirmation: ReprocessRequest | None = None,
):
    """Activate the session query only after validating destructive replacement."""
    from app.nlp import service as nlp_service

    ensure_editable_session(session)
    queries = normalize_queries(session.search_queries or [])
    project_id = session.project_id
    if await nlp_service.reprocess_is_busy(db, project_id):
        raise SessionLockedError(
            "Finish active processing and wait for open patient reviews "
            "(locked in the last hour) before reprocessing."
        )
    impact = await nlp_service.get_reprocess_impact(db, project_id)
    requires_deletion = any(impact.values())
    if requires_deletion or confirmation is not None:
        if confirmation is None or not confirmation.confirmed:
            raise ValueError("Confirm deletion before reprocessing.")
        expected = {
            "annotations": confirmation.expected_annotations,
            "predictions": confirmation.expected_predictions,
            "sentences": confirmation.expected_sentences,
        }
        if impact != expected:
            raise SessionLockedError(
                "Deletion counts changed. Review the updated counts and confirm again."
            )

    session.search_queries = queries
    db.add(session)
    await nlp_service.create_search_query(
        db, project_id, queries[0]["query"], created_by=user_id, nlp_apply=False,
        exclude_negated=session.exclude_negated,
        commit=False,
    )
    if requires_deletion:
        await nlp_service.clear_sentences(db, project_id, commit=False)
    return requires_deletion


async def run_session_queries(
    db: AsyncSession,
    session: EvaluationSession,
    user_id: str,
    confirmation: ReprocessRequest | None = None,
):
    """Activate and run a keyword query while keeping the session editable."""
    from app.nlp import service as nlp_service

    await _activate_session_query(db, session, user_id, confirmation)
    project_id = session.project_id
    return await nlp_service.dispatch_nlp_job(
        db,
        project_id,
        user_id,
        confirmed=bool(confirmation and confirmation.confirmed),
    )


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

    ensure_editable_session(session)
    queries = normalize_queries(session.search_queries or [])
    session.search_queries = queries

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

    # query_index must be the position in the full query list: the UI asks for
    # matches by the index it displays (queries/{index}/matches). Numbering only
    # the include queries mis-attributed previews whenever an exclude query came
    # earlier in the list.
    for query_index, query_def in enumerate(queries):
        if query_def.get("type") != "include":
            continue
        query_str = query_def.get("query", "")
        if not query_str:
            continue

        query_groups = parse_query(query_str)
        if not query_groups:
            continue

        for note in notes:
            sentences = process_note(note.text, query_groups)
            for sent in sentences:
                # Negated matches are dropped unless the session asks to keep
                # them; kept ones are stored with is_negated=True so previews
                # can strike them through and downstream counts stay honest.
                if sent.get("is_target") and (
                    not sent.get("is_negated") or not session.exclude_negated
                ):
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

    session.updated_at = now_utc()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Stats & queries ──────────────────────────────────────────────

# Ballpark sizes for the pre-run cost estimate. Excerpts aren't stored until the
# model runs, so assume an average excerpt and a short JSON verdict.
_EST_EXCERPT_TOKENS = 400
_EST_COMPLETION_TOKENS = 150
_EST_PROMPT_OVERHEAD_TOKENS = len(SYSTEM_PROMPT) // 4 + 150  # ~4 chars/token


async def get_cost_summary(db: AsyncSession, session_id: str) -> dict:
    """Actual spend to date plus a full-dataset projection, for one session.

    Spend is summed from ``PatientResult.token_usage`` (written by both the
    sample run and the full run), so it survives reloads and needs no extra
    column. The projection scales the sample's measured tokens per classified
    patient by the sample's match rate times the project's patient count.
    """
    from app.projects.models import Project

    session = (
        await db.execute(select(EvaluationSession).where(EvaluationSession.id == session_id))
    ).scalar_one()
    project = (
        await db.execute(select(Project).where(Project.id == session.project_id))
    ).scalar_one()
    provider, model = project.llm_provider, project.llm_model

    # Spend comes from the ledger. PatientResult.token_usage is copied into the
    # full run when a session is committed, so summing it would count the sample twice.
    run_ids = [
        r[0]
        for r in (
            await db.execute(
                select(PatientResult.pipeline_run_id)
                .where(
                    PatientResult.session_id == session_id,
                    PatientResult.pipeline_run_id.is_not(None),
                )
                .distinct()
            )
        ).all()
    ]
    from app.production.models import ProductionRun

    production_runs = (
        await db.scalars(
            select(ProductionRun).where(ProductionRun.project_id == session.project_id)
        )
    ).all()
    run_ids.extend(
        run.id for run in production_runs
        if (run.config_snapshot or {}).get("evaluation_session_id") == session_id
    )
    spent_prompt, spent_completion = (
        await db.execute(
            select(
                func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
                func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
            ).where(
                LlmUsage.project_id == session.project_id,
                LlmUsage.ref_id.in_([session_id, *run_ids]),
                LlmUsage.source.in_(["evaluation_sample", "pipeline_run", "production_run"]),
            )
        )
    ).one()

    # The sample's measured tokens per classified patient drive the projection.
    # Only original sample rows (no pipeline_run_id) count; a failed patient stores
    # token_usage=None as JSON null, which IS NOT NULL lets through, so skip it.
    sample_rows = (
        await db.execute(
            select(PatientResult.token_usage).where(
                PatientResult.session_id == session_id,
                PatientResult.pipeline_run_id.is_(None),
                PatientResult.token_usage.is_not(None),
            )
        )
    ).all()
    sample_prompt = sample_completion = sample_n = 0
    for (usage,) in sample_rows:
        if not usage:
            continue
        sample_prompt += usage.get("prompt_tokens", 0) or 0
        sample_completion += usage.get("completion_tokens", 0) or 0
        sample_n += 1

    funnel = await get_funnel_stats(db, session_id)
    projection = None
    if funnel["sample_patients"] > 0 and funnel["matched_patients"] > 0:
        total_patients = (
            await db.execute(
                select(func.count(Patient.id)).where(
                    Patient.project_id == session.project_id,
                    Patient.deleted_at.is_(None),
                )
            )
        ).scalar() or 0
        projected = round(total_patients * funnel["matched_patients"] / funnel["sample_patients"])
        if sample_n:
            basis = "sample"
            per_prompt = sample_prompt / sample_n
            per_completion = sample_completion / sample_n
        else:
            basis = "heuristic"
            notes_per_patient = funnel["matched_notes"] / funnel["matched_patients"]
            per_prompt = _EST_PROMPT_OVERHEAD_TOKENS + notes_per_patient * _EST_EXCERPT_TOKENS
            per_completion = _EST_COMPLETION_TOKENS
        # Committing reuses the sample's classifications, so only the rest cost money.
        to_classify = max(0, projected - sample_n)
        prompt_tokens = round(per_prompt * to_classify)
        completion_tokens = round(per_completion * to_classify)
        projection = {
            "basis": basis,
            "sample_patients_classified": sample_n,
            "total_patients": total_patients,
            "projected_matched_patients": projected,
            "patients_to_classify": to_classify,
            "tokens_per_patient": round(per_prompt + per_completion),
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "estimated_cost": estimate_cost(provider, model, prompt_tokens, completion_tokens),
        }

    return {
        "provider": provider,
        "model": model,
        "spent_prompt_tokens": int(spent_prompt),
        "spent_completion_tokens": int(spent_completion),
        "spent_cost": estimate_cost(provider, model, int(spent_prompt), int(spent_completion)),
        "projection": projection,
    }


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

    from app.projects.models import Project

    project = (
        await db.execute(select(Project).where(Project.id == session.project_id))
    ).scalar_one()
    estimated_cost = estimate_cost(
        project.llm_provider,
        project.llm_model,
        prompt_tokens=matched_patients * _EST_PROMPT_OVERHEAD_TOKENS
        + matched_notes * _EST_EXCERPT_TOKENS,
        completion_tokens=matched_patients * _EST_COMPLETION_TOKENS,
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
        "estimated_cost": estimated_cost,
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

    # Check if already running — unless the run has stalled (see _STALLED_LLM_RUN)
    metrics = session.metrics or {}
    if metrics.get("llm_status") == "running":
        last_progress = session.updated_at
        if last_progress is not None and last_progress.tzinfo is None:
            last_progress = last_progress.replace(tzinfo=UTC)
        if last_progress is not None and now_utc() - last_progress < _STALLED_LLM_RUN:
            raise ValueError("LLM classification is already running for this session.")
        logger.warning(
            "Restarting stalled sample LLM run for session %s (no progress since %s)",
            session_id,
            last_progress,
        )

    # Validate LLM config
    from app.projects.models import Project
    project = (await db.execute(select(Project).where(Project.id == project_id))).scalar_one()

    if not project.llm_provider or not project.llm_model:
        raise ValueError(
            """Project LLM configuration is required.
            \nSet the LLM provider and model in project settings."""
        )

    # Clear previous sample results (pipeline_run_id IS NULL)
    await db.execute(
        delete(PatientResult).where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id.is_(None),
        )
    )

    # Count matched patients for progress tracking. Sessions that keep negated
    # matches classify them too, so the is_negated filter only applies when
    # the session excludes them.
    matched_stmt = select(func.count(func.distinct(SearchMatch.patient_id))).where(
        SearchMatch.session_id == session_id,
        *(
            []
            if not session.exclude_negated
            else [SearchMatch.is_negated.is_(False)]
        ),
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
    session.updated_at = now_utc()
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

    # Find matched patient IDs from SearchMatch records. Sessions that keep
    # negated matches classify them too, so the is_negated filter only applies
    # when the session excludes them.
    matched_stmt = select(func.distinct(SearchMatch.patient_id)).where(
        SearchMatch.session_id == session_id,
        *(
            []
            if not session.exclude_negated
            else [SearchMatch.is_negated.is_(False)]
        ),
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
        llm_api_key=project.llm_api_key,
    )

    patients_classified = 0
    patients_failed = 0
    total_token_usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    # Fetch matched notes in batches of patients rather than one query per
    # patient (avoids an N+1: 1 query per patient) or one giant query for all
    # (unbounded memory — a session may match millions of notes). Each batch is
    # a single query grouped in Python, bounding both round-trips and memory.
    matched_ids_list = list(matched_patient_ids)
    for batch_start in range(0, len(matched_ids_list), _LLM_PATIENT_BATCH_SIZE):
        batch_ids = matched_ids_list[batch_start : batch_start + _LLM_PATIENT_BATCH_SIZE]

        batch_notes_stmt = (
            select(Note)
            .where(
                Note.patient_id.in_(batch_ids),
                Note.id.in_(
                    select(SearchMatch.note_id).where(
                        SearchMatch.session_id == session_id,
                        SearchMatch.patient_id.in_(batch_ids),
                        *(
                            []
                            if not session.exclude_negated
                            else [SearchMatch.is_negated.is_(False)]
                        ),
                    )
                ),
            )
            .order_by(Note.patient_id, Note.note_date)
        )
        batch_result = await db.execute(batch_notes_stmt)
        notes_by_patient: dict[str, list[Note]] = {}
        for note in batch_result.scalars().all():
            notes_by_patient.setdefault(note.patient_id, []).append(note)

        # How many notes the search looked at per patient. Without this,
        # notes_searched was set to the matched count too, so the review panel
        # always read "N notes searched · N matched" — hiding the one number
        # that shows what the queries actually skipped.
        totals_stmt = (
            select(Note.patient_id, func.count())
            .where(Note.patient_id.in_(batch_ids))
            .group_by(Note.patient_id)
        )
        notes_total = dict((await db.execute(totals_stmt)).all())

        for patient_id in batch_ids:
            # Already ordered by (patient_id, note_date) in the query above.
            notes = notes_by_patient.get(patient_id, [])

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
                    notes_searched=notes_total.get(patient_id, len(notes)),
                    notes_matched=len(notes),
                    finding_label=classification.label,
                    finding_reasoning=classification.reasoning,
                    finding_evidence=classification.evidence,
                    event_date=classification.event_date,
                    predicted_score=classification.score,
                    token_usage=classification.token_usage,
                    status=PatientResultStatus.COMPLETED,
                    completed_at=now_utc(),
                )
                db.add(pr)
                add_usage(
                    db,
                    project_id=project_id,
                    source="evaluation_sample",
                    provider=project.llm_provider,
                    model=project.llm_model,
                    usage=classification.token_usage,
                    ref_id=session_id,
                )
                patients_classified += 1

                if classification.token_usage:
                    for key in total_token_usage:
                        total_token_usage[key] += classification.token_usage.get(key, 0)

            except Exception as exc:
                logger.warning("LLM classification failed for patient %s: %s", patient_id, exc)
                pr = PatientResult(
                    session_id=session_id,
                    patient_id=patient_id,
                    notes_searched=notes_total.get(patient_id, len(notes)),
                    notes_matched=len(notes),
                    status=PatientResultStatus.FAILED,
                    error_message=str(exc),
                    completed_at=now_utc(),
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
            completed_at=now_utc(),
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
    session.updated_at = now_utc()
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
        label_filter: Filter by finding_label (e.g. "positive", "negative").
                                                Note: "all" or None = no filter.
        reviewed_filter: "unreviewed" to show only unreviewed results.
        page: 1-based page number.
        page_size: Results per page.

    Returns:
        Dict with results, total, page, page_size, total_pages.
    """
    base = select(PatientResult).where(PatientResult.session_id == session_id)

    # If a full pipeline run created copies of the sample results, only show those
    # (pipeline copies have pipeline_run_id set; originals have NULL).
    # This avoids duplicate rows for patients that were in the sample.
    has_pipeline = (
        await db.execute(
            select(func.count()).where(
                PatientResult.session_id == session_id,
                PatientResult.pipeline_run_id.isnot(None),
            )
        )
    ).scalar()
    if has_pipeline:
        base = base.where(PatientResult.pipeline_run_id.isnot(None))

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
    pr.reviewed_at = now_utc()
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
    """Get the next unreviewed patient result for sequential review.

    Sample results only (pipeline_run_id IS NULL), matching compute_metrics. A
    committed session's full-project results are not judged one at a time, and
    counting them here made the queue disagree with the metrics above it.
    """
    total_stmt = select(func.count()).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.is_(None),
        PatientResult.status == PatientResultStatus.COMPLETED,
    )
    total_results = (await db.execute(total_stmt)).scalar() or 0

    unreviewed_stmt = select(func.count()).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.is_(None),
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
            PatientResult.pipeline_run_id.is_(None),
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
                PatientResult.pipeline_run_id.is_(None),
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
    total_pending = sum(1 for pr in all_results if not pr.review_judgment)
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
        "total_pending": total_pending,
    }

    # Persist metrics on session, keeping the classification run's own keys.
    # Replacing the dict wholesale dropped llm_status/llm_total/token_usage, so
    # the UI forgot that the sample run had finished.
    session = (
        await db.execute(
            select(EvaluationSession).where(EvaluationSession.id == session_id)
        )
    ).scalar_one()
    existing = session.metrics or {}
    session.metrics = {
        **{
            key: value
            for key, value in existing.items()
            if key.startswith("llm_") or key == "token_usage"
        },
        **metrics,
    }
    session.updated_at = now_utc()
    db.add(session)
    await db.commit()

    return metrics


# ── Commit ───────────────────────────────────────────────────────


async def commit_session(
    db: AsyncSession,
    session_id: str,
    user_id: str,
    confidence_threshold: float | None = None,
    confirmation: ReprocessRequest | None = None,
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
            """Project LLM configuration is required.
            \nSet the LLM provider and model in project settings before committing."""
        )

    production_confirmation = await _validate_production_reset(
        db, session.project_id, confirmation
    )
    committed_config = {
        "search_queries": session.search_queries,
        "exclude_negated": session.exclude_negated,
        "event_name": session.event_name,
        "event_description": session.event_description,
        "include_criteria": session.include_criteria,
        "exclude_criteria": session.exclude_criteria,
        "llm_provider": project.llm_provider,
        "llm_model": project.llm_model,
        "llm_api_base": project.llm_api_base,
        "llm_api_key": project.llm_api_key,
        "sample_size": session.sample_size,
        "metrics": session.metrics,
        "_production_confirmation": production_confirmation,
    }
    if confidence_threshold is not None:
        committed_config["confidence_threshold"] = confidence_threshold

    session.committed_config = committed_config
    session.committed_at = now_utc()
    session.committed_by = user_id
    session.status = SessionStatus.COMMITTED
    session.updated_at = now_utc()
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# ── Pipeline Dispatch ────────────────────────────────────────────


async def _validate_production_reset(
    db: AsyncSession,
    project_id: str,
    confirmation: ReprocessRequest | dict | None,
) -> dict:
    """Validate the existing deletion-impact confirmation without rebuilding NLP data."""
    from app.nlp import service as nlp_service

    if await nlp_service.reprocess_is_busy(db, project_id):
        raise SessionLockedError(
            "Finish active processing and wait for open patient reviews "
            "(locked in the last hour) before reprocessing."
        )
    impact = await nlp_service.get_reprocess_impact(db, project_id)
    requires_confirmation = any(impact.values())
    if confirmation is None:
        confirmed = False
        expected = None
    elif isinstance(confirmation, dict):
        confirmed = bool(confirmation.get("confirmed"))
        expected = confirmation.get("impact") or {
            "annotations": confirmation.get("annotations"),
            "predictions": confirmation.get("predictions"),
            "sentences": confirmation.get("sentences"),
        }
    else:
        confirmed = confirmation.confirmed
        expected = {
            "annotations": confirmation.expected_annotations,
            "predictions": confirmation.expected_predictions,
            "sentences": confirmation.expected_sentences,
        }

    if requires_confirmation and not confirmed:
        raise ValueError("Confirm deletion before reprocessing.")
    if expected is not None and impact != expected:
        raise SessionLockedError(
            "Deletion counts changed. Review the updated counts and confirm again."
        )
    if confirmation is not None and not isinstance(confirmation, dict) and not confirmed:
        raise ValueError("Confirm deletion before reprocessing.")
    return {"confirmed": confirmed, "impact": impact}


async def dispatch_full_pipeline_run(
    db: AsyncSession,
    eval_session: EvaluationSession,
    cost_estimate: dict | None = None,
) -> SimpleNamespace:
    """Start production note processing for a committed evaluation session."""
    from app.production import service as production_service

    committed_config = eval_session.committed_config or {}
    confirmation = await _validate_production_reset(
        db,
        eval_session.project_id,
        committed_config.get("_production_confirmation"),
    )

    stmt = select(func.count(Patient.id)).where(
        Patient.project_id == eval_session.project_id,
        Patient.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    total_patients = result.scalar() or 0

    queries = committed_config.get("search_queries") or eval_session.search_queries or []
    include_queries = [
        item.get("query", "").strip()
        for item in queries
        if item.get("type", "include") != "exclude" and item.get("query", "").strip()
    ]
    exclude_queries = [
        item.get("query", "").strip()
        for item in queries
        if item.get("type") == "exclude" and item.get("query", "").strip()
    ]
    if not include_queries:
        raise ValueError("At least one include search query is required to start production.")
    query = " OR ".join(f"({item})" for item in include_queries)
    for excluded in exclude_queries:
        query = f"({query}) AND !({excluded})"

    production_config = {
        **committed_config,
        "query": query,
        "exclude_negated": committed_config.get("exclude_negated", True),
        "event_name": committed_config.get("event_name") or "Evaluation Session",
        "evaluation_session_id": eval_session.id,
        "llm_config": {
            "provider": committed_config.get("llm_provider"),
            "model": committed_config.get("llm_model"),
            "api_base": committed_config.get("llm_api_base"),
            "api_key": committed_config.get("llm_api_key"),
        },
        **({"cost_estimate": cost_estimate} if cost_estimate else {}),
    }
    run = await production_service.start_run(
        db=db,
        project_id=eval_session.project_id,
        user_id=eval_session.committed_by or eval_session.created_by,
        config=production_config,
        confirmed=confirmation["confirmed"],
    )
    await _enqueue_eval_pipeline_run(run.id)
    return SimpleNamespace(id=run.id, total_patients=total_patients)


async def _production_run_for_session(db: AsyncSession, session_id: str):
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")
    from app.production.models import ProductionRun

    runs = list(
        await db.scalars(
            select(ProductionRun)
            .where(ProductionRun.project_id == session.project_id)
            .order_by(ProductionRun.created_at.desc())
        )
    )
    run = next(
        (
            item
            for item in runs
            if (item.config_snapshot or {}).get("evaluation_session_id") == session_id
        ),
        None,
    )
    if run is None:
        raise ValueError("Production run not found for this session")
    return session, run


async def get_pipeline_stats(db: AsyncSession, session_id: str) -> dict:
    """Adapt production run state to the existing evaluation stats response."""
    from app.annotations.models import Annotation
    from app.production import service as production_service
    from app.production.models import ProductionResult

    _, run = await _production_run_for_session(db, session_id)
    production_stats = await production_service.get_stats(db, run.id)
    rows = list(
        await db.execute(
            select(ProductionResult.processing_status, func.count())
            .where(ProductionResult.project_id == run.project_id)
            .group_by(ProductionResult.processing_status)
        )
    )
    counts = dict(rows)
    completed = counts.get("completed", 0)
    matched_patients = await db.scalar(
        select(func.count(func.distinct(Annotation.patient_id))).where(
            Annotation.production_run_id == run.id
        )
    ) or 0
    no_match = max(0, completed - matched_patients)
    return {
        "total": sum(counts.values()),
        "queued": counts.get("queued", 0),
        "processing": counts.get("running", 0),
        "completed": max(0, completed - no_match),
        "failed": counts.get("failed", 0),
        "no_match": no_match,
        "is_cancelled": production_stats["status"] == "cancelled",
    }


async def cancel_pipeline_run(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Cancel the pipeline run for a committed session."""
    from app.production import service as production_service

    session, run = await _production_run_for_session(db, session_id)
    if session.project_id != project_id:
        raise ValueError("Session not found")
    run = await production_service.cancel_run(db, run.id)

    # Move session to discarded so new sessions can be created
    session.status = SessionStatus.DISCARDED
    session.updated_at = now_utc()
    db.add(session)
    await db.commit()

    return {"status": "cancelled", "run_id": run.id}


async def retry_failed_pipeline(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Retry failed production note predictions for a committed session."""
    from app.production import service as production_service

    session, run = await _production_run_for_session(db, session_id)
    if session.project_id != project_id:
        raise ValueError("Session not found")
    before = await production_service.get_stats(db, run.id)
    if not before["failed_notes"]:
        raise ValueError("No failed patients to retry")
    run = await production_service.retry_run(db, run.id)
    return {"requeued": before["failed_notes"], "run_id": run.id}


async def resume_pipeline(db: AsyncSession, session_id: str, project_id: str) -> dict:
    """Resume a stuck pipeline run.

    Resets any 'processing' PatientResults back to 'queued' and re-enqueues
    the ARQ job so the worker picks up where it left off.
    """
    from app.production import service as production_service

    session, run = await _production_run_for_session(db, session_id)
    if session.project_id != project_id:
        raise ValueError("Session not found")
    before = await production_service.get_stats(db, run.id)
    run = await production_service.resume_run(db, run.id)
    return {
        "resumed": True,
        "reset_stuck": before["processing_notes"],
        "remaining_queued": before["queued_notes"] + before["processing_notes"],
        "run_id": run.id,
    }


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

    from app.production import service as production_service

    config = dict(session.committed_config or {})
    queries = config.get("search_queries") or session.search_queries or []
    include_queries = [
        item.get("query", "").strip()
        for item in queries
        if item.get("type", "include") != "exclude" and item.get("query", "").strip()
    ]
    exclude_queries = [
        item.get("query", "").strip()
        for item in queries
        if item.get("type") == "exclude" and item.get("query", "").strip()
    ]
    if not include_queries:
        raise ValueError("At least one include search query is required to start production.")
    query = " OR ".join(f"({item})" for item in include_queries)
    for excluded in exclude_queries:
        query = f"({query}) AND !({excluded})"
    production_config = {
        **config,
        "query": query,
        "exclude_negated": config.get("exclude_negated", True),
        "event_name": config.get("event_name") or "Evaluation Session",
        "evaluation_session_id": session.id,
        "llm_config": {
            "provider": config.get("llm_provider"),
            "model": config.get("llm_model"),
            "api_base": config.get("llm_api_base"),
            "api_key": config.get("llm_api_key"),
        },
    }
    run = await production_service.start_run(
        db=db,
        project_id=project_id,
        user_id=user_id,
        config=production_config,
        confirmed=True,
    )
    await _enqueue_eval_pipeline_run(run.id)
    total_patients = await db.scalar(
        select(func.count(Patient.id)).where(
            Patient.project_id == project_id,
            Patient.deleted_at.is_(None),
        )
    ) or 0
    return {"run_id": run.id, "total_patients": total_patients}


async def get_result_note_context(
    db: AsyncSession,
    session_id: str,
    result_id: int,
) -> dict | None:
    """Get full note context for a patient result, including search matches."""
    pr = (
        await db.execute(
            select(PatientResult).where(
                PatientResult.id == result_id,
                PatientResult.session_id == session_id,
            )
        )
    ).scalar_one_or_none()
    if not pr:
        return None

    patient = (
        await db.execute(select(Patient).where(Patient.id == pr.patient_id))
    ).scalar_one_or_none()

    eval_session = await db.get(EvaluationSession, session_id)
    search_keywords = []
    if eval_session and eval_session.search_queries:
        for q in eval_session.search_queries:
            if isinstance(q, dict) and q.get("type") != "exclude":
                search_keywords.append(q["query"])

    matches_stmt = (
        select(SearchMatch)
        .where(
            SearchMatch.session_id == session_id,
            SearchMatch.patient_id == pr.patient_id,
        )
    )
    matches_result = await db.execute(matches_stmt)
    search_matches = matches_result.scalars().all()

    matches_by_note: dict[str, list] = {}
    for m in search_matches:
        matches_by_note.setdefault(m.note_id, []).append(m)

    evidence_note_ids = set()
    if pr.finding_evidence:
        for ev in pr.finding_evidence:
            if isinstance(ev, dict) and "note_id" in ev:
                evidence_note_ids.add(ev["note_id"])

    note_ids = list(matches_by_note.keys())
    if not note_ids:
        return {
            "patient_id": pr.patient_id,
            "patient_id_ext": patient.patient_id_ext if patient else None,
            "notes": [],
            "search_keywords": search_keywords,
        }

    notes_stmt = (
        select(Note)
        .where(Note.id.in_(note_ids))
        .order_by(Note.note_date)
    )
    notes_result = await db.execute(notes_stmt)
    notes = notes_result.scalars().all()

    note_contexts = []
    for note in notes:
        note_matches = matches_by_note.get(note.id, [])
        all_tokens = []
        all_positions = []
        for m in note_matches:
            all_tokens.extend(m.matched_tokens or [])
            all_positions.extend(m.match_positions or [])

        note_contexts.append({
            "note_id": note.id,
            "text_id": note.text_id,
            "text": note.text,
            "note_date": note.note_date.isoformat() if note.note_date else None,
            "note_tags": note.metadata_ or {},
            "matched_tokens": list(set(all_tokens)),
            "match_positions": all_positions,
            "is_evidence": note.id in evidence_note_ids,
        })

    return {
        "patient_id": pr.patient_id,
        "patient_id_ext": patient.patient_id_ext if patient else None,
        "notes": note_contexts,
        "search_keywords": search_keywords,
    }
