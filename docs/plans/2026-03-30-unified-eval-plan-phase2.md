# Unified Evaluation Session — Phase 2: Backend Schemas & Service

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the service layer for session CRUD, search query execution with match stats, and the LLM classification runner.

**Architecture:** New schemas in `backend/app/evaluation/schemas.py`, new service in `backend/app/evaluation/service.py`. Reuses existing `nlp/engine.py` for query parsing + note matching, and `pipeline/classifier.py` for LLM classification (with event_date extension).

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, spaCy Matcher, LiteLLM

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Rewrite | `backend/app/evaluation/schemas.py` | Request/response Pydantic models |
| Rewrite | `backend/app/evaluation/service.py` | Business logic for sessions, search, LLM, review |
| Modify | `backend/app/pipeline/classifier.py` | Add event_date to LLM response |
| Create | `backend/tests/test_eval_service.py` | Service layer tests |

---

### Task 3: New Schemas

**Files:**
- Rewrite: `backend/app/evaluation/schemas.py`

- [ ] **Step 1: Write the new schemas**

```python
# backend/app/evaluation/schemas.py
"""Request/response schemas for unified evaluation sessions."""

from datetime import datetime

from pydantic import BaseModel, Field


# --- Session ---

class SearchQueryItem(BaseModel):
    query: str
    type: str = "include"  # "include" or "exclude"


class CreateSessionRequest(BaseModel):
    search_queries: list[SearchQueryItem] = []
    cloned_from_id: str | None = None


class UpdateQueriesRequest(BaseModel):
    search_queries: list[SearchQueryItem]


class LlmConfigRequest(BaseModel):
    event_name: str = Field(max_length=200)
    event_description: str = Field(max_length=5000)
    include_criteria: str = Field(max_length=2000)
    exclude_criteria: str = Field(default="", max_length=2000)
    llm_provider: str = Field(max_length=50)
    llm_model: str = Field(max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class SessionResponse(BaseModel):
    id: str
    project_id: str
    status: str
    search_queries: list[dict]
    event_name: str | None
    event_description: str | None
    include_criteria: str | None
    exclude_criteria: str | None
    llm_provider: str | None
    llm_model: str | None
    llm_api_base: str | None
    sample_size: int
    metrics: dict | None
    committed_config: dict | None
    committed_at: datetime | None
    cloned_from_id: str | None
    created_by: str
    created_at: datetime
    updated_at: datetime


class SessionListResponse(BaseModel):
    id: str
    project_id: str
    status: str
    search_queries: list[dict]
    event_name: str | None
    sample_size: int
    metrics: dict | None
    committed_at: datetime | None
    created_at: datetime


# --- Funnel ---

class FunnelResponse(BaseModel):
    sample_patients: int
    sample_notes: int
    matched_patients: int
    matched_notes: int
    filter_percent: float
    llm_positive: int | None = None
    llm_negative: int | None = None
    llm_inconclusive: int | None = None
    estimated_cost: float | None = None


# --- Search Matches ---

class MatchPosition(BaseModel):
    start: int
    end: int
    token: str


class SearchMatchResponse(BaseModel):
    id: int
    patient_id: str
    note_id: str
    matched_tokens: list[str]
    match_positions: list[dict]
    is_negated: bool


class NoteWithMatchesResponse(BaseModel):
    note_id: str
    patient_id: str
    note_text: str
    note_date: str | None
    note_type: str | None
    matches: list[SearchMatchResponse]


class QueryMatchesResponse(BaseModel):
    query_index: int
    query: str
    query_type: str
    total_notes: int
    total_patients: int
    notes: list[NoteWithMatchesResponse]
    page: int
    page_size: int
    total_pages: int


# --- Suggest Queries ---

class SuggestQueriesRequest(BaseModel):
    description: str = Field(max_length=5000)
    llm_provider: str = Field(max_length=50)
    llm_model: str = Field(max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)


class SuggestedQuery(BaseModel):
    query: str
    type: str  # "include" or "exclude"


class SuggestQueriesResponse(BaseModel):
    suggestions: list[SuggestedQuery]


# --- Patient Results ---

class PatientResultResponse(BaseModel):
    id: int
    patient_id: str
    status: str
    finding_label: str | None
    finding_reasoning: str | None
    finding_evidence: list[dict] | None
    event_date: str | None
    predicted_score: float | None
    review_judgment: str | None
    reviewer_date_override: str | None
    reviewed_by: str | None
    reviewed_at: datetime | None
    notes_searched: int
    notes_matched: int


class SubmitJudgmentRequest(BaseModel):
    judgment: str  # "correct", "wrong", "skipped"
    event_date_override: str | None = None  # ISO date


# --- Metrics ---

class MetricsResponse(BaseModel):
    accuracy: float
    precision: float
    recall: float
    f1: float
    tp: int
    fp: int
    tn: int
    fn: int
    total_reviewed: int
    total_pending: int


# --- Commit ---

class CommitRequest(BaseModel):
    confidence_threshold: float | None = None


class CommitResponse(BaseModel):
    session: SessionResponse
    pipeline_run_id: str
    total_patients: int
    estimated_cost: float | None = None


# --- Pipeline ---

class PipelineStatsResponse(BaseModel):
    total: int
    queued: int
    processing: int
    completed: int
    failed: int
    no_match: int
    is_cancelled: bool
```

- [ ] **Step 2: Commit schemas**

```bash
cd backend
git add app/evaluation/schemas.py
git commit -m "feat: add Pydantic schemas for unified evaluation session API

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 4: Update Classifier to Return event_date

**Files:**
- Modify: `backend/app/pipeline/classifier.py`
- Test: `backend/tests/test_eval_service.py` (tested via service tests)

- [ ] **Step 1: Update SYSTEM_PROMPT and ClassificationResult**

In `backend/app/pipeline/classifier.py`:

Change `SYSTEM_PROMPT` (line 16) — replace the Response format section:

```python
SYSTEM_PROMPT = """You are a clinical NLP system that classifies whether a patient's clinical notes contain evidence of a specific medical event. You will receive relevant excerpts from the patient's notes sorted chronologically. Respond ONLY with a JSON object.

Classification rules:
- Analyze ALL provided excerpts together for a unified patient-level decision
- Determine if the excerpts collectively contain evidence of the defined event
- Consider inclusion and exclusion criteria carefully
- Negated mentions (e.g., "no evidence of", "ruled out") should NOT be classified as positive
- A single strong positive excerpt is sufficient for a positive classification
- If the event is detected, identify the EARLIEST confirmed occurrence date
- Distinguish between the note date and the actual event date mentioned in the text

Response format (JSON only, no other text):
{
  "event_detected": true or false,
  "confidence": 0.0 to 1.0,
  "event_date": "YYYY-MM-DD or null if not detected or unknown",
  "reasoning": "Brief explanation referencing specific excerpts",
  "evidence": [{"note_id": "...", "text": "relevant excerpt", "note_date": "YYYY-MM-DD"}]
}"""
```

Update `ClassificationResult` dataclass (line 33):

```python
@dataclass
class ClassificationResult:
    label: str  # "positive" or "negative"
    confidence: float
    reasoning: str
    event_date: str | None = None  # ISO date string
    evidence: list[dict] | None = None
    token_usage: dict | None = field(default=None)
```

Update `_build_user_prompt` (line 41) — add note dates to excerpts:

```python
def _build_user_prompt(excerpts: list[dict], event_config) -> str:
    """Build user prompt with all excerpts for a single patient."""
    excerpt_text = "\n\n".join(
        f"--- Excerpt from note {e['note_id']} (date: {e.get('note_date', 'unknown')}) ---\n{e['text']}"
        for e in excerpts
    )
    return f"""Event to detect: {event_config.name}
Description: {event_config.description}
Include criteria: {event_config.include_criteria}
Exclude criteria: {event_config.exclude_criteria}

Patient excerpts ({len(excerpts)} matched notes, chronological order):

{excerpt_text}

Based on ALL excerpts above, classify whether this patient has evidence of the event. Identify the EARLIEST confirmed occurrence date if positive. Respond with JSON only."""
```

Update the return in `classify_patient` (line 144):

```python
    detected = data.get("event_detected", False)
    confidence = float(data.get("confidence", 0.5))
    reasoning = data.get("reasoning", "")
    event_date = data.get("event_date") if detected else None
    evidence = data.get("evidence", [])

    return ClassificationResult(
        label="positive" if detected else "negative",
        confidence=confidence,
        reasoning=reasoning,
        event_date=event_date,
        evidence=evidence,
        token_usage=token_usage,
    )
```

- [ ] **Step 2: Run existing pipeline tests to ensure nothing breaks**

Run: `cd backend && uv run pytest tests/test_pipeline_models.py tests/test_pipeline_api.py -v`
Expected: All PASS (classifier changes are backwards compatible)

- [ ] **Step 3: Commit**

```bash
cd backend
git add app/pipeline/classifier.py
git commit -m "feat: extend classifier to return event_date and evidence excerpts

The LLM now identifies the earliest confirmed event date and returns
structured evidence excerpts. ClassificationResult gains event_date
and evidence fields. Backwards compatible.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 5: Service Layer — Session CRUD & Search Execution

**Files:**
- Rewrite: `backend/app/evaluation/service.py`
- Test: `backend/tests/test_eval_service.py`

- [ ] **Step 1: Write failing test for session creation**

```python
# backend/tests/test_eval_service.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.auth.models import User
from app.connectors.models import Note, Patient
from app.evaluation.models import EvaluationSession, SearchMatch, SessionStatus
from app.evaluation.service import (
    create_session,
    discard_session,
    execute_search_queries,
    get_funnel_stats,
    get_query_matches,
    list_sessions,
)
from app.projects.models import Project


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


@pytest.fixture
async def seeded_db(db):
    """DB with a user, project, 5 patients with notes."""
    user = User(id="user-1", email="test@test.com", name="Test", password_hash="x")
    project = Project(id="proj-1", name="Test", owner_id="user-1")
    db.add_all([user, project])
    await db.flush()

    for i in range(5):
        p = Patient(id=f"pat-{i}", project_id="proj-1", patient_id_ext=f"EXT-{i}")
        db.add(p)
        await db.flush()
        # 2 notes per patient
        for j in range(2):
            note_text = f"Patient presents with troponin elevation." if j == 0 else "Follow-up visit, no complaints."
            n = Note(
                id=f"note-{i}-{j}",
                project_id="proj-1",
                patient_id=p.id,
                text_id=f"T{i}{j}",
                note_date="2024-01-15",
                text=note_text,
            )
            db.add(n)
    await db.commit()
    return db


class TestSessionCRUD:
    async def test_create_session_samples_patients(self, seeded_db):
        session = await create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        assert session.status == SessionStatus.DRAFT
        assert session.sample_size >= 5  # all patients (< 100)
        assert len(session.sample_patient_ids) == 5

    async def test_create_session_blocks_if_active_exists(self, seeded_db):
        await create_session(
            seeded_db, project_id="proj-1", user_id="user-1", search_queries=[]
        )
        with pytest.raises(ValueError, match="active session"):
            await create_session(
                seeded_db, project_id="proj-1", user_id="user-1", search_queries=[]
            )

    async def test_discard_session(self, seeded_db):
        session = await create_session(
            seeded_db, project_id="proj-1", user_id="user-1", search_queries=[]
        )
        result = await discard_session(seeded_db, session.id)
        assert result.status == SessionStatus.DISCARDED

    async def test_list_sessions(self, seeded_db):
        await create_session(
            seeded_db, project_id="proj-1", user_id="user-1", search_queries=[]
        )
        sessions = await list_sessions(seeded_db, project_id="proj-1")
        assert len(sessions) == 1


class TestSearchExecution:
    async def test_execute_search_creates_matches(self, seeded_db):
        session = await create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        stats = await execute_search_queries(seeded_db, session.id)
        assert stats["matched_patients"] > 0
        assert stats["matched_notes"] > 0

    async def test_funnel_stats(self, seeded_db):
        session = await create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await execute_search_queries(seeded_db, session.id)
        funnel = await get_funnel_stats(seeded_db, session.id)
        assert funnel["sample_patients"] == 5
        assert funnel["matched_patients"] > 0
        assert funnel["filter_percent"] > 0

    async def test_get_query_matches_returns_highlighted_notes(self, seeded_db):
        session = await create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await execute_search_queries(seeded_db, session.id)
        result = await get_query_matches(seeded_db, session.id, query_index=0, page=1, page_size=10)
        assert result["total_notes"] > 0
        assert len(result["notes"]) > 0
        assert len(result["notes"][0]["matches"]) > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_eval_service.py -v -x`
Expected: FAIL (service functions don't exist yet)

- [ ] **Step 3: Write the service layer**

```python
# backend/app/evaluation/service.py
"""Unified evaluation session service layer."""

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


# --- Session CRUD ---


async def create_session(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    search_queries: list[dict],
    cloned_from_id: str | None = None,
) -> EvaluationSession:
    """Create a new evaluation session with patient sampling."""
    # Block if active session exists
    stmt = select(EvaluationSession).where(
        EvaluationSession.project_id == project_id,
        EvaluationSession.status.in_([SessionStatus.DRAFT, SessionStatus.REVIEWING]),
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("An active session already exists for this project")

    # Block if committed run is active
    stmt = select(EvaluationSession).where(
        EvaluationSession.project_id == project_id,
        EvaluationSession.status == SessionStatus.COMMITTED,
    )
    result = await db.execute(stmt)
    if result.scalar_one_or_none():
        raise ValueError("A committed pipeline is running. Cancel it before creating a new session.")

    # Sample patients: minimum 100 or full cohort
    stmt = select(Patient.id).where(
        Patient.project_id == project_id,
        Patient.deleted_at.is_(None),
    )
    result = await db.execute(stmt)
    all_patient_ids = [row[0] for row in result.all()]

    sample_size = max(100, len(all_patient_ids))  # 100 or all
    sample_size = min(sample_size, len(all_patient_ids))  # cap at total
    sampled_ids = random.sample(all_patient_ids, sample_size) if all_patient_ids else []

    # Clone config if requested
    event_name = None
    event_description = None
    include_criteria = None
    exclude_criteria = None
    llm_provider = None
    llm_model = None
    llm_api_base = None

    if cloned_from_id:
        source = await db.get(EvaluationSession, cloned_from_id)
        if source and source.project_id == project_id:
            search_queries = search_queries or source.search_queries
            event_name = source.event_name
            event_description = source.event_description
            include_criteria = source.include_criteria
            exclude_criteria = source.exclude_criteria
            llm_provider = source.llm_provider
            llm_model = source.llm_model
            llm_api_base = source.llm_api_base

    session = EvaluationSession(
        project_id=project_id,
        created_by=user_id,
        status=SessionStatus.DRAFT,
        search_queries=search_queries,
        sample_patient_ids=sampled_ids,
        sample_size=sample_size,
        event_name=event_name,
        event_description=event_description,
        include_criteria=include_criteria,
        exclude_criteria=exclude_criteria,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_base=llm_api_base,
        cloned_from_id=cloned_from_id,
    )
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def get_session(db: AsyncSession, session_id: str) -> EvaluationSession | None:
    return await db.get(EvaluationSession, session_id)


async def list_sessions(db: AsyncSession, project_id: str) -> list[EvaluationSession]:
    stmt = (
        select(EvaluationSession)
        .where(EvaluationSession.project_id == project_id)
        .order_by(EvaluationSession.created_at.desc())
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def discard_session(db: AsyncSession, session_id: str) -> EvaluationSession:
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")
    if session.status not in (SessionStatus.DRAFT, SessionStatus.REVIEWING):
        raise ValueError("Only draft or reviewing sessions can be discarded")
    session.status = SessionStatus.DISCARDED
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def update_queries(
    db: AsyncSession, session_id: str, search_queries: list[dict]
) -> EvaluationSession:
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")
    if session.status not in (SessionStatus.DRAFT, SessionStatus.REVIEWING):
        raise ValueError("Cannot update queries on a committed/discarded session")
    session.search_queries = search_queries
    session.updated_at = datetime.now(UTC)
    # Clear old search matches
    await db.execute(delete(SearchMatch).where(SearchMatch.session_id == session_id))
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def update_llm_config(
    db: AsyncSession, session_id: str, **kwargs
) -> EvaluationSession:
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")
    if session.status not in (SessionStatus.DRAFT, SessionStatus.REVIEWING):
        raise ValueError("Cannot update LLM config on a committed/discarded session")
    for key, value in kwargs.items():
        if hasattr(session, key):
            setattr(session, key, value)
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


# --- Search Execution ---


async def execute_search_queries(db: AsyncSession, session_id: str) -> dict:
    """Run search queries against sample patient notes. Stores SearchMatch records."""
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")

    # Clear existing matches
    await db.execute(delete(SearchMatch).where(SearchMatch.session_id == session_id))

    if not session.search_queries or not session.sample_patient_ids:
        await db.commit()
        return {"matched_patients": 0, "matched_notes": 0, "total_notes": 0}

    # Load notes for sampled patients
    stmt = select(Note).where(
        Note.patient_id.in_(session.sample_patient_ids),
        Note.text.isnot(None),
    )
    result = await db.execute(stmt)
    notes = list(result.scalars().all())

    # Parse queries
    include_queries = []
    exclude_queries = []
    for i, q in enumerate(session.search_queries):
        query_str = q.get("query", "")
        query_type = q.get("type", "include")
        if query_type == "include":
            include_queries.append((i, query_str))
        else:
            exclude_queries.append((i, query_str))

    # Run each include query, collect matches
    matched_note_ids = set()
    matched_patient_ids = set()

    for query_index, query_str in include_queries:
        query_groups = parse_query(query_str)
        for note in notes:
            sentences = process_note(note.text, query_groups)
            for sent in sentences:
                if sent["is_target"] or sent.get("matched_tokens"):
                    positions = []
                    # Build match positions from the sentence
                    text_lower = note.text.lower()
                    for token in sent["matched_tokens"]:
                        start = text_lower.find(token.lower(), sent["start_pos"])
                        if start >= 0:
                            positions.append({
                                "start": start,
                                "end": start + len(token),
                                "token": token,
                            })

                    sm = SearchMatch(
                        session_id=session_id,
                        query_index=query_index,
                        patient_id=note.patient_id,
                        note_id=note.id,
                        matched_tokens=sent["matched_tokens"],
                        match_positions=positions,
                        is_negated=sent.get("is_negated", False),
                    )
                    db.add(sm)
                    if not sent.get("is_negated", False):
                        matched_note_ids.add(note.id)
                        matched_patient_ids.add(note.patient_id)

    # Run exclude queries — mark matches as negated
    for query_index, query_str in exclude_queries:
        query_groups = parse_query(query_str)
        for note in notes:
            sentences = process_note(note.text, query_groups)
            for sent in sentences:
                if sent.get("matched_tokens"):
                    sm = SearchMatch(
                        session_id=session_id,
                        query_index=query_index,
                        patient_id=note.patient_id,
                        note_id=note.id,
                        matched_tokens=sent["matched_tokens"],
                        match_positions=[],
                        is_negated=True,
                    )
                    db.add(sm)
                    # Remove from matched sets if excluded
                    matched_note_ids.discard(note.id)

    await db.commit()

    return {
        "matched_patients": len(matched_patient_ids),
        "matched_notes": len(matched_note_ids),
        "total_notes": len(notes),
    }


async def get_funnel_stats(db: AsyncSession, session_id: str) -> dict:
    """Get funnel bar data for a session."""
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")

    sample_patients = len(session.sample_patient_ids)

    # Count total notes in sample
    stmt = select(func.count(Note.id)).where(
        Note.patient_id.in_(session.sample_patient_ids)
    )
    result = await db.execute(stmt)
    sample_notes = result.scalar() or 0

    # Count matched (non-negated) from SearchMatch
    stmt = (
        select(func.count(func.distinct(SearchMatch.note_id)))
        .where(SearchMatch.session_id == session_id, SearchMatch.is_negated == False)  # noqa: E712
    )
    result = await db.execute(stmt)
    matched_notes = result.scalar() or 0

    stmt = (
        select(func.count(func.distinct(SearchMatch.patient_id)))
        .where(SearchMatch.session_id == session_id, SearchMatch.is_negated == False)  # noqa: E712
    )
    result = await db.execute(stmt)
    matched_patients = result.scalar() or 0

    filter_percent = ((sample_notes - matched_notes) / sample_notes * 100) if sample_notes > 0 else 0

    # LLM results from PatientResult
    llm_stats = {"positive": None, "negative": None, "inconclusive": None}
    stmt = (
        select(PatientResult.finding_label, func.count())
        .where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id.is_(None),
            PatientResult.finding_label.isnot(None),
        )
        .group_by(PatientResult.finding_label)
    )
    result = await db.execute(stmt)
    for label, count in result.all():
        if label in llm_stats:
            llm_stats[label] = count

    return {
        "sample_patients": sample_patients,
        "sample_notes": sample_notes,
        "matched_patients": matched_patients,
        "matched_notes": matched_notes,
        "filter_percent": round(filter_percent, 1),
        "llm_positive": llm_stats["positive"],
        "llm_negative": llm_stats["negative"],
        "llm_inconclusive": llm_stats["inconclusive"],
    }


async def get_query_matches(
    db: AsyncSession,
    session_id: str,
    query_index: int,
    page: int = 1,
    page_size: int = 10,
) -> dict:
    """Get matched notes for a specific query with highlights."""
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")

    query_item = session.search_queries[query_index] if query_index < len(session.search_queries) else None
    if not query_item:
        raise ValueError("Query index out of range")

    # Count totals
    stmt = select(func.count(func.distinct(SearchMatch.note_id))).where(
        SearchMatch.session_id == session_id,
        SearchMatch.query_index == query_index,
    )
    result = await db.execute(stmt)
    total_notes = result.scalar() or 0

    stmt = select(func.count(func.distinct(SearchMatch.patient_id))).where(
        SearchMatch.session_id == session_id,
        SearchMatch.query_index == query_index,
    )
    result = await db.execute(stmt)
    total_patients = result.scalar() or 0

    # Get distinct note_ids for this query (paginated)
    offset = (page - 1) * page_size
    stmt = (
        select(SearchMatch.note_id)
        .where(
            SearchMatch.session_id == session_id,
            SearchMatch.query_index == query_index,
        )
        .distinct()
        .offset(offset)
        .limit(page_size)
    )
    result = await db.execute(stmt)
    note_ids = [row[0] for row in result.all()]

    # Load notes
    notes_by_id = {}
    if note_ids:
        stmt = select(Note).where(Note.id.in_(note_ids))
        result = await db.execute(stmt)
        for note in result.scalars().all():
            notes_by_id[note.id] = note

    # Load matches for these notes
    note_matches = {}
    if note_ids:
        stmt = select(SearchMatch).where(
            SearchMatch.session_id == session_id,
            SearchMatch.query_index == query_index,
            SearchMatch.note_id.in_(note_ids),
        )
        result = await db.execute(stmt)
        for match in result.scalars().all():
            note_matches.setdefault(match.note_id, []).append(match)

    # Build response
    notes_response = []
    for note_id in note_ids:
        note = notes_by_id.get(note_id)
        if not note:
            continue
        matches = note_matches.get(note_id, [])
        notes_response.append({
            "note_id": note.id,
            "patient_id": note.patient_id,
            "note_text": note.text,
            "note_date": str(note.note_date) if note.note_date else None,
            "note_type": getattr(note, "note_type", None),
            "matches": [
                {
                    "id": m.id,
                    "patient_id": m.patient_id,
                    "note_id": m.note_id,
                    "matched_tokens": m.matched_tokens,
                    "match_positions": m.match_positions,
                    "is_negated": m.is_negated,
                }
                for m in matches
            ],
        })

    total_pages = (total_notes + page_size - 1) // page_size if total_notes > 0 else 0

    return {
        "query_index": query_index,
        "query": query_item.get("query", ""),
        "query_type": query_item.get("type", "include"),
        "total_notes": total_notes,
        "total_patients": total_patients,
        "notes": notes_response,
        "page": page,
        "page_size": page_size,
        "total_pages": total_pages,
    }
```

- [ ] **Step 4: Run tests**

Run: `cd backend && uv run pytest tests/test_eval_service.py -v -x`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/evaluation/service.py tests/test_eval_service.py
git commit -m "feat: add evaluation session service - CRUD and search execution

Session creation with patient sampling, discard, list, update queries,
execute search queries using spaCy Matcher, funnel stats, and query
match preview with highlighted tokens.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 6: Service Layer — LLM Run, Review, Metrics, Commit

**Files:**
- Modify: `backend/app/evaluation/service.py` (append)
- Test: `backend/tests/test_eval_service.py` (append)

- [ ] **Step 1: Write failing test for LLM run**

Add to `backend/tests/test_eval_service.py`:

```python
from unittest.mock import AsyncMock, patch

from app.evaluation.models import PatientResult, PatientResultStatus
from app.evaluation.service import (
    commit_session,
    compute_metrics,
    run_llm_on_sample,
    submit_judgment,
)
from app.pipeline.classifier import ClassificationResult


class TestLlmRun:
    async def test_run_llm_creates_patient_results(self, seeded_db):
        session = await create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await execute_search_queries(seeded_db, session.id)

        # Update LLM config
        from app.evaluation.service import update_llm_config
        await update_llm_config(
            seeded_db, session.id,
            event_name="MI",
            event_description="Confirmed MI",
            include_criteria="Troponin elevation",
            exclude_criteria="Rule-out",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
        )

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Troponin elevated",
            event_date="2024-01-15", evidence=[],
            token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )
        with patch("app.evaluation.service.classify_patient", new_callable=AsyncMock, return_value=mock_result):
            stats = await run_llm_on_sample(seeded_db, session.id)

        assert stats["patients_classified"] > 0
        # Session should now be REVIEWING
        await seeded_db.refresh(session)
        assert session.status == SessionStatus.REVIEWING


class TestReview:
    async def _setup_reviewed_session(self, seeded_db):
        """Helper: create session, run search, run LLM, return session."""
        session = await create_session(
            seeded_db, project_id="proj-1", user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await execute_search_queries(seeded_db, session.id)
        from app.evaluation.service import update_llm_config
        await update_llm_config(
            seeded_db, session.id,
            event_name="MI", event_description="Confirmed MI",
            include_criteria="Troponin elevation", exclude_criteria="Rule-out",
            llm_provider="openai", llm_model="gpt-4o-mini",
        )
        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Troponin elevated",
            event_date="2024-01-15", evidence=[],
            token_usage={"prompt_tokens": 100, "completion_tokens": 20, "total_tokens": 120},
        )
        with patch("app.evaluation.service.classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await run_llm_on_sample(seeded_db, session.id)
        return session

    async def test_submit_judgment(self, seeded_db):
        session = await self._setup_reviewed_session(seeded_db)
        # Get a patient result
        stmt = select(PatientResult).where(
            PatientResult.session_id == session.id,
            PatientResult.finding_label.isnot(None),
        )
        result = await seeded_db.execute(stmt)
        pr = result.scalars().first()
        assert pr is not None

        updated = await submit_judgment(
            seeded_db, pr.id, "correct", "user-1", event_date_override=None
        )
        assert updated.review_judgment == "correct"

    async def test_compute_metrics(self, seeded_db):
        session = await self._setup_reviewed_session(seeded_db)
        # Judge all results
        stmt = select(PatientResult).where(
            PatientResult.session_id == session.id,
            PatientResult.finding_label.isnot(None),
        )
        result = await seeded_db.execute(stmt)
        for pr in result.scalars().all():
            await submit_judgment(seeded_db, pr.id, "correct", "user-1")

        metrics = await compute_metrics(seeded_db, session.id)
        assert metrics["total_reviewed"] > 0
        assert metrics["accuracy"] > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_eval_service.py::TestLlmRun -v -x`
Expected: FAIL (functions not implemented)

- [ ] **Step 3: Add LLM run, review, metrics, and commit to service**

Append to `backend/app/evaluation/service.py`:

```python
from app.pipeline.classifier import classify_patient


# --- LLM Classification ---


async def run_llm_on_sample(db: AsyncSession, session_id: str) -> dict:
    """Run LLM classification on all matched patients in the sample."""
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")
    if not session.event_name or not session.llm_provider:
        raise ValueError("LLM config not set. Configure event name, provider, and model first.")

    # Clear previous patient results (sample only, not full run)
    await db.execute(
        delete(PatientResult).where(
            PatientResult.session_id == session_id,
            PatientResult.pipeline_run_id.is_(None),
        )
    )

    # Find matched patient IDs (non-negated matches)
    stmt = (
        select(SearchMatch.patient_id)
        .where(
            SearchMatch.session_id == session_id,
            SearchMatch.is_negated == False,  # noqa: E712
        )
        .distinct()
    )
    result = await db.execute(stmt)
    matched_patient_ids = [row[0] for row in result.all()]

    if not matched_patient_ids:
        session.status = SessionStatus.REVIEWING
        session.updated_at = datetime.now(UTC)
        db.add(session)
        await db.commit()
        return {"patients_classified": 0, "patients_no_match": 0}

    # Build a config-like object for the classifier
    class _Config:
        pass

    config = _Config()
    config.name = session.event_name
    config.description = session.event_description or ""
    config.include_criteria = session.include_criteria or ""
    config.exclude_criteria = session.exclude_criteria or ""
    config.llm_provider = session.llm_provider
    config.llm_model = session.llm_model
    config.llm_api_base = session.llm_api_base

    patients_classified = 0
    patients_failed = 0
    total_tokens = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    for patient_id in matched_patient_ids:
        # Get matched notes for this patient (sorted by date)
        stmt = (
            select(SearchMatch.note_id)
            .where(
                SearchMatch.session_id == session_id,
                SearchMatch.patient_id == patient_id,
                SearchMatch.is_negated == False,  # noqa: E712
            )
            .distinct()
        )
        result = await db.execute(stmt)
        note_ids = [row[0] for row in result.all()]

        if not note_ids:
            continue

        stmt = select(Note).where(Note.id.in_(note_ids)).order_by(Note.note_date)
        result = await db.execute(stmt)
        notes = list(result.scalars().all())

        excerpts = [
            {"note_id": n.id, "text": n.text, "note_date": str(n.note_date) if n.note_date else "unknown"}
            for n in notes
        ]

        pr = PatientResult(
            session_id=session_id,
            patient_id=patient_id,
            notes_searched=len(notes),
            notes_matched=len(notes),
            status=PatientResultStatus.PROCESSING,
            started_at=datetime.now(UTC),
        )

        try:
            classification = await classify_patient(excerpts, config)
            pr.finding_label = classification.label
            pr.finding_reasoning = classification.reasoning
            pr.finding_evidence = classification.evidence or []
            pr.event_date = classification.event_date
            pr.predicted_score = classification.confidence
            pr.token_usage = classification.token_usage
            pr.status = PatientResultStatus.COMPLETED
            pr.completed_at = datetime.now(UTC)
            patients_classified += 1

            if classification.token_usage:
                for key in total_tokens:
                    total_tokens[key] += classification.token_usage.get(key, 0)
        except Exception as e:
            pr.status = PatientResultStatus.FAILED
            pr.error_message = str(e)
            pr.completed_at = datetime.now(UTC)
            patients_failed += 1
            logger.warning("LLM classification failed for patient %s: %s", patient_id, e)

        db.add(pr)

    # Also create NO_MATCH results for unmatched sample patients
    unmatched_ids = set(session.sample_patient_ids) - set(matched_patient_ids)
    for patient_id in unmatched_ids:
        pr = PatientResult(
            session_id=session_id,
            patient_id=patient_id,
            status=PatientResultStatus.NO_MATCH,
            finding_label="no_match",
            completed_at=datetime.now(UTC),
        )
        db.add(pr)

    session.status = SessionStatus.REVIEWING
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()

    return {
        "patients_classified": patients_classified,
        "patients_no_match": len(unmatched_ids),
        "patients_failed": patients_failed,
        "token_usage": total_tokens,
    }


# --- Review ---


async def list_patient_results(
    db: AsyncSession,
    session_id: str,
    label_filter: str | None = None,
    reviewed_filter: str | None = None,
    page: int = 1,
    page_size: int = 20,
) -> dict:
    """List patient results with filtering and pagination."""
    stmt = select(PatientResult).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.is_(None),  # sample results only
    )
    count_stmt = select(func.count(PatientResult.id)).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.is_(None),
    )

    if label_filter and label_filter != "all":
        stmt = stmt.where(PatientResult.finding_label == label_filter)
        count_stmt = count_stmt.where(PatientResult.finding_label == label_filter)

    if reviewed_filter == "unreviewed":
        stmt = stmt.where(PatientResult.review_judgment.is_(None))
        count_stmt = count_stmt.where(PatientResult.review_judgment.is_(None))

    result = await db.execute(count_stmt)
    total = result.scalar() or 0

    offset = (page - 1) * page_size
    stmt = stmt.order_by(PatientResult.predicted_score.desc().nullslast()).offset(offset).limit(page_size)
    result = await db.execute(stmt)
    results = list(result.scalars().all())

    return {
        "results": results,
        "total": total,
        "page": page,
        "page_size": page_size,
        "total_pages": (total + page_size - 1) // page_size if total > 0 else 0,
    }


async def submit_judgment(
    db: AsyncSession,
    patient_result_id: int,
    judgment: str,
    user_id: str,
    event_date_override: str | None = None,
) -> PatientResult:
    """Submit a clinician judgment on a patient result."""
    pr = await db.get(PatientResult, patient_result_id)
    if not pr:
        raise ValueError("PatientResult not found")
    pr.review_judgment = judgment
    pr.reviewed_by = user_id
    pr.reviewed_at = datetime.now(UTC)
    if event_date_override:
        pr.reviewer_date_override = event_date_override
    db.add(pr)
    await db.commit()
    await db.refresh(pr)
    return pr


# --- Metrics ---


async def compute_metrics(db: AsyncSession, session_id: str) -> dict:
    """Compute live metrics from reviewed patient results."""
    stmt = select(PatientResult).where(
        PatientResult.session_id == session_id,
        PatientResult.pipeline_run_id.is_(None),
        PatientResult.finding_label.isnot(None),
        PatientResult.finding_label != "no_match",
    )
    result = await db.execute(stmt)
    results = list(result.scalars().all())

    reviewed = [r for r in results if r.review_judgment and r.review_judgment != "skipped"]
    pending = [r for r in results if not r.review_judgment]

    tp = fp = tn = fn = 0
    for r in reviewed:
        is_positive_prediction = r.finding_label == "positive"
        is_correct = r.review_judgment == "correct"

        if is_positive_prediction and is_correct:
            tp += 1
        elif is_positive_prediction and not is_correct:
            fp += 1
        elif not is_positive_prediction and is_correct:
            tn += 1
        elif not is_positive_prediction and not is_correct:
            fn += 1

    total = tp + fp + tn + fn
    accuracy = (tp + tn) / total if total > 0 else 0
    precision = tp / (tp + fp) if (tp + fp) > 0 else 0
    recall = tp / (tp + fn) if (tp + fn) > 0 else 0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0

    metrics = {
        "accuracy": round(accuracy, 3),
        "precision": round(precision, 3),
        "recall": round(recall, 3),
        "f1": round(f1, 3),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
        "total_reviewed": len(reviewed),
        "total_pending": len(pending),
    }

    # Update session metrics
    session = await db.get(EvaluationSession, session_id)
    if session:
        session.metrics = metrics
        db.add(session)
        await db.commit()

    return metrics


# --- Commit ---


async def commit_session(db: AsyncSession, session_id: str, user_id: str, confidence_threshold: float | None = None) -> EvaluationSession:
    """Commit a session: lock config and prepare for full pipeline run."""
    session = await db.get(EvaluationSession, session_id)
    if not session:
        raise ValueError("Session not found")
    if session.status != SessionStatus.REVIEWING:
        raise ValueError("Only reviewing sessions can be committed")

    session.committed_config = {
        "search_queries": session.search_queries,
        "event_name": session.event_name,
        "event_description": session.event_description,
        "include_criteria": session.include_criteria,
        "exclude_criteria": session.exclude_criteria,
        "llm_provider": session.llm_provider,
        "llm_model": session.llm_model,
        "llm_api_base": session.llm_api_base,
        "confidence_threshold": confidence_threshold,
        "metrics": session.metrics,
    }
    session.committed_at = datetime.now(UTC)
    session.committed_by = user_id
    session.status = SessionStatus.COMMITTED
    session.updated_at = datetime.now(UTC)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session
```

- [ ] **Step 4: Run all service tests**

Run: `cd backend && uv run pytest tests/test_eval_service.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
cd backend
git add app/evaluation/service.py tests/test_eval_service.py
git commit -m "feat: add LLM classification, review, metrics, and commit to eval service

Run LLM on matched sample patients, submit clinician judgments,
compute live metrics (accuracy/precision/recall/F1), and commit
session to lock config for full pipeline run.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
