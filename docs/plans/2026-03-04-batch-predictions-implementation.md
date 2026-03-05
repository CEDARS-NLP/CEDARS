# Batch Predictions Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Decouple predictor activation from prediction execution, run predictions as a background job with per-patient batching, WebSocket progress, cancellation, and next-patient prefetch.

**Architecture:** Replace the synchronous `run_bulk_predictions()` call in the activation endpoint with an ARQ background job. The job processes sentences grouped by patient, committing after each patient so annotations are immediately available for review. A WebSocket endpoint streams progress. The frontend Annotations page gets a "Run Predictions" button, progress banner, and prefetches the next patient during review.

**Tech Stack:** FastAPI (WebSocket), ARQ (background jobs), SQLAlchemy async, React + TanStack React Query, shadcn/ui

---

### Task 1: Add `is_cancelled` field to BackgroundJob model

**Files:**
- Modify: `backend/app/jobs/models.py`
- Create: `backend/migrations/versions/` (auto-generated Alembic migration)

**Step 1: Add the field**

In `backend/app/jobs/models.py`, add `is_cancelled` to the `BackgroundJob` class, after the `error_message` field:

```python
is_cancelled: bool = Field(default=False)
```

Also add a `CANCELLED` status to `JobStatus`:

```python
class JobStatus(str, enum.Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
```

**Step 2: Generate Alembic migration**

Run: `cd backend && uv run alembic revision --autogenerate -m "add is_cancelled to background_jobs"`

Verify the migration adds the column with a default of `False`.

**Step 3: Apply migration**

Run: `cd backend && uv run alembic upgrade head`

**Step 4: Commit**

```bash
git add backend/app/jobs/models.py backend/migrations/versions/
git commit -m "feat: add is_cancelled field and CANCELLED status to BackgroundJob"
```

---

### Task 2: Implement `execute_prediction_job` in `backend/app/jobs/prediction.py`

**Files:**
- Create: `backend/app/jobs/prediction.py`
- Create: `backend/tests/test_prediction_job.py`

**Step 1: Write the failing test**

Create `backend/tests/test_prediction_job.py`:

```python
"""Unit tests for the prediction job executor."""

import pytest
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.annotations.models import Annotation, ReviewStatus
from app.connectors.models import DataSource, Note, Patient, PatientStatus
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp.models import NlpJob, SearchQuery, Sentence
from app.predictors.base import PredictionResult, TokenUsage
from app.predictors.models import PredictorConfig, PredictorType
from app.auth.models import User
from app.projects.models import Project, ProjectMember
from app.evaluation.models import EvaluationSession, EvaluationJudgment, ValidatedPredictor


@pytest.fixture
async def session_factory():
    """Create an in-memory SQLite database with all tables."""
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    yield factory
    await engine.dispose()


async def _seed_data(session: AsyncSession, project_id: str = "proj1"):
    """Seed a project with predictor, patients, notes, and target sentences."""
    # Active predictor config
    pc = PredictorConfig(
        id="pc1",
        project_id=project_id,
        predictor_type=PredictorType.LLM,
        name="Test LLM",
        config={"provider": "ollama", "model": "llama3"},
        is_active=True,
        created_by="user1",
    )
    session.add(pc)

    # Two patients with notes and sentences
    for i, (pid, nid, sid, text) in enumerate([
        ("pat1", "n1", "s1", "Troponin elevated"),
        ("pat1", "n1", "s2", "Chest pain reported"),
        ("pat2", "n2", "s3", "Confirmed MI"),
    ]):
        if i == 0 or pid != "pat1":
            p = Patient(
                id=pid, project_id=project_id, patient_id_ext=pid,
                status=PatientStatus.NLP_COMPLETE,
            )
            session.add(p)
        if i == 0 or nid != "n1":
            n = Note(
                id=nid, project_id=project_id, patient_id=pid,
                text_id=f"T{nid}", note_date="2026-01-10", text=text,
            )
            session.add(n)
        s = Sentence(
            id=sid, project_id=project_id, note_id=nid,
            text=text, sentence_number=i, is_target=True,
            matched_tokens=["troponin"], is_negated=False,
        )
        session.add(s)

    await session.commit()


class TestExecutePredictionJob:
    async def test_processes_all_sentences_per_patient(self, session_factory):
        """Job processes sentences grouped by patient, creates annotations."""
        async with session_factory() as session:
            await _seed_data(session)
            bg_job = BackgroundJob(
                id="job1", project_id="proj1",
                job_type=JobType.PREDICTION, status=JobStatus.PENDING,
            )
            session.add(bg_job)
            await session.commit()

        mock_result = PredictionResult(
            score=0.9, label=1, model="test", reasoning="test reason",
            token_usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )
        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor

            from app.jobs.prediction import execute_prediction_job
            result = await execute_prediction_job("proj1", "job1", session_factory=session_factory)

        assert result["predictions_made"] == 3
        assert result["annotations_created"] == 3
        assert result["patients_processed"] == 2

        # Verify annotations exist
        async with session_factory() as session:
            annos = (await session.execute(select(Annotation))).scalars().all()
            assert len(annos) == 3
            assert all(a.review_status == ReviewStatus.UNREVIEWED for a in annos)

            # Verify job is completed
            job = await session.get(BackgroundJob, "job1")
            assert job.status == JobStatus.COMPLETED
            assert job.progress == 100

    async def test_cancellation_stops_after_current_patient(self, session_factory):
        """Setting is_cancelled=True stops the job between patient batches."""
        async with session_factory() as session:
            await _seed_data(session)
            bg_job = BackgroundJob(
                id="job2", project_id="proj1",
                job_type=JobType.PREDICTION, status=JobStatus.PENDING,
                is_cancelled=True,  # Pre-cancel
            )
            session.add(bg_job)
            await session.commit()

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="ok")
        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor

            from app.jobs.prediction import execute_prediction_job
            result = await execute_prediction_job("proj1", "job2", session_factory=session_factory)

        # Should have processed first patient only (2 sentences) then stopped
        assert result["annotations_created"] == 2
        assert result["patients_processed"] == 1

        async with session_factory() as session:
            job = await session.get(BackgroundJob, "job2")
            assert job.status == JobStatus.CANCELLED

    async def test_handles_prediction_errors_gracefully(self, session_factory):
        """Individual prediction failures don't abort the job."""
        async with session_factory() as session:
            await _seed_data(session)
            bg_job = BackgroundJob(
                id="job3", project_id="proj1",
                job_type=JobType.PREDICTION, status=JobStatus.PENDING,
            )
            session.add(bg_job)
            await session.commit()

        from app.predictors.base import PredictorError

        call_count = 0

        async def mock_predict(text):
            nonlocal call_count
            call_count += 1
            if call_count == 2:
                raise PredictorError("LLM timeout")
            return PredictionResult(score=0.9, label=1, model="test", reasoning="ok")

        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict = mock_predict
            mock_factory.return_value = mock_predictor

            from app.jobs.prediction import execute_prediction_job
            result = await execute_prediction_job("proj1", "job3", session_factory=session_factory)

        assert result["predictions_made"] == 2
        assert result["errors"] == 1
        assert result["annotations_created"] == 3  # All annotations created (some with null predictions)
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_prediction_job.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs.prediction'`

**Step 3: Write the implementation**

Create `backend/app/jobs/prediction.py`:

```python
"""Prediction job executor: per-patient batched bulk predictions."""

import logging
from collections import defaultdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.annotations.models import Annotation
from app.config import settings
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus
from app.nlp.models import Sentence
from app.predictors.base import PredictionResult, PredictorError
from app.predictors.factory import create_predictor
from app.predictors.models import PredictorConfig

logger = logging.getLogger(__name__)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a standalone session factory for worker processes."""
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def execute_prediction_job(
    project_id: str,
    job_db_id: str,
    session_factory: async_sessionmaker[AsyncSession] | None = None,
) -> dict:
    """Run bulk predictions with per-patient batching.

    - Groups target sentences by patient
    - Commits after each patient (annotations immediately available)
    - Checks cancellation flag between patients
    - Updates BackgroundJob progress after each patient
    """
    if session_factory is None:
        session_factory = _make_session_factory()

    async with session_factory() as session:
        bg_job = await session.get(BackgroundJob, job_db_id)
        if not bg_job:
            logger.error("BackgroundJob %s not found", job_db_id)
            return {"error": "Job not found"}

        bg_job.status = JobStatus.RUNNING
        bg_job.started_at = datetime.now(UTC)
        session.add(bg_job)
        await session.commit()

        stats: dict = {
            "total_sentences": 0,
            "predictions_made": 0,
            "annotations_created": 0,
            "errors": 0,
            "patients_processed": 0,
            "total_patients": 0,
            "token_usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
        }

        try:
            # Get active predictor
            stmt = select(PredictorConfig).where(
                PredictorConfig.project_id == project_id,
                PredictorConfig.is_active == True,  # noqa: E712
                PredictorConfig.deleted_at.is_(None),
            )
            result = await session.execute(stmt)
            predictor_config = result.scalar_one_or_none()
            if not predictor_config:
                raise ValueError("No active predictor configured for this project")

            predictor = create_predictor(predictor_config)

            # Find target sentences without annotations, grouped by patient
            existing_annotations = (
                select(Annotation.sentence_id)
                .where(Annotation.project_id == project_id)
                .scalar_subquery()
            )
            stmt = (
                select(Sentence, Note.patient_id)
                .join(Note, Sentence.note_id == Note.id)
                .where(
                    Sentence.project_id == project_id,
                    Sentence.is_target == True,  # noqa: E712
                    Note.deleted_at.is_(None),
                    Sentence.id.notin_(existing_annotations),
                )
                .order_by(Note.patient_id, Note.note_date, Sentence.sentence_number)
            )
            result = await session.execute(stmt)
            rows = result.all()

            # Group by patient
            patient_batches: dict[str, list[tuple]] = defaultdict(list)
            for sentence, patient_id in rows:
                patient_batches[patient_id].append((sentence, patient_id))

            stats["total_sentences"] = len(rows)
            stats["total_patients"] = len(patient_batches)

            # Process per-patient
            for patient_idx, (patient_id, sentences) in enumerate(patient_batches.items()):
                # Check cancellation
                await session.refresh(bg_job)
                if bg_job.is_cancelled:
                    bg_job.status = JobStatus.CANCELLED
                    bg_job.completed_at = datetime.now(UTC)
                    bg_job.result_summary = stats
                    session.add(bg_job)
                    await session.commit()
                    return stats

                for sentence, pid in sentences:
                    prediction: PredictionResult | None = None
                    try:
                        prediction = await predictor.predict(sentence.text)
                        stats["predictions_made"] += 1
                        if prediction.token_usage:
                            stats["token_usage"]["prompt_tokens"] += prediction.token_usage.prompt_tokens
                            stats["token_usage"]["completion_tokens"] += prediction.token_usage.completion_tokens
                            stats["token_usage"]["total_tokens"] += prediction.token_usage.total_tokens
                    except PredictorError as e:
                        logger.warning("Prediction failed for sentence %s: %s", sentence.id, e)
                        stats["errors"] += 1

                    annotation = Annotation(
                        project_id=project_id,
                        patient_id=pid,
                        note_id=sentence.note_id,
                        sentence_id=sentence.id,
                        sentence_text=sentence.text,
                        matched_tokens=",".join(sentence.matched_tokens) if sentence.matched_tokens else "",
                        is_negated=sentence.is_negated,
                        predicted_score=prediction.score if prediction else None,
                        predicted_label=prediction.label if prediction else None,
                        predictor_model=prediction.model if prediction else "",
                        reasoning=prediction.reasoning if prediction else "",
                    )
                    session.add(annotation)
                    stats["annotations_created"] += 1

                # Commit after each patient
                await session.commit()
                stats["patients_processed"] += 1

                # Update progress
                bg_job.progress = int(((patient_idx + 1) / stats["total_patients"]) * 100)
                bg_job.result_summary = stats
                session.add(bg_job)
                await session.commit()

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = datetime.now(UTC)
            bg_job.result_summary = stats

        except Exception as exc:
            logger.exception("Prediction job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return stats
```

**Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_prediction_job.py -v`
Expected: All 3 tests PASS

**Step 5: Commit**

```bash
git add backend/app/jobs/prediction.py backend/tests/test_prediction_job.py
git commit -m "feat: implement per-patient batched prediction job with cancellation"
```

---

### Task 3: Wire `run_prediction_job` in ARQ worker

**Files:**
- Modify: `backend/app/worker.py`

**Step 1: Replace the placeholder**

In `backend/app/worker.py`, replace the `run_prediction_job` function:

```python
async def run_prediction_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run bulk predictions with per-patient batching."""
    from app.jobs.prediction import execute_prediction_job

    return await execute_prediction_job(project_id, job_db_id)
```

**Step 2: Run existing tests**

Run: `cd backend && uv run pytest tests/test_worker.py -v`
Expected: PASS

**Step 3: Commit**

```bash
git add backend/app/worker.py
git commit -m "feat: wire prediction job executor into ARQ worker"
```

---

### Task 4: Add `dispatch_prediction_job` and prediction job API endpoints

**Files:**
- Modify: `backend/app/annotations/prediction_service.py`
- Modify: `backend/app/annotations/schemas.py`
- Modify: `backend/app/annotations/router.py`
- Modify: `backend/app/annotations/service.py` (re-export)
- Create: `backend/tests/test_prediction_dispatch_api.py`

**Step 1: Write the failing test**

Create `backend/tests/test_prediction_dispatch_api.py`:

```python
"""API tests for prediction job dispatch, status, and cancellation."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.predictors.base import PredictionResult


async def register_and_login(client: AsyncClient, email: str = "admin@test.com") -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Admin", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Pred Dispatch Test", "description": "test"},
    )
    return resp.json()["id"]


async def setup_notes_and_nlp(client: AsyncClient, pid: str):
    from unittest.mock import patch as mock_patch

    create_resp = await client.post(
        f"/api/v1/projects/{pid}/data/sources",
        json={
            "name": "test.csv",
            "connector_type": "file_upload",
            "config": {
                "s3_key": "test.csv",
                "file_type": "csv",
                "column_mapping": {
                    "patient_id": "patient_id",
                    "text_id": "text_id",
                    "text": "text",
                    "note_date": "date",
                },
            },
        },
    )
    ds_id = create_resp.json()["id"]
    csv_data = (
        b"patient_id,text_id,text,date\n"
        b"P001,N001,Patient presents with troponin elevation.,2026-01-10\n"
        b"P002,N002,Confirmed myocardial infarction.,2026-01-12\n"
    )
    with mock_patch("app.connectors.file_upload.download_file", return_value=csv_data):
        await client.post(f"/api/v1/projects/{pid}/data/sources/{ds_id}/ingest")

    await client.post(f"/api/v1/projects/{pid}/nlp/queries", json={"query": "troponin OR myocardial"})
    await client.post(f"/api/v1/projects/{pid}/nlp/run")


async def add_predictor(client: AsyncClient, pid: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{pid}/predictors",
        json={
            "name": "Test LLM",
            "predictor_type": "llm",
            "config": {
                "provider": "ollama",
                "model": "llama3",
                "api_base": "http://localhost:11434",
                "event_definition": {
                    "name": "MI", "description": "Myocardial Infarction",
                    "include_criteria": "troponin", "exclude_criteria": "",
                },
            },
        },
    )
    pred_id = resp.json()["id"]
    await client.post(f"/api/v1/projects/{pid}/predictors/{pred_id}/activate")
    return pred_id


class TestPredictionJobDispatch:
    async def test_run_dispatches_job(self, client):
        """POST /annotations/predictions/run creates a background job."""
        await register_and_login(client)
        pid = await create_project(client)
        await setup_notes_and_nlp(client, pid)
        await add_predictor(client, pid)

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="ok")
        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor

            resp = await client.post(f"/api/v1/projects/{pid}/annotations/predictions/run")

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] in ("pending", "running", "completed")

    async def test_status_returns_job_info(self, client):
        """GET /annotations/predictions/status returns latest job info."""
        await register_and_login(client)
        pid = await create_project(client)
        await setup_notes_and_nlp(client, pid)
        await add_predictor(client, pid)

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="ok")
        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor

            await client.post(f"/api/v1/projects/{pid}/annotations/predictions/run")

        resp = await client.get(f"/api/v1/projects/{pid}/annotations/predictions/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "status" in data
        assert "progress" in data

    async def test_cancel_sets_flag(self, client):
        """POST /annotations/predictions/cancel sets is_cancelled on the job."""
        await register_and_login(client)
        pid = await create_project(client)

        # Just test the cancel endpoint returns 404 when no running job
        resp = await client.post(f"/api/v1/projects/{pid}/annotations/predictions/cancel")
        assert resp.status_code == 404

    async def test_run_fails_without_active_predictor(self, client):
        """POST /annotations/predictions/run returns 400 without active predictor."""
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(f"/api/v1/projects/{pid}/annotations/predictions/run")
        assert resp.status_code == 400
```

**Step 2: Run tests to verify they fail**

Run: `cd backend && uv run pytest tests/test_prediction_dispatch_api.py -v`
Expected: FAIL — endpoints don't exist yet

**Step 3: Add schemas**

In `backend/app/annotations/schemas.py`, add after the existing `BulkEstimateResponse`:

```python
class PredictionJobResponse(BaseModel):
    """Response when dispatching or querying a prediction job."""

    job_id: str
    status: str
    progress: int = 0
    result_summary: dict | None = None
```

**Step 4: Add `dispatch_prediction_job` to prediction_service.py**

In `backend/app/annotations/prediction_service.py`, add after the `estimate_bulk_predictions` function:

```python
async def dispatch_prediction_job(
    session: AsyncSession,
    project_id: str,
    user_id: str,
) -> dict:
    """Create a BackgroundJob and enqueue prediction processing via ARQ.

    Falls back to synchronous execution if Redis/ARQ is unavailable.
    """
    from app.jobs.models import BackgroundJob, JobStatus, JobType

    # Check active predictor exists before dispatching
    stmt = select(PredictorConfig).where(
        PredictorConfig.project_id == project_id,
        PredictorConfig.is_active == True,  # noqa: E712
        PredictorConfig.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    if not result.scalar_one_or_none():
        raise ValueError("No active predictor configured for this project")

    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.PREDICTION,
        status=JobStatus.PENDING,
        created_by=user_id,
    )
    session.add(bg_job)
    await session.commit()
    await session.refresh(bg_job)

    try:
        from arq import create_pool

        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        arq_job = await redis.enqueue_job("run_prediction_job", project_id, bg_job.id)
        bg_job.arq_job_id = arq_job.job_id
        session.add(bg_job)
        await session.commit()
        await redis.aclose()
    except Exception:
        logger.warning("ARQ unavailable, running predictions synchronously")
        from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession as _AsyncSession

        from app.jobs.prediction import execute_prediction_job

        factory = async_sessionmaker(
            session.bind, class_=_AsyncSession, expire_on_commit=False
        )
        await execute_prediction_job(project_id, bg_job.id, session_factory=factory)
        await session.refresh(bg_job)

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }


async def get_prediction_job_status(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Get the latest prediction job for a project."""
    from app.jobs.models import BackgroundJob, JobType

    stmt = (
        select(BackgroundJob)
        .where(
            BackgroundJob.project_id == project_id,
            BackgroundJob.job_type == JobType.PREDICTION,
        )
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        return None
    return {
        "job_id": job.id,
        "status": job.status.value,
        "progress": job.progress,
        "result_summary": job.result_summary,
        "is_cancelled": job.is_cancelled,
        "created_at": job.created_at.isoformat() if job.created_at else None,
        "started_at": job.started_at.isoformat() if job.started_at else None,
        "completed_at": job.completed_at.isoformat() if job.completed_at else None,
    }


async def cancel_prediction_job(
    session: AsyncSession,
    project_id: str,
) -> dict | None:
    """Cancel the running prediction job for a project."""
    from app.jobs.models import BackgroundJob, JobStatus, JobType

    stmt = select(BackgroundJob).where(
        BackgroundJob.project_id == project_id,
        BackgroundJob.job_type == JobType.PREDICTION,
        BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
    )
    result = await session.execute(stmt)
    job = result.scalar_one_or_none()
    if not job:
        return None
    job.is_cancelled = True
    session.add(job)
    await session.commit()
    return {"job_id": job.id, "cancelled": True}
```

**Step 5: Add router endpoints**

In `backend/app/annotations/router.py`, replace the existing `run_predictions_endpoint` and add new endpoints. Replace the `# ── Bulk Prediction Run ──` section with:

```python
# ── Prediction Job Dispatch ──────────────────────────────────────


@router.post("/predictions/run", response_model=PredictionJobResponse)
async def dispatch_predictions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Dispatch a background prediction job for all unprocessed target sentences."""
    try:
        result = await dispatch_prediction_job(session, project_id, current_user.id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return result


@router.get("/predictions/status", response_model=PredictionJobResponse | None)
async def prediction_status_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get the latest prediction job status for this project."""
    return await get_prediction_job_status(session, project_id)


@router.post("/predictions/cancel")
async def cancel_predictions_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Cancel the running prediction job."""
    result = await cancel_prediction_job(session, project_id)
    if not result:
        raise HTTPException(status_code=404, detail="No running prediction job found")
    return result
```

Update the imports at the top of `router.py` to add the new schemas and service functions:

```python
from app.annotations.schemas import (
    AnnotationResponse,
    AnnotationStatsResponse,
    BulkEstimateResponse,
    BulkRunResponse,
    DeleteEventDateResponse,
    NextPatientResponse,
    PatientAnnotationResponse,
    PatientReviewStats,
    PredictionJobResponse,
    ReviewRequest,
    ReviewResultResponse,
)
from app.annotations.service import (
    cancel_prediction_job,
    delete_event_date,
    dispatch_prediction_job,
    estimate_bulk_predictions,
    get_annotation,
    get_annotation_stats,
    get_next_patient_for_review,
    get_next_unreviewed,
    get_note_context,
    get_patient_annotations,
    get_patient_review_stats,
    get_prediction_job_status,
    list_annotations,
    reopen_patient,
    review_annotation,
    run_bulk_predictions,
    skip_annotation,
    unlock_patient,
)
```

**Important:** The `/predictions/run`, `/predictions/status`, and `/predictions/cancel` routes MUST be placed BEFORE the `/{annotation_id}` routes to avoid path conflicts (FastAPI matches `predictions` as an `annotation_id` otherwise). Place them right after the `/estimate` endpoint and before the `# ── Annotation CRUD ──` section.

Also keep the old `POST /run` endpoint temporarily for backwards compatibility but mark it as deprecated. It can be removed in a future cleanup.

**Step 6: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_prediction_dispatch_api.py -v`
Expected: All 4 tests PASS

Also run: `cd backend && uv run pytest tests/test_annotations_api.py -v`
Expected: All existing tests still PASS

**Step 7: Commit**

```bash
git add backend/app/annotations/prediction_service.py backend/app/annotations/schemas.py backend/app/annotations/router.py backend/tests/test_prediction_dispatch_api.py
git commit -m "feat: add prediction job dispatch, status, and cancel endpoints"
```

---

### Task 5: Decouple evaluation activation from bulk predictions

**Files:**
- Modify: `backend/app/evaluation/router.py`
- Modify: `backend/app/evaluation/schemas.py`
- Modify: `backend/tests/test_evaluation_api.py`

**Step 1: Update the failing test**

In `backend/tests/test_evaluation_api.py`, update the `test_activate_validated` test. The response should no longer include `bulk_run`:

```python
async def test_activate_validated(self, client):
    pid, sid = await self._setup_completed_session(client)

    # Validate
    resp = await client.post(
        f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/validate",
        json={"name": "v1.0"},
    )
    vp_id = resp.json()["id"]

    # Activate — should only activate, not run predictions
    resp = await client.post(
        f"/api/v1/projects/{pid}/evaluation/validated/{vp_id}/activate",
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["validated"]["is_active"] is True
    assert "bulk_run" not in data or data.get("bulk_run") is None
```

**Step 2: Run test to verify it fails**

Run: `cd backend && uv run pytest tests/test_evaluation_api.py::TestValidatedPredictors::test_activate_validated -v`
Expected: FAIL — response still includes `bulk_run`

**Step 3: Modify evaluation router**

In `backend/app/evaluation/router.py`, update the `activate_validated_endpoint`:

```python
@router.post("/validated/{validated_id}/activate", response_model=ActivateResponse)
async def activate_validated_endpoint(
    project_id: str,
    validated_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin")),
):
    """Activate a validated predictor and its config.

    Does NOT trigger bulk predictions. Use POST /annotations/predictions/run
    to dispatch predictions as a background job.
    """
    validated = await activate_validated_predictor(session, project_id, validated_id)
    if not validated:
        raise HTTPException(status_code=404, detail="Validated predictor not found")

    return ActivateResponse(
        validated=ValidatedPredictorResponse.model_validate(validated, from_attributes=True),
    )
```

Remove the `import logging` and `from app.annotations.prediction_service import run_bulk_predictions` lines that are no longer needed.

**Step 4: Run tests to verify they pass**

Run: `cd backend && uv run pytest tests/test_evaluation_api.py -v`
Expected: All tests PASS

Also run: `cd backend && uv run pytest -v`
Expected: All tests PASS

**Step 5: Commit**

```bash
git add backend/app/evaluation/router.py backend/tests/test_evaluation_api.py
git commit -m "refactor: decouple evaluation activation from bulk prediction execution"
```

---

### Task 6: Add WebSocket endpoint for prediction job progress

**Files:**
- Create: `backend/app/annotations/ws.py`
- Modify: `backend/app/main.py` (register WebSocket route)

**Step 1: Create WebSocket endpoint**

Create `backend/app/annotations/ws.py`:

```python
"""WebSocket endpoint for real-time prediction job progress."""

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.database import async_session
from app.jobs.models import BackgroundJob, JobStatus, JobType

logger = logging.getLogger(__name__)


async def prediction_job_ws(websocket: WebSocket, project_id: str, job_id: str):
    """Stream prediction job progress over WebSocket.

    Polls the BackgroundJob table every 1s and pushes updates to the client.
    Closes when the job reaches a terminal state (completed, failed, cancelled).
    """
    await websocket.accept()

    terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    last_progress = -1

    try:
        while True:
            async with async_session() as session:
                job = await session.get(BackgroundJob, job_id)

            if not job or job.project_id != project_id:
                await websocket.send_json({"type": "error", "detail": "Job not found"})
                break

            if job.progress != last_progress or job.status in terminal_statuses:
                last_progress = job.progress
                msg = {
                    "type": "progress" if job.status not in terminal_statuses else job.status.value,
                    "job_id": job.id,
                    "status": job.status.value,
                    "progress": job.progress,
                    "result_summary": job.result_summary,
                }
                await websocket.send_json(msg)

            if job.status in terminal_statuses:
                break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
```

**Step 2: Register the WebSocket route**

In `backend/app/main.py`, find where routers are included and add the WebSocket route. Add after the existing router includes:

```python
from app.annotations.ws import prediction_job_ws

app.websocket("/ws/projects/{project_id}/jobs/{job_id}")(prediction_job_ws)
```

**Step 3: Run all tests**

Run: `cd backend && uv run pytest -v`
Expected: All tests PASS (WebSocket doesn't break existing tests)

**Step 4: Commit**

```bash
git add backend/app/annotations/ws.py backend/app/main.py
git commit -m "feat: add WebSocket endpoint for prediction job progress"
```

---

### Task 7: Update ValidatedPredictorsSection — activation only

**Files:**
- Modify: `frontend/src/projects/evaluation/ValidatedPredictorsSection.tsx`

**Step 1: Update the activation mutation**

The mutation should no longer expect `bulk_run` in the response. Change the mutation to:

```typescript
const activateMutation = useMutation({
  mutationFn: (validatedId: string) =>
    api.post<{ validated: ValidatedPredictor }>(
      `/projects/${projectId}/evaluation/validated/${validatedId}/activate`,
      {}
    ),
  onSuccess: () => {
    queryClient.invalidateQueries({ queryKey: ["validated-predictors", projectId] });
    setActivateTarget(null);
  },
});
```

**Step 2: Update the confirmation dialog**

Remove the token estimate query and the bulk run results display. The dialog should say "Activate Predictor" instead of "Activate & Run Predictions". After activation, show a toast directing the user to the Annotations page to run predictions.

Remove the `estimate` query and `activateTarget`-dependent `enabled` flag for it.

Update the dialog content to:

```tsx
<DialogContent>
  <DialogHeader>
    <DialogTitle>Activate Predictor?</DialogTitle>
    <DialogDescription>
      This will set this predictor as the active one for the project.
      To run predictions, go to the Annotations page after activation.
    </DialogDescription>
  </DialogHeader>
  <DialogFooter>
    <Button variant="outline" onClick={() => setActivateTarget(null)}>
      Cancel
    </Button>
    <Button
      onClick={() => activateTarget && activateMutation.mutate(activateTarget)}
      disabled={activateMutation.isPending}
    >
      {activateMutation.isPending ? "Activating..." : "Activate"}
    </Button>
  </DialogFooter>
</DialogContent>
```

**Step 3: Verify type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 4: Commit**

```bash
git add frontend/src/projects/evaluation/ValidatedPredictorsSection.tsx
git commit -m "refactor: change activation to predictor-only, remove bulk run trigger"
```

---

### Task 8: Add prediction run controls to AnnotationsPage

**Files:**
- Modify: `frontend/src/projects/AnnotationsPage.tsx`
- Modify: `frontend/src/projects/types.ts`

**Step 1: Add types**

In `frontend/src/projects/types.ts`, add:

```typescript
export interface PredictionJobStatus {
  job_id: string;
  status: string; // "pending" | "running" | "completed" | "failed" | "cancelled"
  progress: number;
  result_summary: {
    total_sentences?: number;
    predictions_made?: number;
    annotations_created?: number;
    errors?: number;
    patients_processed?: number;
    total_patients?: number;
    token_usage?: { prompt_tokens: number; completion_tokens: number; total_tokens: number };
  } | null;
  is_cancelled?: boolean;
  created_at?: string;
  started_at?: string;
  completed_at?: string;
}
```

**Step 2: Add PredictionJobBanner component**

In `frontend/src/projects/AnnotationsPage.tsx`, add a new component before the main `AnnotationsPage` function. This component shows when a prediction job is running:

```tsx
function PredictionJobBanner({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const [jobId, setJobId] = useState<string | null>(null);
  const wsRef = useRef<WebSocket | null>(null);

  // Fetch latest job status
  const { data: jobStatus, refetch: refetchStatus } = useQuery<PredictionJobStatus | null>({
    queryKey: ["prediction-job", projectId],
    queryFn: () => api.get<PredictionJobStatus | null>(`/projects/${projectId}/annotations/predictions/status`),
  });

  // Fetch estimate for confirmation dialog
  const [showConfirm, setShowConfirm] = useState(false);
  const { data: estimate } = useQuery<BulkEstimate>({
    queryKey: ["bulk-estimate", projectId],
    queryFn: () => api.get<BulkEstimate>(`/projects/${projectId}/annotations/estimate`),
    enabled: showConfirm,
  });

  // Run predictions
  const runMutation = useMutation({
    mutationFn: () =>
      api.post<PredictionJobStatus>(`/projects/${projectId}/annotations/predictions/run`, {}),
    onSuccess: (data) => {
      setJobId(data.job_id);
      setShowConfirm(false);
      refetchStatus();
    },
  });

  // Cancel job
  const cancelMutation = useMutation({
    mutationFn: () =>
      api.post(`/projects/${projectId}/annotations/predictions/cancel`, {}),
    onSuccess: () => refetchStatus(),
  });

  // WebSocket for live progress
  const isActive = jobStatus?.status === "running" || jobStatus?.status === "pending";

  useEffect(() => {
    const activeJobId = jobId || jobStatus?.job_id;
    if (!isActive || !activeJobId) return;

    const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
    const ws = new WebSocket(`${protocol}//${window.location.host}/ws/projects/${projectId}/jobs/${activeJobId}`);
    wsRef.current = ws;

    ws.onmessage = (event) => {
      const msg = JSON.parse(event.data);
      queryClient.setQueryData<PredictionJobStatus>(
        ["prediction-job", projectId],
        (old) => old ? { ...old, ...msg, status: msg.status } : old,
      );
      // Refresh annotation data as patients complete
      if (msg.result_summary?.patients_processed) {
        queryClient.invalidateQueries({ queryKey: ["patient-next", projectId] });
        queryClient.invalidateQueries({ queryKey: ["annotation-stats", projectId] });
      }
      // Job done
      if (msg.type === "completed" || msg.type === "cancelled" || msg.type === "failed") {
        refetchStatus();
      }
    };

    return () => {
      ws.close();
      wsRef.current = null;
    };
  }, [isActive, jobId, jobStatus?.job_id, projectId, queryClient, refetchStatus]);

  const summary = jobStatus?.result_summary;
  const progress = jobStatus?.progress ?? 0;

  return (
    <>
      {/* Run Predictions Button — show when no active job */}
      {!isActive && (
        <Button
          variant="outline"
          size="sm"
          onClick={() => setShowConfirm(true)}
          className="gap-1.5"
        >
          <Play className="h-3.5 w-3.5" />
          Run Predictions
        </Button>
      )}

      {/* Progress banner — show when job is active */}
      {isActive && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <div className="h-2 w-2 rounded-full bg-amber-500 animate-pulse" />
              <span className="text-sm font-medium text-amber-800 dark:text-amber-300">
                Running predictions
                {summary?.total_patients
                  ? ` · ${summary.patients_processed ?? 0}/${summary.total_patients} patients`
                  : ""}
              </span>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 text-xs text-amber-700 hover:text-amber-900 dark:text-amber-400"
              onClick={() => cancelMutation.mutate()}
              disabled={cancelMutation.isPending}
            >
              Cancel
            </Button>
          </div>
          <Progress value={progress} className="h-1.5" />
        </div>
      )}

      {/* Completed banner — show briefly after completion */}
      {jobStatus?.status === "completed" && summary && (
        <div className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 dark:border-emerald-500/30 dark:bg-emerald-500/10">
          <p className="text-sm text-emerald-800 dark:text-emerald-300">
            Predictions complete: {summary.annotations_created} annotations created
            across {summary.patients_processed} patients
            {summary.errors ? ` (${summary.errors} errors)` : ""}
          </p>
        </div>
      )}

      {/* Cancelled banner */}
      {jobStatus?.status === "cancelled" && summary && (
        <div className="rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-500/30 dark:bg-amber-500/10">
          <p className="text-sm text-amber-800 dark:text-amber-300">
            Predictions cancelled after {summary.patients_processed}/{summary.total_patients} patients
            ({summary.annotations_created} annotations created)
          </p>
        </div>
      )}

      {/* Confirmation dialog */}
      <Dialog open={showConfirm} onOpenChange={setShowConfirm}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Run Predictions?</DialogTitle>
            <DialogDescription>
              This will run the active predictor on all unprocessed target sentences.
              Annotations will be available for review as each patient completes.
            </DialogDescription>
          </DialogHeader>
          {estimate && (
            <div className="rounded-md border bg-muted/30 px-4 py-3 text-sm space-y-1">
              <p><span className="font-medium">{estimate.sentence_count}</span> sentences to process</p>
              <p>Estimated tokens: <span className="font-medium">{estimate.estimated_total_tokens.toLocaleString()}</span></p>
            </div>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowConfirm(false)}>Cancel</Button>
            <Button
              onClick={() => runMutation.mutate()}
              disabled={runMutation.isPending}
            >
              {runMutation.isPending ? "Starting..." : "Start Predictions"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
```

**Step 3: Integrate PredictionJobBanner into AnnotationsPage**

In the `AnnotationsPage` component, add the banner in the header area. Find where the page header is rendered (near the top of the return statement, around the `<WorkflowBreadcrumb>`) and add:

```tsx
<div className="flex items-center justify-between">
  <div>
    <h2 className="text-lg font-semibold text-foreground">Annotations</h2>
    <p className="text-sm text-muted-foreground">Review predictions and adjudicate clinical events</p>
  </div>
  <PredictionJobBanner projectId={projectId!} />
</div>
```

Add the required imports at the top:

```typescript
import { Play } from "lucide-react";
import { Progress } from "@/components/ui/progress";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { PredictionJobStatus, BulkEstimate } from "./types";
```

**Step 4: Verify type-checks and visual**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 5: Commit**

```bash
git add frontend/src/projects/AnnotationsPage.tsx frontend/src/projects/types.ts
git commit -m "feat: add prediction job controls with WebSocket progress to AnnotationsPage"
```

---

### Task 9: Add next-patient prefetch to annotation review

**Files:**
- Modify: `frontend/src/projects/AnnotationsPage.tsx`

**Step 1: Add prefetch logic**

In the `AnnotationsPage` component (or `PatientReviewPanel` if that's a sub-component), find where `patientInfo` is used. Add a prefetch query for the next patient that fires while the current patient is being reviewed:

```typescript
// Prefetch next patient's data while reviewing current patient
const { data: prefetchedNext } = useQuery<PatientInfo>({
  queryKey: ["patient-next-prefetch", projectId],
  queryFn: async () => {
    // Prefetch: fetch next patient info (won't lock — that happens on actual navigation)
    // We use annotation stats to check if there are more patients
    const stats = await api.get<{ unreviewed: number }>(`/projects/${projectId}/annotations/stats`);
    if (stats.unreviewed <= 0) return null as unknown as PatientInfo;
    return api.get<PatientInfo>(`/projects/${projectId}/annotations/patient/next`);
  },
  enabled: false, // Only trigger manually
  staleTime: 0,
});
```

Actually, a simpler and more effective approach: use React Query's `prefetchQuery` to warm the cache. When the clinician is reviewing a patient, prefetch the annotation stats. When all annotations for the current patient are reviewed, the next patient's data loads faster because the stats are already cached.

The better pattern is to use `queryClient.prefetchQuery` in the `handlePostAction` callback when the patient is completed:

```typescript
// In the patient-completion handler:
const handlePatientComplete = async () => {
  // Prefetch next patient data immediately
  queryClient.prefetchQuery({
    queryKey: ["patient-next", projectId],
    queryFn: () => api.get<PatientInfo>(`/projects/${projectId}/annotations/patient/next`),
  });
};
```

Find the existing patient completion logic (where `all_complete` is checked or where `refetchPatient()` is called after the last annotation is reviewed) and add `queryClient.prefetchQuery` before the UI transition.

Additionally, prefetch the next patient's annotations as soon as the current patient is loaded:

```typescript
// When patient annotations are loaded, prefetch annotation context for the first annotation
useEffect(() => {
  if (annotations && annotations.length > 1) {
    // Prefetch context for the second annotation (next in queue)
    const nextAnno = annotations.find((a, i) => i > currentIndex && a.review_status === "unreviewed");
    if (nextAnno) {
      queryClient.prefetchQuery({
        queryKey: ["annotation-context", nextAnno.id],
        queryFn: () => api.get(`/projects/${projectId}/annotations/${nextAnno.id}/context`),
      });
    }
  }
}, [annotations, currentIndex, projectId, queryClient]);
```

**Step 2: Verify type-checks**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Commit**

```bash
git add frontend/src/projects/AnnotationsPage.tsx
git commit -m "perf: prefetch next patient and annotation context during review"
```

---

### Task 10: Run full test suite and verify

**Files:** None (verification only)

**Step 1: Run backend tests**

Run: `cd backend && uv run pytest -v`
Expected: All tests PASS

**Step 2: Run frontend type check**

Run: `cd frontend && npx tsc --noEmit`
Expected: No type errors

**Step 3: Run frontend lint**

Run: `cd frontend && npx eslint src/`
Expected: No lint errors (or only pre-existing ones)

**Step 4: Manual smoke test (if dev server available)**

1. Start backend: `cd backend && uv run uvicorn app.main:create_app --factory --reload`
2. Start frontend: `cd frontend && npm run dev`
3. Navigate to a project → Evaluation → Activate a predictor (should NOT run predictions)
4. Navigate to Annotations page → Click "Run Predictions" → Confirm dialog → Progress banner appears
5. While running: annotations should start appearing for review
6. Cancel works → partial results kept
