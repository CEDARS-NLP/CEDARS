# Unified Evaluation Session — Phase 5: Integration & Cleanup

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire up routing, sidebar navigation, and full pipeline execution. Clean up old pages that are replaced by the unified session.

**Architecture:** Update `App.tsx` routes, `AppSidebar.tsx` navigation, and the ARQ worker to handle evaluation session pipeline runs. Remove old pages and components that are replaced.

**Tech Stack:** React Router v6, ARQ worker, FastAPI

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Modify | `frontend/src/App.tsx` | Add routes for session list + session detail |
| Modify | `frontend/src/components/AppSidebar.tsx` | Update nav: replace Pipeline + Evaluation with single "Evaluation" link |
| Modify | `backend/app/worker.py` | Add eval session pipeline worker function |
| Modify | `backend/app/jobs/pipeline.py` | Adapt per-patient executor for PatientResult |
| Create | `backend/tests/test_eval_integration.py` | End-to-end integration test |

---

### Task 17: Frontend Routing & Navigation

**Files:**
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/AppSidebar.tsx`

- [ ] **Step 1: Update App.tsx routes**

In `frontend/src/App.tsx`:

Add imports at the top:
```tsx
import EvaluationListPage from "@/projects/evaluation/EvaluationListPage";
import EvaluationSessionPage from "@/projects/evaluation/EvaluationSessionPage";
```

Replace lines 98-101 (the pipeline and evaluation routes):
```tsx
                <Route path="pipeline" element={<EventConfigPage />} />
                <Route path="jobs" element={<JobDashboardPage />} />
                <Route path="annotations" element={<AnnotationsPage />} />
                <Route path="evaluation" element={<EvaluationPage />} />
```

With:
```tsx
                <Route path="pipeline" element={<EventConfigPage />} />
                <Route path="jobs" element={<JobDashboardPage />} />
                <Route path="annotations" element={<AnnotationsPage />} />
                <Route path="evaluation" element={<EvaluationListPage />} />
                <Route path="evaluation/:sessionId" element={<EvaluationSessionPage />} />
```

- [ ] **Step 2: Update sidebar navigation**

In `frontend/src/components/AppSidebar.tsx`, update the `projectNavSections` array (line 19):

Replace:
```tsx
const projectNavSections = [
  { label: "Overview", suffix: "", icon: LayoutDashboard, end: true },
  { label: "Data", suffix: "/data", icon: Database },
  { label: "Patients", suffix: "/patients", icon: Users },
  { label: "Pipeline", suffix: "/pipeline", icon: Workflow },
  { label: "Jobs", suffix: "/jobs", icon: Activity },
  { label: "Evaluation", suffix: "/evaluation", icon: BarChart3 },
  { label: "Annotations", suffix: "/annotations", icon: MessageSquareText },
  { label: "Export", suffix: "/export", icon: Download },
];
```

With:
```tsx
const projectNavSections = [
  { label: "Overview", suffix: "", icon: LayoutDashboard, end: true },
  { label: "Data", suffix: "/data", icon: Database },
  { label: "Patients", suffix: "/patients", icon: Users },
  { label: "Evaluation", suffix: "/evaluation", icon: BarChart3 },
  { label: "Jobs", suffix: "/jobs", icon: Activity },
  { label: "Annotations", suffix: "/annotations", icon: MessageSquareText },
  { label: "Export", suffix: "/export", icon: Download },
];
```

Note: "Pipeline" is removed. "Evaluation" moves up in the nav order since it's now the primary workflow entry point. The old `EventConfigPage` is still accessible at `/pipeline` for backwards compatibility but hidden from the nav.

- [ ] **Step 3: Run type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No errors

- [ ] **Step 4: Commit**

```bash
cd frontend
git add src/App.tsx src/components/AppSidebar.tsx
git commit -m "feat: update routes and sidebar for unified evaluation sessions

Add /evaluation/:sessionId route for session detail page.
Move Evaluation up in sidebar, remove Pipeline nav item.
Old pipeline page still accessible at /pipeline for backwards compat.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 18: ARQ Worker for Evaluation Pipeline

**Files:**
- Modify: `backend/app/worker.py`
- Modify: `backend/app/jobs/pipeline.py`

- [ ] **Step 1: Add eval pipeline worker function to worker.py**

In `backend/app/worker.py`, add a new job function. After the existing `run_pipeline_job` function, add:

```python
async def run_eval_pipeline_job(ctx: dict, run_id: str) -> dict:
    """Execute a full pipeline run for a committed evaluation session.

    Uses PatientResult rows instead of PatientTask. Reuses the same
    search + classify logic but stores results in the new schema.
    """
    from app.common.database import async_session
    from app.evaluation.models import EvaluationSession, PatientResult, PatientResultStatus
    from app.pipeline.models import PipelineRun, PipelineRunStatus
    from app.connectors.models import Note
    from app.nlp.engine import parse_query, process_note
    from app.pipeline.classifier import classify_patient
    from sqlalchemy import select
    from datetime import UTC, datetime
    import logging

    logger = logging.getLogger(__name__)

    async with async_session() as db:
        run = await db.get(PipelineRun, run_id)
        if not run:
            return {"error": "Run not found"}

        run.status = PipelineRunStatus.RUNNING
        run.started_at = datetime.now(UTC)
        db.add(run)
        await db.commit()

        config = run.config_snapshot or {}

        # Find the evaluation session linked to this run
        stmt = select(PatientResult.session_id).where(
            PatientResult.pipeline_run_id == run_id,
        ).limit(1)
        result = await db.execute(stmt)
        row = result.first()
        if not row:
            run.status = PipelineRunStatus.FAILED
            db.add(run)
            await db.commit()
            return {"error": "No PatientResult rows found"}

        session_id = row[0]
        eval_session = await db.get(EvaluationSession, session_id)
        if not eval_session:
            run.status = PipelineRunStatus.FAILED
            db.add(run)
            await db.commit()
            return {"error": "Evaluation session not found"}

        # Parse search queries from config
        search_queries = config.get("search_queries", [])
        include_queries = []
        exclude_queries = []
        for q in search_queries:
            query_str = q.get("query", "")
            if q.get("type") == "exclude":
                exclude_queries.append(query_str)
            else:
                include_queries.append(query_str)

        # Build classifier config
        class _Config:
            pass

        classifier_config = _Config()
        classifier_config.name = config.get("event_name", "")
        classifier_config.description = config.get("event_description", "")
        classifier_config.include_criteria = config.get("include_criteria", "")
        classifier_config.exclude_criteria = config.get("exclude_criteria", "")
        classifier_config.llm_provider = config.get("llm_provider", "")
        classifier_config.llm_model = config.get("llm_model", "")
        classifier_config.llm_api_base = config.get("llm_api_base")

        # Process queued patients
        processed = 0
        failed = 0

        while True:
            if run.is_cancelled:
                break

            # Pick next queued patient (SKIP LOCKED equivalent for SQLite compat)
            stmt = select(PatientResult).where(
                PatientResult.pipeline_run_id == run_id,
                PatientResult.status == PatientResultStatus.QUEUED,
            ).limit(1)
            result = await db.execute(stmt)
            pr = result.scalar_one_or_none()
            if not pr:
                break

            pr.status = PatientResultStatus.PROCESSING
            pr.started_at = datetime.now(UTC)
            db.add(pr)
            await db.commit()

            try:
                # Get patient notes
                stmt = select(Note).where(
                    Note.patient_id == pr.patient_id,
                    Note.text.isnot(None),
                ).order_by(Note.note_date)
                result = await db.execute(stmt)
                notes = list(result.scalars().all())

                pr.notes_searched = len(notes)

                # Run search queries on notes
                matched_notes = []
                for note in notes:
                    is_matched = False
                    for query_str in include_queries:
                        query_groups = parse_query(query_str)
                        sentences = process_note(note.text, query_groups)
                        if any(s.get("is_target") or s.get("matched_tokens") for s in sentences):
                            is_matched = True
                            break

                    # Check exclude queries
                    if is_matched:
                        for query_str in exclude_queries:
                            query_groups = parse_query(query_str)
                            sentences = process_note(note.text, query_groups)
                            if any(s.get("matched_tokens") for s in sentences):
                                is_matched = False
                                break

                    if is_matched:
                        matched_notes.append(note)

                pr.notes_matched = len(matched_notes)

                if not matched_notes:
                    pr.status = PatientResultStatus.NO_MATCH
                    pr.finding_label = "no_match"
                    pr.completed_at = datetime.now(UTC)
                else:
                    # Classify with LLM
                    excerpts = [
                        {
                            "note_id": n.id,
                            "text": n.text,
                            "note_date": str(n.note_date) if n.note_date else "unknown",
                        }
                        for n in matched_notes
                    ]
                    classification = await classify_patient(excerpts, classifier_config)

                    pr.finding_label = classification.label
                    pr.finding_reasoning = classification.reasoning
                    pr.finding_evidence = classification.evidence or []
                    pr.event_date = classification.event_date
                    pr.predicted_score = classification.confidence
                    pr.token_usage = classification.token_usage
                    pr.status = PatientResultStatus.COMPLETED
                    pr.completed_at = datetime.now(UTC)

                processed += 1

            except Exception as e:
                pr.status = PatientResultStatus.FAILED
                pr.error_message = str(e)
                pr.completed_at = datetime.now(UTC)
                failed += 1
                logger.warning("Eval pipeline failed for patient %s: %s", pr.patient_id, e)

            db.add(pr)

            # Update run progress
            run.processed_patients = processed + failed
            run.failed_patients = failed
            db.add(run)
            await db.commit()

            # Re-check cancellation
            await db.refresh(run)

        # Finalize
        if run.is_cancelled:
            run.status = PipelineRunStatus.CANCELLED
        else:
            run.status = PipelineRunStatus.COMPLETED
            # Update eval session status
            eval_session.status = "completed"
            db.add(eval_session)

        run.completed_at = datetime.now(UTC)
        db.add(run)
        await db.commit()

    return {"processed": processed, "failed": failed}
```

- [ ] **Step 2: Register the new job in the worker functions list**

In `backend/app/worker.py`, add `run_eval_pipeline_job` to the `functions` list in the `WorkerSettings` class:

```python
class WorkerSettings:
    functions = [
        ingest_file_job,
        run_nlp_job,
        run_predictions_job,
        run_pipeline_job,
        run_export_job,
        run_eval_pipeline_job,  # NEW
    ]
```

- [ ] **Step 3: Run existing tests to verify nothing breaks**

Run: `cd backend && uv run pytest -v -x --timeout=30`
Expected: All existing tests PASS

- [ ] **Step 4: Commit**

```bash
cd backend
git add app/worker.py app/jobs/pipeline.py
git commit -m "feat: add ARQ worker function for evaluation session pipeline runs

run_eval_pipeline_job processes PatientResult rows: runs search
queries, classifies with LLM, stores results. Supports cancellation.
Registered in WorkerSettings.functions.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 19: End-to-End Integration Test

**Files:**
- Create: `backend/tests/test_eval_integration.py`

- [ ] **Step 1: Write the integration test**

```python
# backend/tests/test_eval_integration.py
"""End-to-end integration test for the unified evaluation session workflow.

Tests the full flow: create session → update queries → execute search →
update LLM config → run LLM → review results → compute metrics → commit.
"""

import pytest
from unittest.mock import AsyncMock, patch

from httpx import ASGITransport, AsyncClient

from app.main import create_app
from app.pipeline.classifier import ClassificationResult


@pytest.fixture
def app():
    return create_app()


@pytest.fixture
async def auth_client(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/v1/auth/register", json={
            "email": "eval@test.com", "password": "testpass123", "name": "Eval Tester",
        })
        resp = await client.post("/api/v1/auth/login", json={
            "email": "eval@test.com", "password": "testpass123",
        })
        assert resp.status_code == 200
        yield client


@pytest.fixture
async def project_with_data(auth_client):
    """Create project and ingest some test data."""
    # Create project
    resp = await auth_client.post("/api/v1/projects", json={"name": "EvalTestProject"})
    assert resp.status_code == 201
    project_id = resp.json()["id"]

    # We'll use the service layer directly to seed patients + notes
    # since file upload + ingestion is complex for a unit test
    from app.common.database import async_session
    from app.connectors.models import Patient, Note

    async with async_session() as db:
        for i in range(5):
            p = Patient(
                id=f"eval-pat-{i}",
                project_id=project_id,
                patient_id_ext=f"EXT-{i}",
            )
            db.add(p)
            await db.flush()

            # First note has troponin mention
            n1 = Note(
                id=f"eval-note-{i}-0",
                project_id=project_id,
                patient_id=p.id,
                text_id=f"T{i}0",
                note_date="2024-01-15",
                text=f"Patient presents with troponin elevation at 2.4 ng/mL. ECG shows ST changes.",
            )
            # Second note is clean
            n2 = Note(
                id=f"eval-note-{i}-1",
                project_id=project_id,
                patient_id=p.id,
                text_id=f"T{i}1",
                note_date="2024-01-16",
                text="Follow-up visit. Patient stable. No acute complaints.",
            )
            db.add_all([n1, n2])
        await db.commit()

    return project_id


class TestUnifiedEvalSessionWorkflow:
    """Tests the full evaluation session workflow end-to-end."""

    async def test_full_workflow(self, auth_client, project_with_data):
        pid = project_with_data
        base = f"/api/v1/projects/{pid}/evaluation"

        # 1. Create session
        resp = await auth_client.post(f"{base}/sessions", json={
            "search_queries": [{"query": "troponin", "type": "include"}],
        })
        assert resp.status_code == 201
        session = resp.json()
        sid = session["id"]
        assert session["status"] == "draft"
        assert session["sample_size"] >= 5

        # 2. Get funnel stats (before search execution)
        resp = await auth_client.get(f"{base}/sessions/{sid}/funnel")
        assert resp.status_code == 200
        funnel = resp.json()
        assert funnel["sample_patients"] == 5

        # 3. Execute search queries
        resp = await auth_client.post(f"{base}/sessions/{sid}/queries/execute")
        assert resp.status_code == 200
        funnel = resp.json()
        assert funnel["matched_patients"] > 0

        # 4. Get query matches (note preview)
        resp = await auth_client.get(f"{base}/sessions/{sid}/queries/0/matches")
        assert resp.status_code == 200
        matches = resp.json()
        assert matches["total_notes"] > 0
        assert len(matches["notes"]) > 0

        # 5. Update LLM config
        resp = await auth_client.put(f"{base}/sessions/{sid}/llm-config", json={
            "event_name": "Myocardial Infarction",
            "event_description": "Confirmed MI with troponin elevation",
            "include_criteria": "Troponin elevation, ECG changes",
            "exclude_criteria": "Rule-out, family history only",
            "llm_provider": "openai",
            "llm_model": "gpt-4o-mini",
        })
        assert resp.status_code == 200
        assert resp.json()["event_name"] == "Myocardial Infarction"

        # 6. Run LLM classification (mocked)
        mock_result = ClassificationResult(
            label="positive",
            confidence=0.92,
            reasoning="Troponin elevated at 2.4 ng/mL with ECG changes",
            event_date="2024-01-15",
            evidence=[{
                "note_id": "eval-note-0-0",
                "text": "troponin elevation at 2.4 ng/mL",
                "note_date": "2024-01-15",
            }],
            token_usage={"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250},
        )
        with patch("app.evaluation.service.classify_patient", new_callable=AsyncMock, return_value=mock_result):
            resp = await auth_client.post(f"{base}/sessions/{sid}/run-llm")
        assert resp.status_code == 200
        run_stats = resp.json()
        assert run_stats["patients_classified"] > 0

        # 7. Session should now be REVIEWING
        resp = await auth_client.get(f"{base}/sessions/{sid}")
        assert resp.json()["status"] == "reviewing"

        # 8. List results
        resp = await auth_client.get(f"{base}/sessions/{sid}/results")
        assert resp.status_code == 200
        results = resp.json()
        assert results["total"] > 0

        # 9. Submit judgment on first positive result
        positive_results = [r for r in results["results"] if r["finding_label"] == "positive"]
        assert len(positive_results) > 0

        result_id = positive_results[0]["id"]
        resp = await auth_client.post(f"{base}/sessions/{sid}/results/{result_id}/judge", json={
            "judgment": "correct",
            "event_date_override": "2024-01-15",
        })
        assert resp.status_code == 200

        # 10. Check metrics
        resp = await auth_client.get(f"{base}/sessions/{sid}/metrics")
        assert resp.status_code == 200
        metrics = resp.json()
        assert metrics["total_reviewed"] >= 1

        # 11. Commit (mocked pipeline dispatch)
        with patch("app.evaluation.service.dispatch_full_pipeline_run", new_callable=AsyncMock) as mock_dispatch:
            from app.pipeline.models import PipelineRun, PipelineRunStatus

            mock_run = PipelineRun(
                id="mock-run-id",
                project_id=pid,
                run_type="full",
                status=PipelineRunStatus.QUEUED,
                total_patients=5,
                created_by="user-1",
            )
            mock_dispatch.return_value = mock_run

            resp = await auth_client.post(f"{base}/sessions/{sid}/commit")
            assert resp.status_code == 200
            commit_data = resp.json()
            assert commit_data["pipeline_run_id"] == "mock-run-id"

        # 12. Session should be COMMITTED
        resp = await auth_client.get(f"{base}/sessions/{sid}")
        assert resp.json()["status"] == "committed"

        # 13. Cannot create new session while committed
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 400

    async def test_discard_and_create_new(self, auth_client, project_with_data):
        """Test that discarding a session allows creating a new one."""
        pid = project_with_data
        base = f"/api/v1/projects/{pid}/evaluation"

        # Create first session
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 201
        sid1 = resp.json()["id"]

        # Can't create another while active
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 400

        # Discard first
        resp = await auth_client.delete(f"{base}/sessions/{sid1}")
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

        # Now can create new
        resp = await auth_client.post(f"{base}/sessions", json={"search_queries": []})
        assert resp.status_code == 201
        assert resp.json()["id"] != sid1
```

- [ ] **Step 2: Run integration test**

Run: `cd backend && uv run pytest tests/test_eval_integration.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
cd backend
git add tests/test_eval_integration.py
git commit -m "test: add end-to-end integration test for unified evaluation session

Tests full workflow: create → search → LLM → review → metrics → commit.
Also tests discard + create new session flow.

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```

---

### Task 20: Cleanup — Remove Old Pages (Optional)

This task is optional and can be deferred. The old pages still work but are no longer linked from navigation.

**Files to eventually remove:**
- `frontend/src/projects/EvaluationPage.tsx` — replaced by `EvaluationListPage.tsx`
- `frontend/src/projects/evaluation/ValidatedPredictorsSection.tsx` — concept removed
- `frontend/src/projects/PipelinePage.tsx` — read-only overview, no longer needed

**Files to eventually rewrite (not in this phase):**
- `frontend/src/projects/EventConfigPage.tsx` — still accessible at `/pipeline`, can be removed once all users migrate to evaluation sessions

- [ ] **Step 1: Verify the new evaluation workflow works end-to-end**

Run the frontend dev server and manually test:
1. Navigate to Evaluation in the sidebar
2. Create a new session
3. Add search queries and run search
4. Expand a query to see note preview with highlights
5. Configure LLM and run
6. Review patient results
7. Check metrics update live
8. Commit

Run: `cd frontend && npm run dev`

- [ ] **Step 2: (Optional) Remove old files and update imports**

Only do this after confirming the new workflow is working.

```bash
# Remove old evaluation page wrapper
rm frontend/src/projects/EvaluationPage.tsx
rm frontend/src/projects/evaluation/ValidatedPredictorsSection.tsx
rm frontend/src/projects/PipelinePage.tsx

# Update App.tsx to remove old EvaluationPage import if removed
```

- [ ] **Step 3: Commit if cleanup was done**

```bash
git add -A
git commit -m "chore: remove old evaluation and pipeline pages replaced by unified session

Co-Authored-By: Claude Opus 4.6 <noreply@anthropic.com>"
```
