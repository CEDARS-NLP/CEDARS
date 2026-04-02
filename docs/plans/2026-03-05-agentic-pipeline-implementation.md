<!-- /autoplan restore point: /Users/rsingh/.gstack/projects/CEDARS-NLP-CEDARS/feature-v2-platform-autoplan-restore-20260329-205150.md -->
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

---

<!-- AUTONOMOUS DECISION LOG -->
## Decision Audit Trail

| # | Phase | Decision | Principle | Rationale | Classification | Rejected |
|---|-------|----------|-----------|-----------|----------------|----------|
| 1 | CEO | Keep custom orchestrator, isolate state machine | P3 pragmatic | Temporal/Prefect add deployment complexity incompatible with Docker Compose target | TASTE | Temporal/Prefect adoption |
| 2 | CEO | Add match rate + cost estimation to UI before full run | P1 completeness | 10% assumption unvalidated; budget cap prevents cost surprises | MECHANICAL | — |
| 3 | CEO | Fix 1-call-per-patient: use excerpts with token budget | P5 explicit | Design doc and plan contradict; single call with excerpts is correct | MECHANICAL | asyncio.gather per note |
| 4 | CEO | Add pattern validation on sample results | P1 completeness | LLM regex is fragile; show what patterns actually catch | MECHANICAL | — |
| 5 | CEO | search.py wraps engine.py (keep spaCy negation) | P4 DRY | engine.py has 291 lines of proven search/negation logic | MECHANICAL | Replace engine.py |
| 6 | CEO | Task 14: deprecate old code (flag), don't delete | P6 action | Strangler fig requires fallback for one release cycle | MECHANICAL | Hard delete |
| 7 | CEO | Defer embedding search evaluation to TODOS.md | P3 pragmatic | Valid alternative but evaluating blocks shipping | TASTE | Evaluate before shipping |
| 8 | CEO | Defer direct-LLM mode for small cohorts | P3 pragmatic | Good optimization but not blocking for initial release | MECHANICAL | — |
| 9 | CEO | Add rate limiting with backoff to classifier | P1 completeness | Batch API deferred; rate limiting is minimum viable protection | MECHANICAL | — |
| 10 | CEO | Defer "quick start" mode to TODOS.md | P3 pragmatic | Excellent UX but scope expansion beyond current plan | MECHANICAL | — |
| 11 | CEO | EventConfig list page as entry point (multi-event) | P1 completeness | Clinical studies track multiple events; single-event UI is limiting | MECHANICAL | — |
| 12 | CEO | Defer methods/reproducibility export to TODOS.md | P3 pragmatic | Competitive moat but not blocking for initial release | MECHANICAL | — |
| 13 | Design | EventConfigPage: use wizard/stepper pattern (9 sequential steps) | P5 explicit | Sequential flow needs progressive disclosure, not all-sections-visible | MECHANICAL | Flat page with all sections |
| 14 | Design | Add EventConfig list page to Task 11 (multi-event entry point) | P1 completeness | Already captured in CEO #11; Task 11 spec must include it explicitly | MECHANICAL | — |
| 15 | Design | Specify loading/error/overwrite states for pattern generation | P1 completeness | LLM calls are slow and fallible; UI must communicate progress and handle failure | MECHANICAL | — |
| 16 | Design | Add empty state to AnnotationsPage for pre-pipeline | P5 explicit | Users will see this page before running any pipeline; must guide them | MECHANICAL | — |
| 17 | Design | Job Dashboard: show per-patient status with failed count and retry | P1 completeness | Partial failures are common at scale; need visibility and recovery | MECHANICAL | — |
| 18 | Design | Design sample-complete-to-review transition (auto-advance wizard step) | P1 completeness | Critical handoff moment — user must know sample is ready for review | MECHANICAL | — |
| 19 | Design | Add confirmation dialog for commit action (metrics + cost + patient count) | P1 completeness | High-stakes action (processes full cohort) needs explicit confirmation | MECHANICAL | — |
| 20 | Design | NoteViewer: reuse AnnotationsPage pattern, highlight matched sentences | P4 DRY | Existing note viewer pattern proven; extend don't rebuild | MECHANICAL | New component from scratch |
| 21 | Design | Expand Task 13 with job list, detail panel, filters, cancel/retry, WebSocket | P1 completeness | 13-word task spec insufficient for Medium-sized frontend work | MECHANICAL | — |
| 22 | Design | Define routes, sidebar nav entry, breadcrumb for Events pages | P1 completeness | Navigation integration is structural requirement, not optional detail | MECHANICAL | — |
| 23 | Design | Pipeline annotations: separate tab on AnnotationsPage (old mode preserved) | P6 action + P5 explicit | Both modes needed during transition; tab separation is simplest | TASTE | Separate /pipeline-annotations page |
| 24 | Design | Extend JobBanner WebSocket for pipeline progress (same channel, new events) | P4 DRY | Existing WebSocket infra should be reused, not duplicated | MECHANICAL | — |
| 25 | Design | Add API client function list to Task 11 spec | P3 pragmatic | Frontend tasks need concrete API contract to implement against | MECHANICAL | — |
| 26 | Eng | Task 6 classifier must reuse predictors/llm.py, not create parallel module | P4 DRY | LLMPredictor has 223 lines of proven LLM logic (prompt, parse, error handling) | MECHANICAL | New classifier.py from scratch |
| 27 | Eng | Task 7 orchestrator follows jobs/prediction.py patterns, reuse session factory | P4 DRY | prediction.py has proven per-patient batch pattern with cancellation | MECHANICAL | — |
| 28 | Eng | EventConfig keeps LLM config inline (don't separate into FK) | P3 pragmatic | config_snapshot freezes everything; FK adds complexity for little gain now | TASTE | Separate LLM config via FK to PredictorConfig |
| 29 | Eng | Fix plan text: Task 14 deprecates behind flag, matches Decision #6 | P5 explicit | Plan text says "Remove" but Decision #6 says deprecate. Plan is inconsistent | MECHANICAL | — |
| 30 | Eng | Add match_rate to PipelineRun.result_summary + zero-match warning | P1 completeness | 0% match on sample is silent failure; clinician needs feedback | MECHANICAL | — |
| 31 | Eng | Use savepoint (session.begin_nested) per patient in pipeline executor | P1 completeness | LLM timeout leaves partial Evidence/Annotations; retry creates duplicates | MECHANICAL | — |
| 32 | Eng | Resolve Task 6 contradiction: single-call-per-patient with excerpts | P5 explicit | Decision #3 says 1-call; Task 6 says asyncio.gather per note. Pick one. | MECHANICAL | Multi-call asyncio.gather |
| 33 | Eng | Use re2 or regex-with-timeout instead of ThreadPoolExecutor for regex | P5 explicit | ThreadPoolExecutor threads cannot be killed in Python; CPU leak | MECHANICAL | ThreadPoolExecutor timeout |
| 34 | Eng | Add PostgreSQL integration test for SKIP LOCKED query path | P1 completeness | SQLite test suite cannot test SKIP LOCKED; core concurrency model untested | MECHANICAL | — |
| 35 | Eng | Add 409 Conflict check: reject concurrent pipeline runs per event config | P1 completeness | Two runs on same config create duplicate PatientTasks and Annotations | MECHANICAL | — |
| 36 | Eng | Add PatientTask.transition_status() with allowed transition validation | P1 completeness | Plain enum allows any transition; no enforcement at model level | MECHANICAL | — |
| 37 | Eng | Replace asyncio.sleep(1) in tests with synchronous job execution | P5 explicit | Sleep-and-hope causes intermittent CI failures | MECHANICAL | — |
| 38 | Eng | Validate LLM-generated regex complexity (max len, no nested quantifiers) | P1 completeness | LLM-generated regex is code injection/DoS vector via backtracking | MECHANICAL | — |
| 39 | Eng | Add Pydantic max_length on EventConfig text fields (5000 desc, 2000 criteria) | P1 completeness | Unbounded strings inflate LLM token costs | MECHANICAL | — |
| 40 | Eng | Filter by both project_id AND event_config_id in all service methods | P1 completeness | IDOR vulnerability: user in project A could reference config from project B | MECHANICAL | — |
| 41 | Eng | Document SKIP LOCKED subquery pattern in plan; handle LIMIT pitfall | P5 explicit | Known PostgreSQL pitfall: LIMIT + SKIP LOCKED can return 0 rows falsely | MECHANICAL | — |
| 42 | Eng | Defer automatic PipelineRun health-check (heartbeat) to TODOS.md | P3 pragmatic | Adds ARQ cron + heartbeat column; manual retry-stalled is sufficient for v1 | TASTE | Add heartbeat + auto-recovery now |
| 43 | Eng | Add snapshot_version field to PipelineRun for config_snapshot evolution | P1 completeness | JSON schema changes over time; old snapshots need migration path | MECHANICAL | — |
| 44 | Eng | Cache WebSocket aggregate counts in Redis instead of 1s DB polling | P3 pragmatic | 10 viewers × 1 query/sec × 100K-row table = DB pressure during writes | MECHANICAL | — |

---

## DESIGN REVIEW — Phase 2 [subagent-only]

### Design Litmus Scorecard

```
DESIGN DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                           Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ─────── ─────────
  1. Information hierarchy             5/10    N/A    NEEDS WORK
  2. Interaction states specified?     3/10    N/A    NEEDS WORK
  3. User journey / emotional arc      4/10    N/A    NEEDS WORK
  4. Specificity of UI decisions       4/10    N/A    NEEDS WORK
  5. Navigation / routing integration  2/10    N/A    CRITICAL
  6. Component reuse / DRY             6/10    N/A    ACCEPTABLE
  7. Responsiveness / accessibility    N/A     N/A    NOT ASSESSED
═══════════════════════════════════════════════════════════════
Missing voice = N/A (Codex unavailable — CLI arg error).
```

### Findings Summary

- **3 Critical:** EventConfigPage needs wizard pattern, sample→review transition undesigned, routes/sidebar/breadcrumb missing
- **5 High:** Multi-event list page missing from Task 11, pattern generation states missing, commit confirmation UX missing, Task 13 underspecified, old vs new annotation modes unresolved
- **5 Medium:** AnnotationsPage empty state, job dashboard partial failure, NoteViewer spec, JobBanner WebSocket reuse, API client functions

### Auto-Decided Actions

All 13 findings auto-decided. 12 MECHANICAL, 1 TASTE (Decision #23: pipeline annotations as tab vs separate page).

### Design Completion Summary

| Metric | Value |
|--------|-------|
| Findings | 13 (3 critical, 5 high, 5 medium) |
| Auto-decided | 13 |
| Taste decisions | 1 (#23 annotation tab vs page) |
| Design score before | 3/10 (frontend tasks are backend-engineer specs) |
| Design score after fixes | 7/10 (wizard pattern, states, routes specified) |
| Codex available | No (CLI argument error) |

---

## CROSS-PHASE THEMES

| Theme | Phases | Signal |
|-------|--------|--------|
| Code reuse vs new modules | CEO (#5), Eng (#26, #27) | High-confidence: existing predictors/llm.py, nlp/engine.py, jobs/prediction.py should be reused, not duplicated |
| Task 6 contradicts Decision #3 (calls-per-patient) | CEO (#3), Eng (#32, subagent 5.5) | High-confidence: plan text internally inconsistent. Must be single-call with excerpts. |
| Error recovery / partial data | CEO (subagent), Eng (#31, #35, subagent 2.2, 3.2, 5.2) | High-confidence: no savepoints, no mutual exclusion, no orphan detection. Three independent reviewers flagged this. |
| Frontend task underspecification | Design (#13, #21, #22), Eng (test diagram) | High-confidence: Tasks 11-13 lack routes, states, component specs. Design review added wizard pattern + routes. |

---

## ENG REVIEW — Phase 3 [subagent-only]

### Architecture Diagram

```
                          ┌─────────────┐
                          │   React UI  │
                          │ EventConfig │
                          │   Wizard    │
                          └──────┬──────┘
                                 │ REST + WebSocket
                                 ▼
                    ┌────────────────────────┐
                    │  pipeline/router.py     │
                    │  CRUD + run endpoints   │
                    └────────┬───────────────┘
                             │
              ┌──────────────┼──────────────────┐
              ▼              ▼                   ▼
   ┌──────────────┐  ┌──────────────┐  ┌──────────────────┐
   │ pipeline/    │  │ pipeline/    │  │ pipeline/         │
   │ service.py   │  │ pattern_gen  │  │ orchestrator.py   │
   │ (CRUD,       │  │ .py          │  │ (dispatch, cancel,│
   │  metrics)    │  │ (LLM→regex)  │  │  retry, stats)    │
   └──────────────┘  └──────┬───────┘  └────────┬──────────┘
                            │                    │
                            │                    │ ARQ enqueue
                            ▼                    ▼
                    ┌──────────────┐   ┌──────────────────┐
                    │ predictors/  │   │ jobs/pipeline.py  │
                    │ llm.py       │   │ execute_pipeline  │
                    │ (REUSE)      │   │ _run()            │
                    └──────────────┘   └────────┬──────────┘
                                                │
                                    ┌───────────┴───────────┐
                                    ▼                       ▼
                          ┌──────────────┐       ┌──────────────┐
                          │ pipeline/    │       │ predictors/  │
                          │ search.py    │       │ llm.py       │
                          │ (wraps       │       │ (classify    │
                          │  engine.py)  │       │  patient)    │
                          └──────┬───────┘       └──────────────┘
                                 │
                                 ▼
                          ┌──────────────┐
                          │ nlp/         │
                          │ engine.py    │
                          │ (REUSE)      │
                          └──────────────┘

Data Flow:
  EventConfig ──→ PipelineRun ──→ PatientTask ──→ Evidence
                                       │              │
                                       └──→ Annotation ┘

Queue: ARQ (Redis) → worker.py → jobs/pipeline.py
       PatientTask claimed via SKIP LOCKED (PostgreSQL)
       or CAS update (SQLite fallback)
```

### Eng Consensus Table

```
ENG DUAL VOICES — CONSENSUS TABLE:
═══════════════════════════════════════════════════════════════
  Dimension                           Claude  Codex  Consensus
  ──────────────────────────────────── ─────── ─────── ─────────
  1. Architecture sound?               6/10    N/A    NEEDS WORK
  2. Test coverage sufficient?         4/10    N/A    NEEDS WORK
  3. Performance risks addressed?      5/10    N/A    NEEDS WORK
  4. Security threats covered?         5/10    N/A    NEEDS WORK
  5. Error paths handled?             3/10    N/A    CRITICAL
  6. Deployment risk manageable?       7/10    N/A    ACCEPTABLE
═══════════════════════════════════════════════════════════════
Missing voice = N/A (Codex unavailable — CLI arg error).
```

### Findings Summary (Eng Subagent)

- **2 Critical:** Partial data on LLM timeout (savepoint needed), concurrent runs create duplicates (409 check needed)
- **9 High:** Module duplication, 0% match silent, unbounded LLM concurrency, regex thread leak, SKIP LOCKED untested, regex injection, SKIP LOCKED pitfalls, orphaned runs, Task 6 contradicts Decision #3
- **8 Medium:** EventConfig concern merge, Task 14 plan text inconsistency, state transitions unenforced, test race condition, input length limits, IDOR check, snapshot versioning, WebSocket DB polling

### Test Coverage Diagram

```
CODE PATH COVERAGE
===========================
[+] pipeline/models.py (Task 1)
    │
    ├── EventConfig CRUD
    │   ├── [★★  PLANNED] Create/read/update/delete — test_pipeline_api.py
    │   ├── [GAP]         Reject update on committed config — specified but needs explicit test
    │   └── [GAP]         Max-length validation on text fields — NO TEST
    │
    ├── PipelineRun lifecycle
    │   ├── [★★  PLANNED] Create sample/full run — test_pipeline_api.py
    │   ├── [GAP]         409 Conflict on concurrent runs — NO TEST
    │   └── [GAP]         Orphaned run detection — deferred to TODOS
    │
    └── PatientTask state machine
        ├── [★   PLANNED] Create task — test_pipeline_models.py
        ├── [GAP]         Valid transitions (queued→processing→completed/failed) — NO TEST
        └── [GAP]         Invalid transitions rejected — NO TEST

[+] pipeline/pattern_generator.py (Task 4)
    │
    ├── [★★  PLANNED] Generate patterns from description — test_pattern_generator.py
    ├── [GAP] [→EVAL]    Pattern quality eval (do LLM patterns actually match clinical text?) — needs eval
    ├── [GAP]             Regex complexity validation — NO TEST
    └── [GAP]             Pattern overwrite confirmation — NO TEST (frontend only)

[+] pipeline/search.py (Task 5)
    │
    ├── [★★★ PLANNED] Keyword search — test_pipeline_search.py
    ├── [★★★ PLANNED] Regex search — test_pipeline_search.py
    ├── [★★★ PLANNED] Exclusion patterns — test_pipeline_search.py
    ├── [★★  PLANNED] Regex timeout — test_pipeline_search.py (BUT ThreadPoolExecutor is wrong)
    ├── [GAP]         Negation detection integration (wraps engine.py) — NO TEST
    └── [GAP]         0 matches returns empty + match_rate metric — NO TEST

[+] pipeline/classifier.py (Task 6)
    │
    ├── [★★  PLANNED] Classify positive note — test_pipeline_classifier.py
    ├── [GAP]         Single-call-per-patient with excerpts (Decision #3) — contradicts plan
    ├── [GAP]         LLM timeout handling — NO TEST
    ├── [GAP]         LLM rate limit handling — NO TEST
    └── [GAP] [→EVAL] Classification accuracy eval — needs eval suite

[+] pipeline/orchestrator.py + jobs/pipeline.py (Task 7)
    │
    ├── [★★  PLANNED] Run sample — test_pipeline_api.py
    ├── [★   PLANNED] Cancel run — test_pipeline_api.py (specified, not detailed)
    ├── [★   PLANNED] Retry failed — test_pipeline_api.py (specified, not detailed)
    ├── [GAP]         SKIP LOCKED claim query (PostgreSQL) — NO TEST (SQLite suite)
    ├── [GAP]         Savepoint per patient (rollback on error) — NO TEST
    ├── [GAP]         Concurrent workers claiming same task — NO TEST
    ├── [GAP]         Worker crash mid-patient recovery — NO TEST
    └── [GAP]         Full run requires committed config — specified but needs test

[+] pipeline/ws.py (Task 8)
    │
    └── [GAP]         WebSocket progress messages — NO TEST (hard to test, but at least unit test the aggregation)

[+] pipeline/service.py - eval calibration (Task 9)
    │
    ├── [GAP]         Compute metrics (precision/recall/F1) — specified, needs explicit test
    └── [GAP]         Threshold suggestion from score distribution — NO TEST

[+] pipeline/router.py - job dashboard (Task 10)
    │
    ├── [GAP]         List runs with summary stats — specified, needs test
    ├── [GAP]         Filter tasks by status — needs test
    └── [GAP]         Retry stalled tasks (processing > 10min) — needs test

USER FLOW COVERAGE
===========================
[+] Event configuration → pattern generation → sample → review → commit → full run
    │
    ├── [GAP] [→E2E]  Complete happy path end-to-end — Task 15 (specified, good)
    ├── [GAP] [→E2E]  Pattern generation fails (LLM error) → retry
    ├── [GAP]          Sample with 0 matches → warning
    ├── [GAP]          Commit with low metrics → warning
    └── [GAP]          Full run partial failure → retry individual patients

[+] Security flows
    │
    ├── [GAP]          Cross-project IDOR on EventConfig — NO TEST
    ├── [GAP]          Prompt injection via event description — NO TEST
    └── [GAP]          Regex DoS via LLM-generated pattern — NO TEST

─────────────────────────────────────
COVERAGE: 7/35 paths have planned tests (20%)
  Code paths: 6/26 (23%)
  User flows: 1/9 (11%)
QUALITY:  ★★★: 3  ★★: 6  ★: 2
GAPS: 28 paths need tests (2 need E2E, 2 need eval)
─────────────────────────────────────
```

### NOT in scope (Eng)

| Item | Rationale |
|------|-----------|
| Automatic orphaned-run recovery (heartbeat + ARQ cron) | Adds infrastructure; manual retry-stalled sufficient for v1 |
| PostgreSQL advisory locking alternative to SKIP LOCKED | SKIP LOCKED is correct approach; just needs proper subquery pattern |
| Horizontal worker scaling config | Default ARQ max_jobs=10 is fine for initial release |
| LLM response streaming | Batch classification doesn't benefit from streaming |
| Pattern quality eval suite | Important but separate concern — add to TODOS |

### What already exists (Eng)

| Sub-problem | Existing code | Plan action |
|---|---|---|
| LLM classification | `predictors/llm.py` | Task 6 MUST reuse (Decision #26) |
| Note search + negation | `nlp/engine.py` | Task 5 wraps (Decision #5) |
| Per-patient batch execution | `jobs/prediction.py` | Task 7 follows patterns (Decision #27) |
| Job dispatch + cancel | `annotations/prediction_service.py` | Task 7 follows patterns |
| WebSocket progress | `jobs/ws.py` | Task 8 can extend or parallel (OK — different endpoint) |
| Token estimation | `prediction_service.py:estimate_bulk_predictions` | Reuse for cost estimation |
| Test fixtures | `tests/conftest.py` | Extend with pipeline model imports |

### Failure Modes Registry

| Codepath | Failure Mode | Test? | Error Handling? | User Sees? | Gap? |
|---|---|---|---|---|---|
| Pattern generation | LLM timeout | No | No | Silent failure | **CRITICAL** |
| Pattern generation | Invalid regex from LLM | Partial | Compile check only | No backtracking check | **CRITICAL** |
| Search execution | Regex catastrophic backtracking | Yes (wrong impl) | ThreadPoolExecutor (leaks) | Hang | **CRITICAL** |
| Classification | LLM timeout mid-patient | No | No savepoint | Partial data persisted | **CRITICAL** |
| Pipeline dispatch | Concurrent runs same config | No | No mutual exclusion | Duplicate annotations | **CRITICAL** |
| SKIP LOCKED | Worker crash during claim | No | No | Orphaned processing task | High |
| Full run | 50% patients fail LLM | No | Individual task failure | No aggregate view | High |
| WebSocket | 10+ viewers on large run | No | DB polling | DB pressure | Medium |
| Config snapshot | Schema evolution | No | No versioning | Deserialization error | Medium |
| Cross-project | IDOR on EventConfig ID | No | No filter | Data leak | High |

**5 critical gaps** — all require fixes before implementation.

### Worktree Parallelization Strategy

| Step | Modules touched | Depends on |
|------|----------------|------------|
| Tasks 1-3 (models + CRUD) | pipeline/, migrations/, tests/ | — |
| Tasks 4+5 (search + patterns) | pipeline/, nlp/ | Task 1 (models) |
| Task 6 (classifier) | pipeline/, predictors/ | Task 1 (models) |
| Task 7 (orchestrator) | pipeline/, jobs/, worker.py | Tasks 1-6 |
| Tasks 8-10 (infra) | pipeline/, jobs/ | Task 7 |
| Tasks 11-13 (frontend) | frontend/src/ | Backend APIs (Tasks 3,7,10) |

**Parallel lanes:**
- Lane A: Tasks 1-3 (models + CRUD) → Task 7 (orchestrator)
- Lane B: Tasks 4+5 (search + patterns) — can start after Task 1 merges
- Lane C: Task 6 (classifier) — can start after Task 1 merges
- Lane D: Tasks 11-13 (frontend) — can start after backend API contracts defined

**Execution:** Launch B + C in parallel after A completes Task 1. D can start with API stubs. Tasks 8-10 and 14-15 are sequential after Task 7.

**Conflict flags:** Lanes B and C both touch `pipeline/` — potential merge conflict on `__init__.py` and imports.

### Eng Completion Summary

| Metric | Value |
|--------|-------|
| Step 0: Scope Challenge | Scope accepted; duplication flagged for reuse |
| Architecture Review | 3 issues (1 high, 2 medium) |
| Code Quality Review | 6 issues (2 critical, 3 high, 1 medium) |
| Test Review | Diagram produced, 28 gaps identified |
| Performance Review | 2 issues (2 medium) |
| NOT in scope | 5 items deferred |
| What already exists | 7 reusable components mapped |
| TODOS.md updates | 3 items to propose |
| Failure modes | 5 critical gaps flagged |
| Outside voice | Claude subagent (Codex unavailable) |
| Parallelization | 4 lanes, 2 parallel / 2 sequential |
| Lake Score | 17/19 recommendations chose complete option |
| Codex available | No (CLI argument error) |

---

## TODOS.md Items (Deferred)

1. **Embedding search evaluation** — Evaluate vector similarity search as alternative to regex patterns for note matching. Could improve recall for clinician-described events. Blocked by: need baseline metrics from regex approach first.
2. **Direct-LLM mode for small cohorts** — Skip pattern generation, send all notes directly to LLM for cohorts < 100 patients. Good UX optimization but not blocking.
3. **Quick-start mode for common events** — Pre-configured EventConfig templates for VTE, MI, metastasis. Competitive moat but requires curated template library.
4. **Methods/reproducibility export** — Export pipeline config + metrics as a methods section for publications. Strong academic differentiator.
5. **Pattern quality eval suite** — Automated evaluation of LLM-generated patterns against known-positive notes. Needed for pattern generation confidence.
6. **Automatic orphaned-run recovery** — ARQ cron job with heartbeat + last_heartbeat column. Auto-transitions stalled tasks back to queued. Manual retry-stalled is sufficient for v1.

---

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR (via /autoplan) | 4 proposals accepted, 6 deferred |
| Codex Review | `/codex review` | Independent 2nd opinion | 0 | — | — |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 1 | ISSUES OPEN (via /autoplan) | 19 issues, 5 critical gaps |
| Design Review | `/plan-design-review` | UI/UX gaps | 1 | CLEAR (via /autoplan) | score: 3/10 → 7/10, 13 decisions |

**UNRESOLVED:** 0 unresolved decisions (all 44 decided, 4 taste decisions approved by user)
**VERDICT:** CEO + DESIGN CLEARED. ENG has 5 critical failure mode gaps that are addressed in the decision audit trail (savepoints, mutual exclusion, regex safety, SKIP LOCKED pattern, single-call-per-patient). Plan incorporates all fixes. Ready to implement.
