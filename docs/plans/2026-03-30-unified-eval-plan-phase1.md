# Unified Evaluation Session — Phase 1: Backend Models & Migration

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace EventConfig + old EvaluationSession models with a unified EvaluationSession model, plus new SearchMatch and PatientResult tables.

**Architecture:** New models in `backend/app/evaluation/models.py`. Alembic migration to create new tables. Old pipeline models (EventConfig, PatientTask, Evidence) are kept but no longer used by new code. Old evaluation models (EvaluationJudgment, ValidatedPredictor) are replaced.

**Tech Stack:** SQLAlchemy 2.0, SQLModel, Alembic, pytest-asyncio, aiosqlite

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Rewrite | `backend/app/evaluation/models.py` | New EvaluationSession, SearchMatch, PatientResult models |
| Create | `backend/tests/test_eval_models.py` | Unit tests for new models |
| Create | `backend/migrations/versions/xxxx_unified_eval_session.py` | Alembic migration |
| Modify | `backend/app/worker.py:69-73` | Register new worker function |

---

### Task 1: New EvaluationSession Model

**Files:**
- Rewrite: `backend/app/evaluation/models.py`
- Test: `backend/tests/test_eval_models.py`

- [ ] **Step 1: Write failing test for EvaluationSession model**

```python
# backend/tests/test_eval_models.py
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.evaluation.models import (
    EvaluationSession,
    SessionStatus,
)


@pytest.fixture
async def session():
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


class TestEvaluationSession:
    async def test_create_draft_session(self, session):
        es = EvaluationSession(
            project_id="proj-1",
            created_by="user-1",
            status=SessionStatus.DRAFT,
            search_queries=[{"query": "troponin OR MI", "type": "include"}],
            sample_size=100,
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)

        assert es.id is not None
        assert es.status == SessionStatus.DRAFT
        assert es.search_queries[0]["query"] == "troponin OR MI"
        assert es.sample_size == 100
        assert es.event_name is None
        assert es.committed_config is None

    async def test_default_status_is_draft(self, session):
        es = EvaluationSession(
            project_id="proj-1",
            created_by="user-1",
            sample_size=100,
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)
        assert es.status == SessionStatus.DRAFT

    async def test_session_with_llm_config(self, session):
        es = EvaluationSession(
            project_id="proj-1",
            created_by="user-1",
            sample_size=100,
            event_name="Myocardial Infarction",
            event_description="Confirmed MI",
            include_criteria="Troponin elevation",
            exclude_criteria="Rule-out",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)
        assert es.event_name == "Myocardial Infarction"
        assert es.llm_provider == "openai"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_eval_models.py -v -x`
Expected: FAIL (old model doesn't have new fields)

- [ ] **Step 3: Write the new EvaluationSession model**

Replace `backend/app/evaluation/models.py` entirely:

```python
"""Unified evaluation session models.

Replaces: EventConfig, old EvaluationSession, EvaluationJudgment, ValidatedPredictor.
"""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, Index, JSON, Text
from sqlmodel import Field, SQLModel


class SessionStatus(str, enum.Enum):
    DRAFT = "draft"
    REVIEWING = "reviewing"
    COMMITTED = "committed"
    COMPLETED = "completed"
    DISCARDED = "discarded"


class PatientResultStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    NO_MATCH = "no_match"


PATIENT_RESULT_TRANSITIONS = {
    PatientResultStatus.QUEUED: {PatientResultStatus.PROCESSING},
    PatientResultStatus.PROCESSING: {
        PatientResultStatus.COMPLETED,
        PatientResultStatus.FAILED,
        PatientResultStatus.NO_MATCH,
        PatientResultStatus.QUEUED,
    },
    PatientResultStatus.FAILED: {PatientResultStatus.QUEUED},
    PatientResultStatus.COMPLETED: set(),
    PatientResultStatus.NO_MATCH: set(),
}


class EvaluationSession(SQLModel, table=True):
    __tablename__ = "evaluation_sessions_v2"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)

    # Status
    status: SessionStatus = Field(default=SessionStatus.DRAFT)

    # Search queries
    search_queries: list = Field(default=[], sa_column=Column(JSON, default=[]))

    # LLM configuration
    event_name: str | None = Field(default=None, max_length=200)
    event_description: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    include_criteria: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    exclude_criteria: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    llm_provider: str | None = Field(default=None, max_length=50)
    llm_model: str | None = Field(default=None, max_length=200)
    llm_api_base: str | None = Field(default=None, max_length=500)

    # Sample
    sample_patient_ids: list = Field(default=[], sa_column=Column(JSON, default=[]))
    sample_size: int = Field(default=100)

    # Metrics
    metrics: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Commit
    committed_config: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    committed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    committed_by: str | None = Field(default=None, foreign_key="users.id")

    # Clone
    cloned_from_id: str | None = Field(default=None, foreign_key="evaluation_sessions_v2.id")

    # Audit
    created_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )
    updated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


class SearchMatch(SQLModel, table=True):
    __tablename__ = "search_matches"
    __table_args__ = (
        Index("ix_search_matches_session_query", "session_id", "query_index"),
        Index("ix_search_matches_session_patient", "session_id", "patient_id"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="evaluation_sessions_v2.id", index=True)
    query_index: int = Field(default=0)
    patient_id: str = Field(index=True)
    note_id: str = Field(foreign_key="notes.id", index=True)
    matched_tokens: list = Field(default=[], sa_column=Column(JSON, default=[]))
    match_positions: list = Field(default=[], sa_column=Column(JSON, default=[]))
    is_negated: bool = Field(default=False)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )


class PatientResult(SQLModel, table=True):
    __tablename__ = "patient_results"
    __table_args__ = (
        Index("ix_patient_results_session_status", "session_id", "status"),
        Index("ix_patient_results_run_status", "pipeline_run_id", "status"),
    )

    id: int | None = Field(default=None, primary_key=True)
    session_id: str = Field(foreign_key="evaluation_sessions_v2.id", index=True)
    pipeline_run_id: str | None = Field(default=None, foreign_key="pipeline_runs.id", index=True)
    patient_id: str = Field(index=True)

    # Search results
    notes_searched: int = Field(default=0)
    notes_matched: int = Field(default=0)

    # LLM classification
    finding_label: str | None = Field(default=None, max_length=20)
    finding_reasoning: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    finding_evidence: list | None = Field(default=None, sa_column=Column(JSON, nullable=True))
    event_date: str | None = Field(default=None, max_length=10)  # ISO date string
    predicted_score: float | None = Field(default=None)
    token_usage: dict | None = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Clinician review
    review_judgment: str | None = Field(default=None, max_length=20)
    reviewer_date_override: str | None = Field(default=None, max_length=10)
    reviewed_by: str | None = Field(default=None, foreign_key="users.id")
    reviewed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )

    # Execution
    status: PatientResultStatus = Field(default=PatientResultStatus.QUEUED)
    error_message: str | None = Field(default=None, sa_column=Column(Text, nullable=True))
    started_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    completed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), default=lambda: datetime.now(UTC)),
    )

    def transition_status(self, new_status: PatientResultStatus) -> None:
        allowed = PATIENT_RESULT_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise ValueError(
                f"Cannot transition PatientResult from {self.status} to {new_status}"
            )
        self.status = new_status
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && uv run pytest tests/test_eval_models.py -v -x`
Expected: PASS

- [ ] **Step 5: Write tests for SearchMatch and PatientResult**

Add to `backend/tests/test_eval_models.py`:

```python
from app.evaluation.models import (
    PatientResult,
    PatientResultStatus,
    SearchMatch,
)


class TestSearchMatch:
    async def test_create_search_match(self, session):
        # Need an EvaluationSession first
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)

        sm = SearchMatch(
            session_id=es.id,
            query_index=0,
            patient_id="pat-1",
            note_id="note-1",
            matched_tokens=["troponin", "MI"],
            match_positions=[{"start": 10, "end": 18, "token": "troponin"}],
            is_negated=False,
        )
        session.add(sm)
        await session.commit()
        await session.refresh(sm)

        assert sm.id is not None
        assert sm.matched_tokens == ["troponin", "MI"]
        assert sm.is_negated is False


class TestPatientResult:
    async def test_create_patient_result(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)

        pr = PatientResult(
            session_id=es.id,
            patient_id="pat-1",
            status=PatientResultStatus.QUEUED,
        )
        session.add(pr)
        await session.commit()
        await session.refresh(pr)

        assert pr.id is not None
        assert pr.status == PatientResultStatus.QUEUED
        assert pr.finding_label is None

    async def test_transition_queued_to_processing(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()

        pr = PatientResult(session_id=es.id, patient_id="pat-1")
        pr.transition_status(PatientResultStatus.PROCESSING)
        assert pr.status == PatientResultStatus.PROCESSING

    async def test_invalid_transition_raises(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()

        pr = PatientResult(session_id=es.id, patient_id="pat-1")
        pr.transition_status(PatientResultStatus.PROCESSING)
        pr.transition_status(PatientResultStatus.COMPLETED)

        with pytest.raises(ValueError, match="Cannot transition"):
            pr.transition_status(PatientResultStatus.QUEUED)

    async def test_patient_result_with_llm_results(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()

        pr = PatientResult(
            session_id=es.id,
            patient_id="pat-1",
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Troponin elevated",
            finding_evidence=[{"note_id": "n1", "text": "troponin 2.4", "note_date": "2024-01-15"}],
            event_date="2024-01-15",
            predicted_score=0.94,
            token_usage={"prompt_tokens": 500, "completion_tokens": 50},
        )
        session.add(pr)
        await session.commit()
        await session.refresh(pr)

        assert pr.finding_label == "positive"
        assert pr.event_date == "2024-01-15"
        assert pr.predicted_score == 0.94
```

- [ ] **Step 6: Run all model tests**

Run: `cd backend && uv run pytest tests/test_eval_models.py -v`
Expected: All PASS

- [ ] **Step 7: Register models in worker.py for FK resolution**

Add import to `backend/app/worker.py` after line 20:

```python
from app.evaluation import models as _eval_models_v2  # noqa: F401  # FK resolution
```

- [ ] **Step 8: Commit**

```bash
cd backend
git add app/evaluation/models.py tests/test_eval_models.py app/worker.py
git commit -m "feat: add unified EvaluationSession, SearchMatch, PatientResult models

Replaces separate EventConfig + old EvaluationSession with a single
unified model. SearchMatch stores per-query match results for note
preview. PatientResult handles both sample and full pipeline runs.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 2: Alembic Migration

**Files:**
- Create: `backend/migrations/versions/xxxx_unified_eval_session.py`

- [ ] **Step 1: Generate the migration**

Run: `cd backend && uv run alembic revision -m "add unified evaluation session tables"`

- [ ] **Step 2: Edit the generated migration**

Replace the upgrade/downgrade with:

```python
"""add unified evaluation session tables

Revision ID: (auto-generated)
"""

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.create_table(
        "evaluation_sessions_v2",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String(), sa.ForeignKey("projects.id"), nullable=False, index=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("search_queries", sa.JSON(), server_default="[]"),
        sa.Column("event_name", sa.String(200), nullable=True),
        sa.Column("event_description", sa.Text(), nullable=True),
        sa.Column("include_criteria", sa.Text(), nullable=True),
        sa.Column("exclude_criteria", sa.Text(), nullable=True),
        sa.Column("llm_provider", sa.String(50), nullable=True),
        sa.Column("llm_model", sa.String(200), nullable=True),
        sa.Column("llm_api_base", sa.String(500), nullable=True),
        sa.Column("sample_patient_ids", sa.JSON(), server_default="[]"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="100"),
        sa.Column("metrics", sa.JSON(), nullable=True),
        sa.Column("committed_config", sa.JSON(), nullable=True),
        sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("committed_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("cloned_from_id", sa.String(), sa.ForeignKey("evaluation_sessions_v2.id"), nullable=True),
        sa.Column("created_by", sa.String(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )

    op.create_table(
        "search_matches",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("evaluation_sessions_v2.id"), nullable=False, index=True),
        sa.Column("query_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("patient_id", sa.String(), nullable=False, index=True),
        sa.Column("note_id", sa.String(), sa.ForeignKey("notes.id"), nullable=False, index=True),
        sa.Column("matched_tokens", sa.JSON(), server_default="[]"),
        sa.Column("match_positions", sa.JSON(), server_default="[]"),
        sa.Column("is_negated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_search_matches_session_query", "search_matches", ["session_id", "query_index"])
    op.create_index("ix_search_matches_session_patient", "search_matches", ["session_id", "patient_id"])

    op.create_table(
        "patient_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("session_id", sa.String(), sa.ForeignKey("evaluation_sessions_v2.id"), nullable=False, index=True),
        sa.Column("pipeline_run_id", sa.String(), sa.ForeignKey("pipeline_runs.id"), nullable=True, index=True),
        sa.Column("patient_id", sa.String(), nullable=False, index=True),
        sa.Column("notes_searched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("notes_matched", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finding_label", sa.String(20), nullable=True),
        sa.Column("finding_reasoning", sa.Text(), nullable=True),
        sa.Column("finding_evidence", sa.JSON(), nullable=True),
        sa.Column("event_date", sa.String(10), nullable=True),
        sa.Column("predicted_score", sa.Float(), nullable=True),
        sa.Column("token_usage", sa.JSON(), nullable=True),
        sa.Column("review_judgment", sa.String(20), nullable=True),
        sa.Column("reviewer_date_override", sa.String(10), nullable=True),
        sa.Column("reviewed_by", sa.String(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_patient_results_session_status", "patient_results", ["session_id", "status"])
    op.create_index("ix_patient_results_run_status", "patient_results", ["pipeline_run_id", "status"])


def downgrade() -> None:
    op.drop_table("patient_results")
    op.drop_table("search_matches")
    op.drop_table("evaluation_sessions_v2")
```

- [ ] **Step 3: Run migration locally**

Run: `cd backend && uv run alembic upgrade head`
Expected: Tables created without errors

- [ ] **Step 4: Commit**

```bash
cd backend
git add migrations/versions/*unified*
git commit -m "chore: add Alembic migration for unified evaluation session tables

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
