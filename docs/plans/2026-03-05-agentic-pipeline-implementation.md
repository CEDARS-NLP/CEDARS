# Agentic Pipeline Implementation Plan (v2)

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace separate NLP and LLM prediction pipelines with a scalable two-phase architecture: LLM-assisted search pattern generation on a sample, then batch per-patient search+classify across the full corpus.

**Architecture:** Clinician describes events in natural language → LLM generates search patterns → patterns run deterministically on sample → LLM classifies matched notes → clinician reviews/calibrates → approved pipeline runs per-patient at scale via PatientTask queue with SKIP LOCKED.

**Tech Stack:** FastAPI, SQLAlchemy/SQLModel, Alembic, LiteLLM (classification + pattern generation), spaCy (deterministic search), ARQ (worker queue), React + TypeScript + shadcn/ui (frontend)

**Design doc:** `docs/plans/2026-03-05-agentic-pipeline-redesign.md`

---

## Task 1: New Data Models — EventConfig, PipelineRun, PatientTask, Evidence

**Files:**
- Create: `backend/app/pipeline/__init__.py`
- Create: `backend/app/pipeline/models.py`
- Modify: `backend/tests/conftest.py` (register models)
- Test: `backend/tests/test_pipeline_models.py`

### Step 1: Write the failing test

```python
"""Tests for pipeline data models."""
import pytest
from sqlmodel import select


async def _get_session(app):
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
                search_patterns={
                    "keywords": ["troponin", "MI"],
                    "regex_patterns": [r"troponin.*elevated"],
                    "exclusion_patterns": ["rule.?out"],
                },
                llm_provider="ollama",
                llm_model="llama3",
            )
            session.add(config)
            await session.commit()
            await session.refresh(config)
            assert config.id is not None
            assert config.is_committed is False
            assert config.confidence_threshold is None


class TestPipelineRunModel:
    async def test_create_pipeline_run(self, app):
        from app.pipeline.models import EventConfig, PipelineRun, PipelineRunStatus
        async for session in _get_session(app):
            ec = EventConfig(
                project_id="proj-1", name="MI", description="MI",
                include_criteria="x", exclude_criteria="y",
                search_patterns={}, llm_provider="ollama", llm_model="llama3",
            )
            session.add(ec)
            await session.commit()
            await session.refresh(ec)

            run = PipelineRun(
                project_id="proj-1", event_config_id=ec.id,
                run_type="sample", status=PipelineRunStatus.QUEUED,
                config_snapshot={"name": "MI"}, sample_size=50,
                total_patients=50, created_by="user-1",
            )
            session.add(run)
            await session.commit()
            await session.refresh(run)
            assert run.id is not None
            assert run.is_cancelled is False


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
                search_patterns={}, llm_provider="ollama", llm_model="llama3",
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
                pipeline_run_id=run.id, patient_id="patient-1",
                status=PatientTaskStatus.QUEUED,
            )
            session.add(task)
            await session.commit()
            await session.refresh(task)
            assert task.id is not None
            assert task.notes_matched == 0
            assert task.finding_label is None


class TestEvidenceModel:
    async def test_create_evidence(self, app):
        from app.pipeline.models import Evidence
        ev = Evidence(
            patient_task_id=1, note_id="note-1",
            text="troponin elevated at 2.4 ng/mL",
            start_pos=120, end_pos=155,
            match_source="keyword", match_pattern="troponin",
        )
        assert ev.match_source == "keyword"
```

### Step 2: Run test — expected FAIL (`ModuleNotFoundError`)

```bash
cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_pipeline_models.py -v
```

### Step 3: Implement models

Create `backend/app/pipeline/__init__.py`:
```python
"""Agentic pipeline module."""
```

Create `backend/app/pipeline/models.py` with:
- `EventConfig` — `search_patterns: JSON` (not `search_queries`), `llm_provider`, `llm_model`, `llm_api_base`, `confidence_threshold`, `is_committed`
- `PipelineRun` — `run_type`, `status`, `config_snapshot: JSON`, `is_cancelled`, `result_summary: JSON`
- `PatientTask` — `status`, `notes_searched`, `notes_matched`, `finding_label`, `finding_reasoning`, `finding_evidence: JSON`, `predicted_score`, `token_usage: JSON`
- `Evidence` — `patient_task_id`, `note_id`, `text`, `start_pos`, `end_pos`, `match_source`, `match_pattern`
- Enums: `PipelineRunStatus`, `PipelineRunType`, `PatientTaskStatus`

Register in `backend/tests/conftest.py`:
```python
from app.pipeline.models import EventConfig, PipelineRun, PatientTask, Evidence  # noqa: F401
```

### Step 4: Run test — expected PASS

### Step 5: Create Alembic migration

```bash
cd /Users/rsingh/Programming/CEDARS/backend
uv run alembic revision --autogenerate -m "add pipeline models"
```

### Step 6: Commit

```bash
git add backend/app/pipeline/ backend/tests/test_pipeline_models.py backend/tests/conftest.py backend/migrations/versions/
git commit -m "feat: add pipeline data models (EventConfig, PipelineRun, PatientTask, Evidence)"
```

---

## Task 2: Rework Annotation Model to Patient-Level

**Files:**
- Modify: `backend/app/annotations/models.py`
- Modify: `backend/app/annotations/schemas.py`
- Test: extend `backend/tests/test_pipeline_models.py`

### Step 1: Write failing test for new fields

Test creating an Annotation with `pipeline_run_id`, `patient_task_id`, `predicted_reasoning`, `reviewer_label`, `reviewer_notes`, and `ReviewStatus.PENDING`.

### Step 2: Update the model

Key changes to `backend/app/annotations/models.py`:
- `ReviewStatus`: `PENDING | CONFIRMED | REJECTED | SKIPPED` (was `UNREVIEWED | REVIEWED | SKIPPED`)
- Add fields: `pipeline_run_id`, `patient_task_id`, `predicted_reasoning`, `reviewer_label`, `reviewer_notes`
- `predicted_label` becomes string (was int 0/1)
- Legacy fields (`sentence_id`, `sentence_text`, etc.) kept as Optional for backward compat

### Step 3: Update schemas, create migration, fix existing tests

```bash
uv run alembic revision --autogenerate -m "update annotations for pipeline linkage"
uv run pytest tests/ -v  # fix breakages
```

### Step 4: Commit

```bash
git commit -m "feat: rework Annotation model to patient-level with pipeline linkage"
```

---

## Task 3: EventConfig CRUD API

**Files:**
- Create: `backend/app/pipeline/schemas.py`
- Create: `backend/app/pipeline/service.py`
- Create: `backend/app/pipeline/router.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/test_pipeline_api.py`

### Step 1: Write failing tests

Test CRUD for EventConfig:
- `POST /api/v1/projects/{pid}/pipeline/events` → 201
- `GET /api/v1/projects/{pid}/pipeline/events` → list
- `PUT /api/v1/projects/{pid}/pipeline/events/{eid}` → update
- `DELETE /api/v1/projects/{pid}/pipeline/events/{eid}` → 204
- `POST /api/v1/projects/{pid}/pipeline/events/{eid}/commit` → locks config
- Cannot update committed config → 400

### Step 2: Implement schemas, service, router

**Router prefix:** `/api/v1/projects/{project_id}/pipeline`

**Service:** Follow patterns from `backend/app/predictors/service.py`. Business rule: reject updates/deletes on committed configs.

**Register in `main.py`:** Add `pipeline_router`.

### Step 3: Run tests, commit

```bash
git commit -m "feat: add EventConfig CRUD API"
```

---

## Task 4: LLM Pattern Generation

**Files:**
- Create: `backend/app/pipeline/pattern_generator.py`
- Test: `backend/tests/test_pattern_generator.py`

### Step 1: Write failing test

```python
class TestPatternGenerator:
    async def test_generates_patterns_from_description(self):
        """LLM should generate keywords, regex, and exclusion patterns."""
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "keywords": ["troponin", "MI", "myocardial infarction"],
                "regex_patterns": ["troponin.*(?:elevated|positive)"],
                "exclusion_patterns": ["rule.?out", "family history"],
            }))

            from app.pipeline.pattern_generator import generate_search_patterns
            result = await generate_search_patterns(
                event_name="Myocardial Infarction",
                description="Confirmed MI",
                include_criteria="Troponin elevation, ECG changes",
                exclude_criteria="Rule-outs, family history",
                llm_provider="ollama", llm_model="llama3",
            )
            assert len(result["keywords"]) >= 2
            assert len(result["regex_patterns"]) >= 1
            assert len(result["exclusion_patterns"]) >= 1
```

### Step 2: Implement

`generate_search_patterns()` makes a single LLM call with a system prompt that asks the LLM to output JSON with `keywords`, `regex_patterns`, and `exclusion_patterns`. Parses the JSON response. Validates regex patterns compile without error.

Add router endpoint: `POST /events/{eid}/generate-patterns` — regenerates patterns from the event description and updates the EventConfig.

### Step 3: Run tests, commit

```bash
git commit -m "feat: add LLM-powered search pattern generation"
```

---

## Task 5: Deterministic Note Search Engine

**Files:**
- Create: `backend/app/pipeline/search.py`
- Test: `backend/tests/test_pipeline_search.py`

### Step 1: Write failing test

```python
class TestNoteSearch:
    def test_keyword_search_finds_matches(self):
        from app.pipeline.search import search_patient_notes
        notes = [
            FakeNote(id="n1", text="Patient has troponin elevation and chest pain."),
            FakeNote(id="n2", text="No significant findings today."),
        ]
        results = search_patient_notes(
            notes,
            keywords=["troponin"],
            regex_patterns=[],
            exclusion_patterns=[],
        )
        assert len(results) == 1
        assert results[0].note_id == "n1"
        assert "troponin" in results[0].text.lower()

    def test_regex_search_finds_patterns(self):
        notes = [FakeNote(id="n1", text="Troponin I level: 2.4 ng/mL, elevated.")]
        results = search_patient_notes(
            notes, keywords=[],
            regex_patterns=[r"troponin.*?(\d+\.?\d*)\s*ng/mL"],
            exclusion_patterns=[],
        )
        assert len(results) == 1

    def test_exclusion_patterns_filter_matches(self):
        notes = [
            FakeNote(id="n1", text="Family history of MI."),
            FakeNote(id="n2", text="Confirmed MI with troponin elevation."),
        ]
        results = search_patient_notes(
            notes, keywords=["MI"],
            regex_patterns=[],
            exclusion_patterns=["family history"],
        )
        # n1 should be excluded
        assert len(results) == 1
        assert results[0].note_id == "n2"

    def test_regex_timeout_protection(self):
        """Catastrophic backtracking should not hang."""
        notes = [FakeNote(id="n1", text="a" * 10000)]
        results = search_patient_notes(
            notes, keywords=[],
            regex_patterns=[r"(a+)+b"],  # catastrophic backtracking
            exclusion_patterns=[],
        )
        assert len(results) == 0  # timeout, no match
```

### Step 2: Implement

`search_patient_notes()` takes a list of notes and search patterns. For each note:
1. Run keyword matching (case-insensitive, word boundary aware via spaCy or simple regex)
2. Run regex patterns with 2-second timeout per pattern (via `concurrent.futures.ThreadPoolExecutor`)
3. Check exclusion patterns — if matched, skip the note
4. Return list of `SearchMatch(note_id, text, start_pos, end_pos, match_source, match_pattern)` dataclasses

This is the deterministic core — no LLM calls, pure compute.

### Step 3: Run tests, commit

```bash
git commit -m "feat: implement deterministic note search engine with timeout protection"
```

---

## Task 6: LLM Note Classification

**Files:**
- Create: `backend/app/pipeline/classifier.py`
- Test: `backend/tests/test_pipeline_classifier.py`

### Step 1: Write failing test

```python
class TestNoteClassifier:
    async def test_classifies_positive_note(self):
        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            mock_llm.return_value = _mock_response(json.dumps({
                "event_detected": True,
                "confidence": 0.92,
                "reasoning": "Troponin elevated, ECG shows ST changes",
            }))

            from app.pipeline.classifier import classify_note
            result = await classify_note(
                note_text="Troponin I elevated at 2.4 ng/mL...",
                matched_excerpts=["troponin I elevated at 2.4 ng/mL"],
                event_config=mock_config,
            )
            assert result.label == "positive"
            assert result.score == 0.92
            assert "Troponin" in result.reasoning

    async def test_classifies_multiple_notes_concurrently(self):
        """Should use asyncio.gather for concurrent classification."""
        from app.pipeline.classifier import classify_patient_notes
        # ... test that multiple notes are classified concurrently
```

### Step 2: Implement

`classify_note()` — single LLM call with the full note text + event definition. Returns `ClassificationResult(label, score, reasoning, token_usage)`.

`classify_patient_notes()` — for a patient with multiple matched notes, runs `asyncio.gather(*[classify_note(n) for n in notes])`. Aggregates results into a single patient-level finding (positive if any note is positive).

Reuse prompt structure from `backend/app/predictors/llm.py` but adapt for the new event config format.

### Step 3: Run tests, commit

```bash
git commit -m "feat: implement LLM note classifier with concurrent per-patient calls"
```

---

## Task 7: Pipeline Run Orchestration

**Files:**
- Create: `backend/app/pipeline/orchestrator.py`
- Create: `backend/app/jobs/pipeline.py`
- Modify: `backend/app/worker.py`
- Modify: `backend/app/pipeline/router.py` (add run endpoints)
- Test: `backend/tests/test_pipeline_api.py` (extend)

### Step 1: Write failing tests

```python
class TestPipelineRun:
    async def test_run_sample(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _ingest_test_data(client, pid)
        eid = await _create_event_config(client, pid)

        with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
            _setup_mock_classify_response(mock_llm)
            resp = await client.post(
                f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
                json={"sample_size": 2},
            )
            await asyncio.sleep(1)

        assert resp.status_code == 200
        data = resp.json()
        assert data["run_type"] == "sample"
        assert data["total_patients"] == 2

    async def test_run_full_requires_committed_config(self, client):
        # ... should return 400 if not committed

    async def test_cancel_pipeline_run(self, client):
        # ... cancel sets is_cancelled, stops processing

    async def test_retry_failed_tasks(self, client):
        # ... re-queues failed PatientTasks
```

### Step 2: Implement

**`backend/app/pipeline/orchestrator.py`:**

- `dispatch_sample_run(session, project_id, event_config_id, user_id, sample_size)` — random sample patients, create PipelineRun + PatientTasks, enqueue to ARQ
- `dispatch_full_run(session, project_id, event_config_id, user_id)` — all patients minus already-processed, require committed config
- `cancel_run(session, project_id, run_id)` — set `is_cancelled=True`
- `retry_failed(session, project_id, run_id)` — re-queue failed tasks
- `get_run_stats(session, run_id)` — COUNT by PatientTask status

**`backend/app/jobs/pipeline.py`:**

```python
async def execute_pipeline_run(pipeline_run_id: str):
    """Process patients for a pipeline run. Called by ARQ worker."""
    # 1. Get PipelineRun, extract config_snapshot
    # 2. Loop: claim next PatientTask (SKIP LOCKED for Postgres, simple SELECT for SQLite)
    # 3. Per patient:
    #    a. Load notes
    #    b. Run search_patient_notes() with committed patterns → Evidence records
    #    c. If matches: classify_patient_notes() → 1+ LLM calls
    #    d. Create Annotation with classification result
    #    e. Update PatientTask (completed/failed)
    #    f. Commit
    # 4. Check is_cancelled between patients
    # 5. Update PipelineRun status when done
```

**Router additions:**
- `POST /events/{eid}/run-sample` → dispatch_sample_run
- `POST /events/{eid}/run-full` → dispatch_full_run (requires committed config)
- `POST /runs/{run_id}/cancel`
- `POST /runs/{run_id}/retry-failed`
- `GET /runs/{run_id}` → run detail
- `GET /runs/{run_id}/stats`
- `GET /runs/{run_id}/tasks` → paginated PatientTasks
- `GET /runs` → list all runs for project

**Worker:** Add `run_pipeline_job` to `WorkerSettings.functions`.

### Step 3: Run tests, commit

```bash
git commit -m "feat: implement pipeline orchestration (sample, full, cancel, retry)"
```

---

## Task 8: WebSocket for Pipeline Progress

**Files:**
- Create: `backend/app/pipeline/ws.py`
- Modify: `backend/app/main.py`

### Step 1: Implement

WebSocket at `/ws/projects/{project_id}/pipeline/{run_id}`. Polls PatientTask aggregate counts every 1 second. Sends progress JSON. Closes on terminal status.

### Step 2: Register in `main.py`, commit

```bash
git commit -m "feat: add WebSocket for pipeline run progress"
```

---

## Task 9: Eval Calibration (Metrics from Sample Reviews)

**Files:**
- Modify: `backend/app/pipeline/service.py`
- Modify: `backend/app/pipeline/router.py`
- Test: extend `backend/tests/test_pipeline_api.py`

### Step 1: Write failing test

Test that after reviewing sample annotations (confirm/reject), the metrics endpoint returns precision/recall/F1 and a suggested threshold.

### Step 2: Implement

`compute_run_metrics(session, run_id)` — compare `predicted_label` vs `reviewer_label` for all reviewed annotations in the run. Compute TP/FP/FN/TN. Suggest threshold from score distribution.

Router: `GET /runs/{run_id}/metrics`

Modify `POST /events/{eid}/commit` to accept optional `confidence_threshold`.

### Step 3: Run tests, commit

```bash
git commit -m "feat: add eval calibration and metrics for pipeline runs"
```

---

## Task 10: Job Dashboard API

**Files:**
- Modify: `backend/app/pipeline/router.py`
- Test: extend tests

### Step 1: Implement dashboard endpoints

- `GET /runs` — list all runs with summary stats
- `GET /runs/{run_id}/tasks?status=failed` — filtered task list
- `GET /runs/{run_id}/tasks/{task_id}` — single task detail
- `POST /runs/{run_id}/retry-stalled` — re-queue tasks stuck in `processing` > 10min

### Step 2: Run tests, commit

```bash
git commit -m "feat: add job dashboard API endpoints"
```

---

## Task 11: Frontend — EventConfig + Pipeline UI

**Files:**
- Create: `frontend/src/projects/EventConfigPage.tsx`
- Modify: `frontend/src/projects/types.ts`
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/components/AppSidebar.tsx`

### Step 1: Add TypeScript types

Add `EventConfig`, `PipelineRun`, `PipelineRunStats`, `PatientTaskSummary`, `EvidenceItem` types.

### Step 2: Build EventConfig page

Sections:
1. **Event Definition** — name, description, include/exclude criteria (natural language textarea)
2. **Generate Patterns** button → calls LLM, displays generated keywords/regex/exclusions
3. **LLM Config** — provider, model, api_base
4. **Run Sample** → shows JobBanner with pipeline WebSocket
5. **Sample Results** — patient findings table with evidence
6. **Review Panel** — confirm/reject each finding
7. **Metrics** — precision/recall/F1 after reviews
8. **Commit** → locks config with threshold
9. **Run Full Pipeline** → JobBanner for full run

### Step 3: Type check, commit

```bash
npx tsc --noEmit
git commit -m "feat: add EventConfig and pipeline run UI"
```

---

## Task 12: Frontend — Evidence-Based Annotation UI

**Files:**
- Modify: `frontend/src/projects/AnnotationsPage.tsx`
- Create: `frontend/src/components/EvidenceHighlighter.tsx`
- Create: `frontend/src/components/NoteViewer.tsx`

### Step 1: Build EvidenceHighlighter

Component takes note text + evidence spans, renders with `<mark>` highlights at `start_pos`/`end_pos`.

### Step 2: Rework AnnotationsPage

Patient-level review: patient card with classification + reasoning + evidence + note viewer with highlights. Confirm/Reject/Skip actions.

### Step 3: Type check, commit

```bash
git commit -m "feat: rework annotation UI for evidence-based patient-level review"
```

---

## Task 13: Frontend — Job Dashboard Page

**Files:**
- Create: `frontend/src/projects/JobDashboardPage.tsx`
- Modify: `frontend/src/components/AppSidebar.tsx`

Pipeline runs table, expandable detail, cancel/retry actions, token usage summary.

```bash
git commit -m "feat: add job dashboard page"
```

---

## Task 14: Clean Up Old Code

**Files:**
- Remove old NLP dispatch from `backend/app/nlp/router.py` and `service.py`
- Remove old prediction dispatch from `backend/app/annotations/router.py` and `service.py`
- Remove `backend/app/jobs/nlp.py` and `backend/app/jobs/prediction.py`
- Update `backend/app/worker.py`
- Fix/remove broken tests

```bash
uv run pytest -v  # verify nothing breaks
git commit -m "refactor: remove old NLP and prediction dispatch code"
```

---

## Task 15: End-to-End Integration Test

Test full workflow: ingest → configure event → generate patterns → run sample → review → calibrate → commit → run full → annotate.

```bash
git commit -m "test: add end-to-end pipeline integration test"
```

---

## Summary

| Task | Component | Size | Dependencies |
|------|-----------|------|-------------|
| 1 | Data models | Medium | — |
| 2 | Rework Annotation model | Medium | 1 |
| 3 | EventConfig CRUD API | Medium | 1 |
| 4 | LLM pattern generation | Medium | 3 |
| 5 | Deterministic note search | Medium | 1 |
| 6 | LLM note classifier | Medium | 1 |
| 7 | Pipeline orchestration | Large | 2, 3, 5, 6 |
| 8 | WebSocket progress | Small | 7 |
| 9 | Eval calibration | Medium | 7 |
| 10 | Job dashboard API | Medium | 7 |
| 11 | Frontend: EventConfig + pipeline | Large | 3, 4, 7 |
| 12 | Frontend: Annotation UI | Large | 2, 7 |
| 13 | Frontend: Job dashboard | Medium | 10 |
| 14 | Clean up old code | Medium | 7 |
| 15 | E2E integration test | Small | All |

**Parallelizable:** Tasks 4, 5, 6 are independent and can be built concurrently after Task 1. Frontend tasks (11, 12, 13) can start once their backend dependencies are done.
