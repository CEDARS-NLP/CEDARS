# Agentic Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace separate NLP and LLM prediction pipelines with a unified per-patient agentic pipeline that processes patients one at a time using LLM tool-calling.

**Architecture:** New `EventConfig` model unifies search queries + LLM config. `PipelineRun` + `PatientTask` tables enable per-patient tracking at scale. An agent loop per patient uses tools (`search_notes`, `regex_search`, `read_note`, `submit_finding`) to find clinical events. Evidence excerpts with character offsets replace sentence-level annotations.

**Tech Stack:** FastAPI, SQLAlchemy/SQLModel, Alembic, LiteLLM (tool-calling), spaCy (as agent tool), ARQ (worker queue), React + TypeScript + shadcn/ui (frontend)

**Design doc:** `docs/plans/2026-03-05-agentic-pipeline-redesign.md`

---

## Task 1: New Data Models — EventConfig, PipelineRun, PatientTask, Evidence

**Files:**
- Create: `backend/app/pipeline/models.py`
- Create: `backend/app/pipeline/__init__.py`
- Test: `backend/tests/test_pipeline_models.py`

### Step 1: Write the failing test

```python
"""Tests for pipeline data models."""

import pytest
from sqlmodel import select
from sqlalchemy.ext.asyncio import AsyncSession


async def _get_session(app):
    """Get a test DB session from the app fixture."""
    from app.common.database import get_session
    gen = app.dependency_overrides[get_session]()
    session = await gen.__anext__()
    yield session
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass


class TestEventConfigModel:
    async def test_create_event_config(self, app):
        from app.pipeline.models import EventConfig

        async for session in _get_session(app):
            config = EventConfig(
                project_id="proj-1",
                name="Myocardial Infarction",
                description="Confirmed MI event",
                include_criteria="Troponin elevation, ECG changes",
                exclude_criteria="Rule-out, family history only",
                search_queries=[
                    {"query": "troponin OR myocardial", "name": "MI keywords"},
                ],
                llm_provider="ollama",
                llm_model="llama3",
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)

            assert config.id is not None
            assert config.is_committed is False
            assert config.max_agent_rounds == 5
            assert config.confidence_threshold is None

    async def test_event_config_search_queries_json(self, app):
        from app.pipeline.models import EventConfig

        async for session in _get_session(app):
            config = EventConfig(
                project_id="proj-1",
                name="DVT",
                description="Deep vein thrombosis",
                include_criteria="DVT confirmed",
                exclude_criteria="Suspected only",
                search_queries=[
                    {"query": "DVT OR embolism", "name": "DVT terms"},
                    {"query": "clot AND leg", "name": "Clot in leg"},
                ],
                llm_provider="openai",
                llm_model="gpt-4o",
            )
            session.add(config)
            await session.commit()

            result = await session.get(EventConfig, config.id)
            assert len(result.search_queries) == 2
            assert result.search_queries[0]["query"] == "DVT OR embolism"


class TestPipelineRunModel:
    async def test_create_pipeline_run(self, app):
        from app.pipeline.models import EventConfig, PipelineRun, PipelineRunStatus

        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_queries=[], llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1",
                event_config_id=ec.id,
                run_type="sample",
                status=PipelineRunStatus.QUEUED,
                config_snapshot={"name": "MI"},
                sample_size=50,
                total_patients=50,
                created_by="user-1",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            assert run.id is not None
            assert run.is_cancelled is False
            assert run.run_type == "sample"


class TestPatientTaskModel:
    async def test_create_patient_task(self, app):
        from app.pipeline.models import (
            EventConfig, PipelineRun, PipelineRunStatus,
            PatientTask, PatientTaskStatus,
        )

        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_queries=[], llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1", event_config_id=ec.id,
                run_type="full", status=PipelineRunStatus.QUEUED,
                config_snapshot={}, total_patients=1, created_by="user-1",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)

            task = PatientTask(
                pipeline_run_id=run.id,
                patient_id="patient-1",
                status=PatientTaskStatus.QUEUED,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)

            assert task.id is not None
            assert task.notes_searched == 0
            assert task.finding_label is None


class TestEvidenceModel:
    async def test_create_evidence(self, app):
        from app.pipeline.models import Evidence

        evidence = Evidence(
            patient_task_id=1,
            note_id="note-1",
            text="troponin elevated at 2.4 ng/mL",
            start_pos=120,
            end_pos=155,
            match_source="keyword_search",
            match_query="troponin",
            agent_round=1,
        )
        assert evidence.match_source == "keyword_search"
```

### Step 2: Run test to verify it fails

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.pipeline'`

### Step 3: Write the models

```python
"""Data models for the agentic pipeline."""

import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Column, BigInteger, Index, JSON, Text
from sqlmodel import Field, SQLModel


# ── Enums ────────────────────────────────────────────────────────


class PipelineRunStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class PipelineRunType(str, enum.Enum):
    SAMPLE = "sample"
    FULL = "full"


class PatientTaskStatus(str, enum.Enum):
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


# ── EventConfig ──────────────────────────────────────────────────


class EventConfig(SQLModel, table=True):
    __tablename__ = "event_configs"

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex, primary_key=True)
    project_id: str = Field(index=True)
    name: str
    description: str = Field(sa_column=Column(Text))
    include_criteria: str = Field(sa_column=Column(Text))
    exclude_criteria: str = Field(sa_column=Column(Text))
    search_queries: list = Field(default_factory=list, sa_column=Column(JSON, nullable=False))

    # LLM configuration
    llm_provider: str
    llm_model: str
    llm_api_base: Optional[str] = None

    # Agent settings
    max_agent_rounds: int = Field(default=5)

    # Calibration (set after eval)
    confidence_threshold: Optional[float] = None
    is_committed: bool = Field(default=False)

    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)


# ── PipelineRun ──────────────────────────────────────────────────


class PipelineRun(SQLModel, table=True):
    __tablename__ = "pipeline_runs"

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex, primary_key=True)
    project_id: str = Field(index=True)
    event_config_id: str = Field(index=True)
    run_type: str  # "sample" or "full"
    status: PipelineRunStatus = Field(default=PipelineRunStatus.QUEUED)
    config_snapshot: dict = Field(default_factory=dict, sa_column=Column(JSON, nullable=False))
    sample_size: Optional[int] = None
    total_patients: int = Field(default=0)
    is_cancelled: bool = Field(default=False)
    result_summary: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error_message: Optional[str] = None
    created_by: str
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


# ── PatientTask ──────────────────────────────────────────────────


class PatientTask(SQLModel, table=True):
    __tablename__ = "patient_tasks"
    __table_args__ = (
        Index("ix_patient_tasks_run_status", "pipeline_run_id", "status"),
    )

    id: Optional[int] = Field(
        default=None,
        sa_column=Column(BigInteger, primary_key=True, autoincrement=True),
    )
    pipeline_run_id: str = Field(index=True)
    patient_id: str = Field(index=True)
    status: PatientTaskStatus = Field(default=PatientTaskStatus.QUEUED)

    # Agent results
    agent_trace: Optional[list] = Field(default=None, sa_column=Column(JSON))
    notes_searched: int = Field(default=0)
    notes_read: int = Field(default=0)
    tool_calls: int = Field(default=0)
    finding_label: Optional[str] = None
    finding_reasoning: Optional[str] = Field(default=None, sa_column=Column(Text))
    finding_evidence: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    token_usage: Optional[dict] = Field(default=None, sa_column=Column(JSON))
    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))

    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


# ── Evidence ─────────────────────────────────────────────────────


class Evidence(SQLModel, table=True):
    __tablename__ = "evidences"

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex, primary_key=True)
    patient_task_id: int = Field(sa_column=Column(BigInteger, index=True))
    note_id: str = Field(index=True)
    text: str = Field(sa_column=Column(Text))
    start_pos: int
    end_pos: int
    match_source: str  # "keyword_search", "regex_search", "full_note_read"
    match_query: Optional[str] = None
    agent_round: int = Field(default=0)
```

Also create `backend/app/pipeline/__init__.py`:
```python
"""Agentic pipeline module."""
```

### Step 4: Run test to verify it passes

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_models.py -v`
Expected: All 5 tests PASS

### Step 5: Register models in conftest and create Alembic migration

Add to `backend/tests/conftest.py` line 16 (after the BackgroundJob import):
```python
from app.pipeline.models import EventConfig, PipelineRun, PatientTask, Evidence  # noqa: F401
```

Run:
```bash
cd /Users/rsingh/Programming/CEDARS/backend
uv run alembic revision --autogenerate -m "add pipeline models event_config pipeline_run patient_task evidence"
```

Review the generated migration, then:
```bash
uv run pytest tests/test_pipeline_models.py -v
```

### Step 6: Commit

```bash
git add backend/app/pipeline/ backend/tests/test_pipeline_models.py backend/migrations/versions/*pipeline*.py backend/tests/conftest.py
git commit -m "feat: add pipeline data models (EventConfig, PipelineRun, PatientTask, Evidence)"
```

---

## Task 2: Rework Annotation Model to Patient-Level

**Files:**
- Modify: `backend/app/annotations/models.py`
- Test: `backend/tests/test_pipeline_models.py` (extend)

The current `Annotation` model links to individual sentences. The new model links to patient-level findings from the pipeline.

### Step 1: Write the failing test

Add to `backend/tests/test_pipeline_models.py`:

```python
class TestAnnotationV2Model:
    async def test_create_patient_level_annotation(self, app):
        from app.annotations.models import Annotation, ReviewStatus

        async for session in _get_session(app):
            annotation = Annotation(
                project_id="proj-1",
                patient_id="patient-1",
                pipeline_run_id="run-1",
                patient_task_id=1,
                predicted_label="positive",
                predicted_reasoning="Troponin elevated",
                predicted_score=0.87,
                review_status=ReviewStatus.PENDING,
            )
            session.add(annotation)
            await session.commit()
            await session.refresh(annotation)

            assert annotation.id is not None
            assert annotation.predicted_label == "positive"
            assert annotation.reviewer_label is None
```

### Step 2: Run test — expected FAIL

The current model has `sentence_id`, `sentence_text`, `matched_tokens`, `is_negated` fields but no `pipeline_run_id`, `patient_task_id`, `predicted_reasoning`, `predicted_label` (it uses int 0/1), `reviewer_label`, `reviewer_notes`, or `ReviewStatus.PENDING`.

### Step 3: Update the Annotation model

Modify `backend/app/annotations/models.py`:

```python
"""Annotation models — patient-level findings from the agentic pipeline."""

import enum
from datetime import date, datetime
from typing import Optional

from sqlalchemy import Column, BigInteger, Text
from sqlmodel import Field, SQLModel


class ReviewStatus(str, enum.Enum):
    PENDING = "pending"
    CONFIRMED = "confirmed"
    REJECTED = "rejected"
    SKIPPED = "skipped"


class Annotation(SQLModel, table=True):
    __tablename__ = "annotations"

    id: str = Field(default_factory=lambda: __import__("uuid").uuid4().hex, primary_key=True)
    project_id: str = Field(index=True)
    patient_id: str = Field(index=True)

    # Pipeline linkage
    pipeline_run_id: Optional[str] = Field(default=None, index=True)
    patient_task_id: Optional[int] = Field(default=None, sa_column=Column(BigInteger))

    # Legacy sentence linkage (kept for backward compat during migration)
    note_id: Optional[str] = Field(default=None, index=True)
    sentence_id: Optional[str] = None
    sentence_text: Optional[str] = None
    matched_tokens: Optional[str] = None
    is_negated: Optional[bool] = None

    # Agent / predictor determination
    predicted_label: Optional[str] = None  # "positive", "negative", "inconclusive" (or legacy 0/1)
    predicted_score: Optional[float] = None
    predicted_reasoning: Optional[str] = Field(default=None, sa_column=Column(Text))
    predictor_model: Optional[str] = None

    # Human review
    review_status: ReviewStatus = Field(default=ReviewStatus.PENDING)
    reviewer_label: Optional[str] = None
    event_date: Optional[date] = None
    reviewer_notes: Optional[str] = Field(default=None, sa_column=Column(Text))
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[datetime] = None

    created_at: datetime = Field(default_factory=datetime.utcnow)
```

**Key changes:**
- `ReviewStatus` now uses `PENDING/CONFIRMED/REJECTED/SKIPPED` (was `UNREVIEWED/REVIEWED/SKIPPED`)
- Added `pipeline_run_id`, `patient_task_id` for pipeline linkage
- `predicted_label` is now a string (`"positive"/"negative"/"inconclusive"`) instead of int
- Added `predicted_reasoning`, `reviewer_label`, `reviewer_notes`
- Legacy fields (`sentence_id`, `sentence_text`, `matched_tokens`, `is_negated`, `note_id`) kept as Optional for backward compat

### Step 4: Update annotation schemas

Modify `backend/app/annotations/schemas.py` to reflect the new fields. Key changes:
- `AnnotationResponse` adds `pipeline_run_id`, `patient_task_id`, `predicted_reasoning`, `reviewer_label`, `reviewer_notes`
- `ReviewRequest` adds optional `reviewer_label` and `reviewer_notes`
- Add `EvidenceResponse` schema

### Step 5: Create Alembic migration

```bash
cd /Users/rsingh/Programming/CEDARS/backend
uv run alembic revision --autogenerate -m "update annotations model for pipeline linkage"
```

### Step 6: Run tests, fix any breakages in existing annotation tests

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/ -v
```

Existing tests in `test_annotations_api.py` will need updates for the new `ReviewStatus` enum values and field changes.

### Step 7: Commit

```bash
git add backend/app/annotations/models.py backend/app/annotations/schemas.py backend/migrations/versions/ backend/tests/
git commit -m "feat: rework Annotation model to patient-level with pipeline linkage"
```

---

## Task 3: EventConfig CRUD API

**Files:**
- Create: `backend/app/pipeline/schemas.py`
- Create: `backend/app/pipeline/service.py`
- Create: `backend/app/pipeline/router.py`
- Modify: `backend/app/main.py` (register router)
- Test: `backend/tests/test_pipeline_api.py`

### Step 1: Write the failing test

```python
"""API integration tests for the agentic pipeline."""

import pytest
from httpx import AsyncClient


async def register_and_login(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "pipeline@example.com", "name": "Pipeline User", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "pipeline@example.com", "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Pipeline Project", "description": "test"},
    )
    return resp.json()["id"]


class TestEventConfigCRUD:
    async def test_create_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json={
                "name": "Myocardial Infarction",
                "description": "Confirmed MI event",
                "include_criteria": "Troponin elevation, ECG changes",
                "exclude_criteria": "Rule-out, family history",
                "search_queries": [
                    {"query": "troponin OR myocardial", "name": "MI keywords"},
                ],
                "llm_provider": "ollama",
                "llm_model": "llama3",
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Myocardial Infarction"
        assert data["is_committed"] is False
        assert len(data["search_queries"]) == 1

    async def test_list_event_configs(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        for name in ["MI", "DVT"]:
            await client.post(
                f"/api/v1/projects/{pid}/pipeline/events",
                json={
                    "name": name, "description": "test",
                    "include_criteria": "x", "exclude_criteria": "y",
                    "search_queries": [], "llm_provider": "ollama", "llm_model": "m",
                },
            )

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/events")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_update_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json={
                "name": "MI", "description": "test",
                "include_criteria": "x", "exclude_criteria": "y",
                "search_queries": [], "llm_provider": "ollama", "llm_model": "m",
            },
        )
        eid = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}",
            json={"name": "Updated MI", "llm_model": "llama3.1"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated MI"
        assert resp.json()["llm_model"] == "llama3.1"

    async def test_cannot_update_committed_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json={
                "name": "MI", "description": "test",
                "include_criteria": "x", "exclude_criteria": "y",
                "search_queries": [], "llm_provider": "ollama", "llm_model": "m",
            },
        )
        eid = create_resp.json()["id"]

        # Commit it
        await client.post(f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit")

        # Try to update — should fail
        resp = await client.put(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}",
            json={"name": "Changed"},
        )
        assert resp.status_code == 400

    async def test_delete_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json={
                "name": "MI", "description": "test",
                "include_criteria": "x", "exclude_criteria": "y",
                "search_queries": [], "llm_provider": "ollama", "llm_model": "m",
            },
        )
        eid = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/projects/{pid}/pipeline/events/{eid}")
        assert resp.status_code == 204

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/events")
        assert len(resp.json()) == 0
```

### Step 2: Run test — expected FAIL (404, no route)

### Step 3: Implement schemas, service, router

**`backend/app/pipeline/schemas.py`:**
```python
"""Request/response schemas for the pipeline module."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel


class SearchQueryItem(BaseModel):
    query: str
    name: str = ""


class CreateEventConfigRequest(BaseModel):
    name: str
    description: str
    include_criteria: str
    exclude_criteria: str
    search_queries: list[SearchQueryItem]
    llm_provider: str
    llm_model: str
    llm_api_base: Optional[str] = None
    max_agent_rounds: int = 5


class UpdateEventConfigRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    include_criteria: Optional[str] = None
    exclude_criteria: Optional[str] = None
    search_queries: Optional[list[SearchQueryItem]] = None
    llm_provider: Optional[str] = None
    llm_model: Optional[str] = None
    llm_api_base: Optional[str] = None
    max_agent_rounds: Optional[int] = None


class EventConfigResponse(BaseModel):
    id: str
    project_id: str
    name: str
    description: str
    include_criteria: str
    exclude_criteria: str
    search_queries: list
    llm_provider: str
    llm_model: str
    llm_api_base: Optional[str]
    max_agent_rounds: int
    confidence_threshold: Optional[float]
    is_committed: bool
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class PipelineRunResponse(BaseModel):
    id: str
    project_id: str
    event_config_id: str
    run_type: str
    status: str
    sample_size: Optional[int]
    total_patients: int
    is_cancelled: bool
    result_summary: Optional[dict]
    error_message: Optional[str]
    created_by: str
    started_at: Optional[datetime]
    completed_at: Optional[datetime]
    created_at: datetime

    model_config = {"from_attributes": True}


class PatientTaskResponse(BaseModel):
    id: int
    pipeline_run_id: str
    patient_id: str
    status: str
    notes_searched: int
    notes_read: int
    tool_calls: int
    finding_label: Optional[str]
    finding_reasoning: Optional[str]
    token_usage: Optional[dict]
    error_message: Optional[str]
    started_at: Optional[datetime]
    completed_at: Optional[datetime]

    model_config = {"from_attributes": True}


class EvidenceResponse(BaseModel):
    id: str
    patient_task_id: int
    note_id: str
    text: str
    start_pos: int
    end_pos: int
    match_source: str
    match_query: Optional[str]
    agent_round: int

    model_config = {"from_attributes": True}


class RunSampleRequest(BaseModel):
    sample_size: int = 50


class PipelineRunStatsResponse(BaseModel):
    """Aggregate stats for a pipeline run (computed from PatientTask counts)."""
    total: int
    queued: int
    processing: int
    completed: int
    failed: int
    skipped: int
    total_tokens: Optional[dict] = None
```

**`backend/app/pipeline/service.py`:**
Standard CRUD for EventConfig — `create_event_config`, `list_event_configs`, `get_event_config`, `update_event_config`, `delete_event_config`, `commit_event_config`. Follow the exact patterns in `backend/app/predictors/service.py`.

Key business rule: `update_event_config` and `delete_event_config` must reject if `is_committed=True` (return 400).

**`backend/app/pipeline/router.py`:**
```python
router = APIRouter(
    prefix="/api/v1/projects/{project_id}/pipeline",
    tags=["pipeline"],
)
```

Routes:
- `POST /events` → create_event_config (201)
- `GET /events` → list_event_configs
- `GET /events/{event_id}` → get_event_config
- `PUT /events/{event_id}` → update_event_config
- `DELETE /events/{event_id}` → delete (204)
- `POST /events/{event_id}/commit` → commit_event_config

**`backend/app/main.py`:** Add `from app.pipeline.router import router as pipeline_router` and `application.include_router(pipeline_router)`.

### Step 4: Run tests

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_api.py -v
```

### Step 5: Commit

```bash
git add backend/app/pipeline/ backend/app/main.py backend/tests/test_pipeline_api.py
git commit -m "feat: add EventConfig CRUD API for pipeline configuration"
```

---

## Task 4: Agent Engine — Tool Definitions and Execution

This is the core: the per-patient agent loop with tool-calling.

**Files:**
- Create: `backend/app/pipeline/agent.py`
- Create: `backend/app/pipeline/tools.py`
- Test: `backend/tests/test_agent.py`

### Step 1: Write the failing test

```python
"""Tests for the agentic pipeline engine."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.pipeline.tools import search_notes_tool, regex_search_tool, read_note_tool
from app.pipeline.agent import PatientAgent, AgentFinding


class TestSearchNotesTool:
    async def test_search_finds_matching_sentences(self):
        """search_notes should use spaCy matcher to find target sentences."""
        notes = [
            MagicMock(id="n1", text="Patient has troponin elevation and chest pain.", note_date=None),
            MagicMock(id="n2", text="No significant findings today.", note_date=None),
        ]
        result = await search_notes_tool(
            query="troponin",
            notes=notes,
        )
        assert len(result["matches"]) >= 1
        assert any("troponin" in m["text"].lower() for m in result["matches"])
        assert result["matches"][0]["note_id"] == "n1"

    async def test_search_returns_empty_on_no_match(self):
        notes = [MagicMock(id="n1", text="Normal vitals today.", note_date=None)]
        result = await search_notes_tool(query="troponin", notes=notes)
        assert len(result["matches"]) == 0


class TestRegexSearchTool:
    async def test_regex_finds_pattern(self):
        notes = [
            MagicMock(id="n1", text="Troponin I level: 2.4 ng/mL, elevated above normal range."),
        ]
        result = await regex_search_tool(
            pattern=r"troponin.*?(\d+\.?\d*)\s*ng/mL",
            notes=notes,
        )
        assert len(result["matches"]) >= 1
        assert "2.4" in result["matches"][0]["text"]

    async def test_regex_timeout_protection(self):
        """Catastrophic backtracking patterns should be caught."""
        notes = [MagicMock(id="n1", text="a" * 10000)]
        result = await regex_search_tool(
            pattern=r"(a+)+b",  # catastrophic backtracking
            notes=notes,
        )
        # Should return error or empty, not hang
        assert "error" in result or len(result["matches"]) == 0


class TestReadNoteTool:
    async def test_read_returns_full_note(self):
        notes = [
            MagicMock(id="n1", text="Full note content here.", note_date=None),
            MagicMock(id="n2", text="Another note.", note_date=None),
        ]
        result = await read_note_tool(note_id="n1", notes=notes)
        assert result["text"] == "Full note content here."
        assert result["note_id"] == "n1"

    async def test_read_not_found(self):
        notes = [MagicMock(id="n1", text="Some text.")]
        result = await read_note_tool(note_id="n999", notes=notes)
        assert "error" in result


class TestPatientAgent:
    async def test_agent_processes_patient_with_positive_finding(self):
        """Agent should call tools and produce a finding."""
        # Mock LLM responses: first calls search_notes, then submit_finding
        mock_search_response = MagicMock()
        mock_search_response.choices = [MagicMock()]
        mock_search_response.choices[0].message.tool_calls = [MagicMock(
            id="call_1",
            function=MagicMock(
                name="search_notes",
                arguments='{"query": "troponin OR MI"}',
            ),
        )]
        mock_search_response.choices[0].message.content = None
        mock_search_response.usage = MagicMock(prompt_tokens=100, completion_tokens=20)

        mock_finding_response = MagicMock()
        mock_finding_response.choices = [MagicMock()]
        mock_finding_response.choices[0].message.tool_calls = [MagicMock(
            id="call_2",
            function=MagicMock(
                name="submit_finding",
                arguments='{"label": "positive", "evidence_note_ids": ["n1"], "reasoning": "Troponin elevated"}',
            ),
        )]
        mock_finding_response.choices[0].message.content = None
        mock_finding_response.usage = MagicMock(prompt_tokens=200, completion_tokens=50)

        notes = [
            MagicMock(id="n1", text="Patient has troponin elevation.", note_date=None),
        ]

        event_config = MagicMock(
            name="MI", description="Myocardial Infarction",
            include_criteria="Troponin elevation",
            exclude_criteria="Rule-out",
            search_queries=[{"query": "troponin OR MI", "name": "MI terms"}],
            llm_provider="ollama", llm_model="llama3",
            llm_api_base="http://localhost:11434",
            max_agent_rounds=5,
        )

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [mock_search_response, mock_finding_response]

            agent = PatientAgent(event_config=event_config, notes=notes)
            finding = await agent.run()

            assert finding.label == "positive"
            assert "Troponin" in finding.reasoning
            assert len(agent.trace) == 2  # two rounds

    async def test_agent_respects_max_rounds(self):
        """Agent should stop after max_agent_rounds even without submit_finding."""
        # Every response just calls search_notes (never submit_finding)
        def make_search_response():
            resp = MagicMock()
            resp.choices = [MagicMock()]
            resp.choices[0].message.tool_calls = [MagicMock(
                id="call_x",
                function=MagicMock(
                    name="search_notes",
                    arguments='{"query": "troponin"}',
                ),
            )]
            resp.choices[0].message.content = None
            resp.usage = MagicMock(prompt_tokens=50, completion_tokens=10)
            return resp

        notes = [MagicMock(id="n1", text="Some text.", note_date=None)]
        event_config = MagicMock(
            name="MI", description="MI", include_criteria="x", exclude_criteria="y",
            search_queries=[], llm_provider="ollama", llm_model="llama3",
            llm_api_base=None, max_agent_rounds=3,
        )

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.side_effect = [make_search_response() for _ in range(3)]

            agent = PatientAgent(event_config=event_config, notes=notes)
            finding = await agent.run()

            assert finding.label == "inconclusive"
            assert mock_llm.call_count == 3
```

### Step 2: Run test — expected FAIL

### Step 3: Implement tools and agent

**`backend/app/pipeline/tools.py`:**

Implements `search_notes_tool`, `regex_search_tool`, `read_note_tool` as pure async functions. `search_notes_tool` delegates to `app.nlp.engine.parse_query` and `app.nlp.engine.process_note`. `regex_search_tool` uses `re.finditer` with a 2-second timeout (via `signal` or `concurrent.futures.ThreadPoolExecutor`). `read_note_tool` returns full note text.

Each tool returns a dict with a consistent structure:
```python
{"matches": [{"note_id": str, "text": str, "start_pos": int, "end_pos": int}]}
```
or `{"text": str, "note_id": str}` for `read_note_tool`.

**`backend/app/pipeline/agent.py`:**

Core `PatientAgent` class:

```python
@dataclass
class AgentFinding:
    label: str  # "positive", "negative", "inconclusive"
    reasoning: str
    evidence_note_ids: list[str]
    score: float | None = None


class PatientAgent:
    TOOL_DEFINITIONS = [...]  # OpenAI-format tool schemas

    def __init__(self, event_config, notes):
        self.event_config = event_config
        self.notes = notes
        self.trace = []  # audit trail
        self.token_usage = {"prompt_tokens": 0, "completion_tokens": 0}
        self.notes_searched = 0
        self.notes_read = 0

    async def run(self) -> AgentFinding:
        messages = [self._system_message()]

        for round_num in range(self.event_config.max_agent_rounds):
            response = await litellm.acompletion(
                model=self._litellm_model(),
                messages=messages,
                tools=self.TOOL_DEFINITIONS,
                **self._connection_kwargs(),
            )
            # Track tokens
            # Process tool calls or final answer
            # Append to trace
            # If submit_finding called, return AgentFinding

        return AgentFinding(label="inconclusive", reasoning="Max rounds reached", evidence_note_ids=[])
```

The `_litellm_model()` and `_connection_kwargs()` methods reuse the same logic from `backend/app/predictors/llm.py` (extract into shared utility or duplicate — keep it simple).

### Step 4: Run tests

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_agent.py -v
```

### Step 5: Commit

```bash
git add backend/app/pipeline/agent.py backend/app/pipeline/tools.py backend/tests/test_agent.py
git commit -m "feat: implement per-patient agent engine with tool-calling"
```

---

## Task 5: Pipeline Run Orchestration (Sample + Full)

**Files:**
- Create: `backend/app/pipeline/orchestrator.py`
- Create: `backend/app/jobs/pipeline.py`
- Modify: `backend/app/worker.py` (register new task)
- Modify: `backend/app/pipeline/router.py` (add run endpoints)
- Test: `backend/tests/test_pipeline_api.py` (extend)

### Step 1: Write the failing test

Add to `backend/tests/test_pipeline_api.py`:

```python
class TestPipelineRun:
    async def test_run_sample(self, client):
        """Run a sample pipeline on a few patients."""
        await register_and_login(client)
        pid = await create_project(client)
        await _ingest_test_data(client, pid)  # helper to add patients + notes
        eid = await _create_event_config(client, pid)  # helper

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_type"] == "sample"
        assert data["total_patients"] == 2
        assert data["status"] in ("queued", "running", "completed")

    async def test_run_full_requires_committed_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        eid = await _create_event_config(client, pid)

        resp = await client.post(f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-full")
        assert resp.status_code == 400  # not committed yet

    async def test_cancel_pipeline_run(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _ingest_test_data(client, pid)
        eid = await _create_event_config(client, pid)

        run_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        run_id = run_resp.json()["id"]

        cancel_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/cancel",
        )
        assert cancel_resp.status_code == 200
        assert cancel_resp.json()["is_cancelled"] is True
```

### Step 2: Run test — expected FAIL (routes don't exist)

### Step 3: Implement orchestrator

**`backend/app/pipeline/orchestrator.py`:**

```python
async def dispatch_sample_run(session, project_id, event_config_id, user_id, sample_size=50):
    """Create a sample PipelineRun, pick random patients, create PatientTasks."""
    # 1. Get EventConfig
    # 2. Count patients in project
    # 3. Random sample of patient IDs (ORDER BY RANDOM() LIMIT sample_size)
    # 4. Create PipelineRun(run_type="sample", config_snapshot=ec.dict())
    # 5. Create PatientTask rows for each sampled patient
    # 6. Enqueue to ARQ or run sync fallback
    # 7. Return PipelineRun

async def dispatch_full_run(session, project_id, event_config_id, user_id):
    """Create a full PipelineRun for all patients not already processed."""
    # 1. Verify EventConfig.is_committed == True
    # 2. Get all patient IDs in project
    # 3. Exclude patients already in a completed PatientTask for this event_config
    # 4. Create PipelineRun(run_type="full")
    # 5. Bulk insert PatientTask rows
    # 6. Enqueue to ARQ
    # 7. Return PipelineRun

async def cancel_run(session, project_id, run_id):
    """Set is_cancelled flag on a PipelineRun."""

async def retry_failed(session, project_id, run_id):
    """Re-queue all failed PatientTasks in a run."""

async def get_run_stats(session, run_id):
    """Return aggregate counts by PatientTask status."""
```

**`backend/app/jobs/pipeline.py`:**

```python
async def execute_pipeline_run(pipeline_run_id: str):
    """Worker function: process patients for a pipeline run.

    Pulls PatientTasks with status=queued one at a time, runs the agent,
    creates Evidence + Annotation records, updates PatientTask.
    """
    async with async_session() as session:
        run = await session.get(PipelineRun, pipeline_run_id)

        while True:
            # Check cancellation
            await session.refresh(run)
            if run.is_cancelled:
                break

            # Pull next patient task (FOR UPDATE SKIP LOCKED for Postgres,
            # simple SELECT for SQLite in tests)
            task = await _claim_next_task(session, pipeline_run_id)
            if not task:
                break  # all done

            try:
                # Load patient's notes
                notes = await _get_patient_notes(session, run.project_id, task.patient_id)

                # Run agent
                config = run.config_snapshot  # use snapshot, not live config
                agent = PatientAgent(event_config=config, notes=notes)
                finding = await agent.run()

                # Save Evidence records
                for evidence_item in agent.collected_evidence:
                    session.add(Evidence(...))

                # Save Annotation
                session.add(Annotation(
                    project_id=run.project_id,
                    patient_id=task.patient_id,
                    pipeline_run_id=run.id,
                    patient_task_id=task.id,
                    predicted_label=finding.label,
                    predicted_reasoning=finding.reasoning,
                    predicted_score=finding.score,
                ))

                # Update PatientTask
                task.status = PatientTaskStatus.COMPLETED
                task.finding_label = finding.label
                task.finding_reasoning = finding.reasoning
                task.agent_trace = agent.trace
                task.token_usage = agent.token_usage
                task.notes_searched = agent.notes_searched
                task.notes_read = agent.notes_read
                task.tool_calls = len(agent.trace)
                task.completed_at = datetime.utcnow()

            except Exception as e:
                task.status = PatientTaskStatus.FAILED
                task.error_message = str(e)
                task.completed_at = datetime.utcnow()

            await session.commit()

        # Update PipelineRun status
        run.status = _compute_final_status(session, pipeline_run_id)
        run.completed_at = datetime.utcnow()
        run.result_summary = await _compute_summary(session, pipeline_run_id)
        await session.commit()
```

**`backend/app/worker.py`:** Add:
```python
async def run_pipeline_job(ctx: dict, pipeline_run_id: str) -> dict:
    from app.jobs.pipeline import execute_pipeline_run
    return await execute_pipeline_run(pipeline_run_id)
```
Add `run_pipeline_job` to `WorkerSettings.functions`.

**Pipeline router additions:**
- `POST /events/{event_id}/run-sample` → dispatch_sample_run
- `POST /events/{event_id}/run-full` → dispatch_full_run
- `POST /runs/{run_id}/cancel` → cancel_run
- `POST /runs/{run_id}/retry-failed` → retry_failed
- `GET /runs/{run_id}` → get run detail
- `GET /runs/{run_id}/stats` → get_run_stats
- `GET /runs/{run_id}/tasks` → list PatientTasks (paginated)
- `GET /runs` → list PipelineRuns for project

### Step 4: Run tests

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_api.py -v
```

### Step 5: Commit

```bash
git add backend/app/pipeline/orchestrator.py backend/app/jobs/pipeline.py backend/app/worker.py backend/app/pipeline/router.py backend/tests/test_pipeline_api.py
git commit -m "feat: implement pipeline run orchestration (sample, full, cancel, retry)"
```

---

## Task 6: WebSocket for Pipeline Progress

**Files:**
- Modify: `backend/app/jobs/ws.py` or create `backend/app/pipeline/ws.py`
- Modify: `backend/app/main.py` (register WS route)
- Test: manual / integration

### Step 1: Implement pipeline progress WebSocket

The existing `job_progress_ws` in `backend/app/jobs/ws.py` polls `BackgroundJob`. Create a new WS endpoint for pipeline runs that polls `PatientTask` aggregate counts:

```python
async def pipeline_progress_ws(websocket: WebSocket, project_id: str, run_id: str):
    await websocket.accept()
    last_progress = None

    try:
        while True:
            async with async_session() as session:
                run = await session.get(PipelineRun, run_id)
                if not run or run.project_id != project_id:
                    await websocket.close(code=4004)
                    return

                stats = await get_run_stats(session, run_id)
                progress = {
                    "type": "progress",
                    "run_id": run_id,
                    "status": run.status.value,
                    "total": stats.total,
                    "completed": stats.completed,
                    "failed": stats.failed,
                    "processing": stats.processing,
                    "queued": stats.queued,
                }

                if progress != last_progress:
                    await websocket.send_json(progress)
                    last_progress = progress

                if run.status in (PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED, PipelineRunStatus.CANCELLED):
                    progress["type"] = run.status.value
                    progress["result_summary"] = run.result_summary
                    await websocket.send_json(progress)
                    break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
```

Register in `main.py`:
```python
from app.pipeline.ws import pipeline_progress_ws
application.websocket("/ws/projects/{project_id}/pipeline/{run_id}")(pipeline_progress_ws)
```

### Step 2: Commit

```bash
git add backend/app/pipeline/ws.py backend/app/main.py
git commit -m "feat: add WebSocket endpoint for pipeline run progress"
```

---

## Task 7: Eval Flow Rework — Unified Sample → Review → Calibrate → Commit

**Files:**
- Modify: `backend/app/pipeline/service.py` (add calibration logic)
- Modify: `backend/app/pipeline/router.py` (add eval/calibration endpoints)
- Test: `backend/tests/test_pipeline_api.py` (extend)

### Step 1: Write the failing test

```python
class TestEvalCalibration:
    async def test_review_sample_annotations(self, client):
        """After sample run, user reviews annotations and system calibrates threshold."""
        await register_and_login(client)
        pid = await create_project(client)
        await _ingest_test_data(client, pid)
        eid = await _create_event_config(client, pid)

        # Run sample (mocking LLM)
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            _setup_mock_agent_responses(mock_llm)
            run_resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
                json={"sample_size": 3},
            )
            await asyncio.sleep(0.5)

        run_id = run_resp.json()["id"]

        # Get annotations from this run
        annot_resp = await client.get(
            f"/api/v1/projects/{pid}/annotations",
            params={"pipeline_run_id": run_id},
        )
        annotations = annot_resp.json()

        # Review: confirm first, reject second
        await client.post(
            f"/api/v1/projects/{pid}/annotations/{annotations[0]['id']}/review",
            json={"reviewer_label": "positive"},
        )
        await client.post(
            f"/api/v1/projects/{pid}/annotations/{annotations[1]['id']}/review",
            json={"reviewer_label": "negative"},
        )

        # Get calibrated metrics
        metrics_resp = await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/metrics",
        )
        assert metrics_resp.status_code == 200
        metrics = metrics_resp.json()
        assert "precision" in metrics
        assert "recall" in metrics
        assert "suggested_threshold" in metrics
```

### Step 2: Implement calibration

Add to `backend/app/pipeline/service.py`:

```python
async def compute_run_metrics(session, run_id):
    """Compute precision/recall/F1 from reviewed annotations in a pipeline run.

    Compares predicted_label against reviewer_label for all reviewed annotations.
    Suggests a confidence threshold based on score distribution.
    """
    # Query annotations WHERE pipeline_run_id = run_id AND review_status IN (confirmed, rejected)
    # Count TP (predicted=positive, reviewer=positive/confirmed)
    # Count FP (predicted=positive, reviewer=negative/rejected)
    # Count FN (predicted=negative, reviewer=positive)
    # Count TN (predicted=negative, reviewer=negative)
    # Compute precision, recall, F1, accuracy
    # Compute suggested_threshold from score distribution (optimal F1 cutoff)
```

Add to `backend/app/pipeline/router.py`:
- `GET /runs/{run_id}/metrics` → compute_run_metrics
- Modify `POST /events/{event_id}/commit` to optionally accept `confidence_threshold`

### Step 3: Run tests and commit

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_api.py -v
git add backend/app/pipeline/ backend/tests/test_pipeline_api.py
git commit -m "feat: add eval calibration and metrics for pipeline runs"
```

---

## Task 8: Job Dashboard API

**Files:**
- Modify: `backend/app/pipeline/router.py` (dashboard endpoints)
- Modify: `backend/app/pipeline/service.py`
- Test: `backend/tests/test_pipeline_api.py` (extend)

### Step 1: Write the failing test

```python
class TestJobDashboard:
    async def test_list_pipeline_runs(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    async def test_get_run_detail_with_task_breakdown(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        # ... create run, check stats endpoint

    async def test_retry_failed_tasks(self, client):
        # ... create run with some failed tasks, retry, verify re-queued

    async def test_list_patient_tasks_for_run(self, client):
        # ... paginated task list with status filter
```

### Step 2: Implement dashboard endpoints

Add to router:
- `GET /runs` — list all pipeline runs for project (with stats summary)
- `GET /runs/{run_id}` — run detail + aggregate stats
- `GET /runs/{run_id}/tasks` — paginated PatientTask list with `?status=` filter
- `GET /runs/{run_id}/tasks/{task_id}` — single task detail with agent_trace
- `POST /runs/{run_id}/retry-failed` — re-queue failed tasks
- `POST /runs/{run_id}/retry-stalled` — re-queue tasks stuck in `processing` > 10min

### Step 3: Run tests and commit

```bash
git add backend/app/pipeline/ backend/tests/test_pipeline_api.py
git commit -m "feat: add job dashboard API endpoints"
```

---

## Task 9: Frontend — EventConfig UI (Pipeline Page Rework)

**Files:**
- Create: `frontend/src/projects/EventConfigPage.tsx`
- Modify: `frontend/src/projects/types.ts` (add types)
- Modify: `frontend/src/api/client.ts` (add API calls)
- Modify: `frontend/src/components/AppSidebar.tsx` (navigation)

### Step 1: Add TypeScript types

Add to `frontend/src/projects/types.ts`:

```typescript
export interface SearchQueryItem {
  query: string;
  name: string;
}

export interface EventConfig {
  id: string;
  project_id: string;
  name: string;
  description: string;
  include_criteria: string;
  exclude_criteria: string;
  search_queries: SearchQueryItem[];
  llm_provider: string;
  llm_model: string;
  llm_api_base: string | null;
  max_agent_rounds: number;
  confidence_threshold: number | null;
  is_committed: boolean;
  created_at: string;
  updated_at: string;
}

export interface PipelineRun {
  id: string;
  project_id: string;
  event_config_id: string;
  run_type: "sample" | "full";
  status: "queued" | "running" | "completed" | "failed" | "cancelled";
  sample_size: number | null;
  total_patients: number;
  is_cancelled: boolean;
  result_summary: Record<string, unknown> | null;
  error_message: string | null;
  created_by: string;
  started_at: string | null;
  completed_at: string | null;
  created_at: string;
}

export interface PipelineRunStats {
  total: number;
  queued: number;
  processing: number;
  completed: number;
  failed: number;
  skipped: number;
  total_tokens: Record<string, number> | null;
}

export interface PatientTaskSummary {
  id: number;
  patient_id: string;
  status: string;
  finding_label: string | null;
  finding_reasoning: string | null;
  tool_calls: number;
  error_message: string | null;
}

export interface EvidenceItem {
  id: string;
  note_id: string;
  text: string;
  start_pos: number;
  end_pos: number;
  match_source: string;
  match_query: string | null;
  agent_round: number;
}
```

### Step 2: Build EventConfig page

The page replaces the current PipelinePage + EvaluationPage split. Use shadcn/ui components. Sections:

1. **Event Definition Form** — name, description, include/exclude criteria, search queries (dynamic list), LLM provider/model/api_base, max rounds
2. **Save / Update** — creates or updates EventConfig
3. **Run Sample** button → starts sample PipelineRun, shows JobBanner
4. **Sample Results** — table of patient findings with evidence
5. **Review** — click into each finding, confirm/reject (uses annotation endpoints)
6. **Metrics** — precision/recall/F1 after reviews
7. **Commit** button — locks config with optional threshold
8. **Run Full Pipeline** button — starts full PipelineRun

Use the existing `JobBanner` component pattern for progress tracking, adapted to use the new pipeline WebSocket.

### Step 3: Run type check

```bash
cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit
```

### Step 4: Commit

```bash
git add frontend/src/
git commit -m "feat: add EventConfig and pipeline run UI"
```

---

## Task 10: Frontend — Annotation Review UI (Evidence-Based)

**Files:**
- Modify: `frontend/src/projects/AnnotationsPage.tsx`
- Create: `frontend/src/components/EvidenceHighlighter.tsx`
- Create: `frontend/src/components/NoteViewer.tsx`

### Step 1: Build EvidenceHighlighter component

Component that takes note text + evidence spans and renders the text with highlighted regions:

```typescript
interface EvidenceHighlighterProps {
  noteText: string;
  evidences: EvidenceItem[];
}

function EvidenceHighlighter({ noteText, evidences }: EvidenceHighlighterProps) {
  // Sort evidences by start_pos
  // Build segments: [plain_text, highlighted_text, plain_text, ...]
  // Render with <mark> tags for highlighted portions
}
```

### Step 2: Rework AnnotationsPage

The page now shows **patient-level findings** instead of individual sentences:

1. **Patient list** — filtered by `predicted_label`, sorted by review status
2. **Patient card** — shows agent determination, reasoning, confidence score
3. **Evidence panel** — lists evidence excerpts grouped by note
4. **Note viewer** — expands full note with evidence highlighted via `EvidenceHighlighter`
5. **Review actions** — Confirm / Reject / Skip, event date picker, reviewer notes

### Step 3: Type check and commit

```bash
cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit
git add frontend/src/
git commit -m "feat: rework annotation UI for patient-level evidence-based review"
```

---

## Task 11: Frontend — Job Dashboard Page

**Files:**
- Create: `frontend/src/projects/JobDashboardPage.tsx`
- Modify: `frontend/src/components/AppSidebar.tsx` (add nav link)

### Step 1: Build JobDashboardPage

Sections:
1. **Pipeline Runs table** — status, progress, patient counts, timestamps, actions (cancel/retry)
2. **Expandable run detail** — PatientTask breakdown (chart or table), failed tasks with errors
3. **Token usage summary** — aggregate prompt/completion/total tokens
4. **Other jobs section** — ingestion and export jobs (using existing BackgroundJob API)

Actions:
- Cancel running pipeline
- Retry failed patient tasks
- Retry stalled tasks
- View agent trace for individual patient tasks

### Step 2: Type check and commit

```bash
cd /Users/rsingh/Programming/CEDARS/frontend && npx tsc --noEmit
git add frontend/src/
git commit -m "feat: add job dashboard page with pipeline run management"
```

---

## Task 12: Clean Up Old Code

**Files:**
- Modify: `backend/app/nlp/router.py` — remove NLP run/cancel/status endpoints (keep search query CRUD for now as migration bridge)
- Modify: `backend/app/nlp/service.py` — remove `dispatch_nlp_job`, `cancel_nlp_job`
- Modify: `backend/app/annotations/router.py` — remove prediction dispatch endpoints
- Modify: `backend/app/annotations/service.py` — remove `dispatch_prediction_job`, `cancel_prediction_job`, `run_bulk_predictions`
- Remove: `backend/app/jobs/nlp.py`
- Remove: `backend/app/jobs/prediction.py`
- Modify: `backend/app/worker.py` — remove `run_nlp_job`, `run_prediction_job` from functions list
- Modify: `backend/app/main.py` — remove old WS route if replaced
- Update: `backend/tests/` — update or remove tests for removed endpoints

### Step 1: Remove old NLP dispatch code

Remove from `backend/app/nlp/router.py`:
- `POST /run` (dispatch_nlp_job)
- `POST /cancel` (cancel_nlp_job)
- `GET /job/status` (get_nlp_job_status)

Keep:
- Search query CRUD (`POST/GET/PUT/DELETE /queries`)
- `GET /stats` (useful for project overview)

### Step 2: Remove old prediction dispatch code

Remove from `backend/app/annotations/router.py`:
- `POST /predictions/run`
- `GET /predictions/status`
- `POST /predictions/cancel`
- `POST /run` (synchronous bulk run)
- `GET /estimate`

Keep:
- Annotation CRUD and review endpoints (they work with the new model)
- Patient-first review endpoints

### Step 3: Remove old job executors

Delete `backend/app/jobs/nlp.py` and `backend/app/jobs/prediction.py`.
Remove their entries from `backend/app/worker.py`.

### Step 4: Run full test suite

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v
```

Fix any broken tests. Tests that tested removed endpoints should be deleted or replaced with pipeline API tests.

### Step 5: Commit

```bash
git add -u backend/
git commit -m "refactor: remove old NLP and prediction dispatch code, replaced by unified pipeline"
```

---

## Task 13: End-to-End Integration Test

**Files:**
- Create: `backend/tests/test_pipeline_e2e.py`

### Step 1: Write the full workflow test

```python
"""End-to-end test: ingest → configure → sample → review → commit → full run → annotate."""

class TestPipelineE2E:
    async def test_full_workflow(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        # 1. Ingest data
        await _ingest_test_data(client, pid)

        # 2. Create EventConfig
        eid = await _create_event_config(client, pid)

        # 3. Run sample
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            _setup_mock_agent_responses(mock_llm)
            run_resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
                json={"sample_size": 2},
            )
            await asyncio.sleep(1)

        run = run_resp.json()
        assert run["status"] == "completed"

        # 4. Check annotations created
        annots = (await client.get(
            f"/api/v1/projects/{pid}/annotations",
            params={"pipeline_run_id": run["id"]},
        )).json()
        assert len(annots) >= 1

        # 5. Review annotations
        for a in annots:
            await client.post(
                f"/api/v1/projects/{pid}/annotations/{a['id']}/review",
                json={"reviewer_label": "positive"},
            )

        # 6. Check metrics
        metrics = (await client.get(
            f"/api/v1/projects/{pid}/pipeline/runs/{run['id']}/metrics",
        )).json()
        assert metrics["precision"] is not None

        # 7. Commit config
        await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit",
            json={"confidence_threshold": metrics.get("suggested_threshold", 0.5)},
        )

        # 8. Run full pipeline
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            _setup_mock_agent_responses(mock_llm)
            full_resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-full",
            )
            await asyncio.sleep(1)

        full_run = full_resp.json()
        # Sample patients should be excluded from full run
        assert full_run["total_patients"] >= 1

        # 9. Check job dashboard
        runs = (await client.get(f"/api/v1/projects/{pid}/pipeline/runs")).json()
        assert len(runs) == 2  # sample + full
```

### Step 2: Run test

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_e2e.py -v
```

### Step 3: Commit

```bash
git add backend/tests/test_pipeline_e2e.py
git commit -m "test: add end-to-end pipeline integration test"
```

---

## Summary of Tasks

| Task | Component | Estimated Size |
|------|-----------|---------------|
| 1 | Data models (EventConfig, PipelineRun, PatientTask, Evidence) | Medium |
| 2 | Rework Annotation model to patient-level | Medium |
| 3 | EventConfig CRUD API | Medium |
| 4 | Agent engine (tools + agent loop) | Large |
| 5 | Pipeline orchestration (sample + full + cancel + retry) | Large |
| 6 | WebSocket for pipeline progress | Small |
| 7 | Eval calibration flow | Medium |
| 8 | Job dashboard API | Medium |
| 9 | Frontend: EventConfig UI | Large |
| 10 | Frontend: Annotation review UI | Large |
| 11 | Frontend: Job dashboard page | Medium |
| 12 | Clean up old code | Medium |
| 13 | E2E integration test | Small |

**Dependencies:** Tasks 1→2→3→4→5→6→7→8 are sequential (each builds on prior). Tasks 9, 10, 11 (frontend) can start after Task 8. Task 12 after Task 8. Task 13 after all others.
