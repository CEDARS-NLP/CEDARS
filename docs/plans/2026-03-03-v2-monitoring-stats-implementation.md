# v2 Monitoring, Stats & Queue Infrastructure — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add ARQ background workers, queue monitoring API, Prometheus metrics, project stats API, and enhanced frontend overview to reach v1 monitoring parity.

**Architecture:** Unified ARQ worker process with queue routing, first-party admin API for queue visibility, Prometheus HTTP metrics via instrumentator, consolidated project stats endpoint, and enriched React ProjectOverview page.

**Tech Stack:** ARQ, redis, prometheus-fastapi-instrumentator, FastAPI, SQLAlchemy, React + TanStack Query + shadcn/ui

---

## Task 1: Add BackgroundJob model and migration

**Files:**
- Create: `backend/app/jobs/__init__.py`
- Create: `backend/app/jobs/models.py`
- Create: `backend/migrations/versions/<auto>_add_background_jobs_table.py`
- Modify: `backend/tests/conftest.py:11` (add import for model registration)

**Step 1: Write the failing test**

Create `backend/tests/test_jobs_model.py`:

```python
"""Tests for BackgroundJob model."""
import pytest
from app.jobs.models import BackgroundJob, JobType, JobStatus


@pytest.mark.asyncio
async def test_create_background_job(app):
    """BackgroundJob can be created and persisted."""
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.common.database import get_session

    async for session in app.dependency_overrides[get_session]():
        job = BackgroundJob(
            project_id="proj-1",
            job_type=JobType.NLP,
            status=JobStatus.PENDING,
            created_by="user-1",
        )
        session.add(job)
        await session.commit()
        await session.refresh(job)

        assert job.id is not None
        assert job.job_type == JobType.NLP
        assert job.status == JobStatus.PENDING
        assert job.progress == 0
        assert job.arq_job_id is None
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_jobs_model.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.jobs'`

**Step 3: Create the model**

Create `backend/app/jobs/__init__.py`:

```python
"""Background job infrastructure."""
```

Create `backend/app/jobs/models.py`:

```python
"""Generic background job model for ARQ task tracking."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime, JSON, Text
from sqlmodel import Field, SQLModel


class JobType(str, enum.Enum):
    """Types of background jobs."""

    NLP = "nlp"
    PREDICTION = "prediction"
    EXPORT = "export"


class JobStatus(str, enum.Enum):
    """Status of a background job."""

    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class BackgroundJob(SQLModel, table=True):
    """Tracks background jobs dispatched via ARQ."""

    __tablename__ = "background_jobs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str | None = Field(default=None, foreign_key="projects.id", index=True)
    job_type: JobType
    arq_job_id: str | None = Field(default=None, index=True)
    status: JobStatus = Field(default=JobStatus.PENDING)
    progress: int = Field(default=0)
    result_summary: dict | None = Field(
        default=None,
        sa_column=Column(JSON, nullable=True),
    )
    error_message: str | None = Field(
        default=None,
        sa_column=Column(Text, nullable=True),
    )
    created_by: str | None = Field(default=None, foreign_key="users.id")
    started_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    completed_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
```

Add import to `backend/tests/conftest.py` after line 12:

```python
from app.jobs.models import BackgroundJob  # noqa: F401
```

**Step 4: Run test to verify it passes**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_jobs_model.py -v`
Expected: PASS

**Step 5: Generate Alembic migration**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run alembic revision --autogenerate -m "add background_jobs table"`

Verify the migration file was created and contains `create_table('background_jobs', ...)`.

**Step 6: Commit**

```bash
git add backend/app/jobs/ backend/tests/test_jobs_model.py backend/tests/conftest.py backend/migrations/versions/
git commit -m "feat: add BackgroundJob model for ARQ task tracking"
```

---

## Task 2: ARQ worker setup

**Files:**
- Create: `backend/app/worker.py`
- Create: `backend/app/jobs/nlp.py`
- Modify: `backend/app/config.py` (no changes needed — `redis_url` already exists)
- Modify: `backend/app/nlp/router.py:113-121` (dispatch to ARQ instead of synchronous)
- Modify: `backend/app/nlp/service.py:99-191` (extract job logic for ARQ)

**Step 1: Write the failing test**

Create `backend/tests/test_worker.py`:

```python
"""Tests for ARQ worker configuration and NLP job dispatch."""
import pytest


@pytest.mark.asyncio
async def test_enqueue_nlp_job(app, auth_client):
    """NLP run endpoint returns a job with PENDING status (async dispatch)."""
    # Create project first
    resp = await auth_client.post(
        "/api/v1/projects", json={"name": "Test Project"}
    )
    project_id = resp.json()["id"]

    # Trigger NLP run
    resp = await auth_client.post(f"/api/v1/projects/{project_id}/nlp/run")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] in ("pending", "running")
```

**Step 2: Run test to verify current behavior**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_worker.py -v`
Expected: PASS (currently runs synchronously and returns completed). This establishes the baseline.

**Step 3: Create ARQ worker settings**

Create `backend/app/worker.py`:

```python
"""ARQ worker configuration.

Run with: arq app.worker.WorkerSettings
"""

import logging

from arq.connections import RedisSettings

from app.config import settings

logger = logging.getLogger(__name__)


def parse_redis_settings() -> RedisSettings:
    """Parse CEDARS redis_url into ARQ RedisSettings."""
    from urllib.parse import urlparse

    parsed = urlparse(settings.redis_url)
    return RedisSettings(
        host=parsed.hostname or "localhost",
        port=parsed.port or 6379,
        database=int(parsed.path.lstrip("/") or 0),
        password=parsed.password,
    )


async def run_nlp_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run NLP pipeline for a project."""
    from app.jobs.nlp import execute_nlp_job

    return await execute_nlp_job(project_id, job_db_id)


async def run_prediction_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: run bulk predictions for a project. (Placeholder)"""
    return {"status": "not_implemented"}


async def run_export_job(ctx: dict, project_id: str, job_db_id: str) -> dict:
    """ARQ task: generate export for a project. (Placeholder)"""
    return {"status": "not_implemented"}


class WorkerSettings:
    functions = [run_nlp_job, run_prediction_job, run_export_job]
    redis_settings = parse_redis_settings()
    max_jobs = 10
    job_timeout = 3600
```

**Step 4: Create NLP job executor**

Create `backend/app/jobs/nlp.py`:

```python
"""NLP pipeline ARQ job implementation."""

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.connectors.models import Note
from app.jobs.models import BackgroundJob, JobStatus
from app.nlp.engine import parse_query, process_note
from app.nlp.models import NlpJob, NlpJobStatus, SearchQuery, Sentence

logger = logging.getLogger(__name__)


def _make_session_factory() -> async_sessionmaker[AsyncSession]:
    """Create a standalone session factory for worker processes."""
    engine = create_async_engine(settings.database_url, echo=False)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def execute_nlp_job(project_id: str, job_db_id: str) -> dict:
    """Run the NLP pipeline, updating job progress in the database.

    This is called from the ARQ worker (separate process), so it creates
    its own database session rather than using FastAPI's dependency injection.
    """
    session_factory = _make_session_factory()

    async with session_factory() as session:
        # Load the BackgroundJob record
        bg_job = await session.get(BackgroundJob, job_db_id)
        if not bg_job:
            logger.error("BackgroundJob %s not found", job_db_id)
            return {"error": "Job not found"}

        bg_job.status = JobStatus.RUNNING
        bg_job.started_at = datetime.now(UTC)
        session.add(bg_job)
        await session.commit()

        try:
            # Get active search queries
            stmt = (
                select(SearchQuery)
                .where(
                    SearchQuery.project_id == project_id,
                    SearchQuery.deleted_at.is_(None),
                    SearchQuery.is_active.is_(True),
                )
                .order_by(SearchQuery.created_at.desc())
            )
            result = await session.execute(stmt)
            queries = list(result.scalars().all())

            all_query_groups = []
            for q in queries:
                groups = parse_query(q.query)
                all_query_groups.extend(groups)

            # Get unprocessed notes
            notes_stmt = (
                select(Note)
                .outerjoin(Sentence, Sentence.note_id == Note.id)
                .where(
                    Note.project_id == project_id,
                    Note.deleted_at.is_(None),
                    Sentence.id.is_(None),
                )
                .order_by(Note.created_at)
            )
            result = await session.execute(notes_stmt)
            notes = list(result.scalars().all())

            total = len(notes)
            bg_job.result_summary = {"total_notes": total, "processed_notes": 0}
            session.add(bg_job)
            await session.commit()

            if not notes:
                bg_job.status = JobStatus.COMPLETED
                bg_job.progress = 100
                bg_job.completed_at = datetime.now(UTC)
                session.add(bg_job)
                await session.commit()
                return {"total_notes": 0, "processed_notes": 0}

            for i, note in enumerate(notes):
                sentences = process_note(note.text, all_query_groups)
                for sent_data in sentences:
                    sentence = Sentence(
                        note_id=note.id,
                        project_id=project_id,
                        sentence_number=sent_data["sentence_number"],
                        text=sent_data["text"],
                        start_pos=sent_data["start_pos"],
                        end_pos=sent_data["end_pos"],
                        is_negated=sent_data["is_negated"],
                        is_target=sent_data["is_target"],
                        matched_tokens=sent_data["matched_tokens"],
                    )
                    session.add(sentence)
                await session.flush()

                if (i + 1) % 50 == 0 or i == total - 1:
                    bg_job.progress = int(((i + 1) / total) * 100)
                    bg_job.result_summary = {
                        "total_notes": total,
                        "processed_notes": i + 1,
                    }
                    session.add(bg_job)
                    await session.commit()

            bg_job.status = JobStatus.COMPLETED
            bg_job.progress = 100
            bg_job.completed_at = datetime.now(UTC)
            bg_job.result_summary = {
                "total_notes": total,
                "processed_notes": total,
            }

        except Exception as exc:
            logger.exception("NLP job failed for project %s", project_id)
            bg_job.status = JobStatus.FAILED
            bg_job.error_message = str(exc)

        session.add(bg_job)
        await session.commit()
        return bg_job.result_summary or {}
```

**Step 5: Update NLP service to dispatch via ARQ**

Modify `backend/app/nlp/service.py`. Add a new `dispatch_nlp_job` function that creates a BackgroundJob record and enqueues an ARQ task. Keep the synchronous `run_nlp_pipeline` for backwards compat / tests, but the router will call `dispatch_nlp_job`.

Add to `backend/app/nlp/service.py` (before the existing `run_nlp_pipeline`):

```python
async def dispatch_nlp_job(session: AsyncSession, project_id: str, user_id: str) -> dict:
    """Create a BackgroundJob and enqueue NLP processing via ARQ.

    Falls back to synchronous execution if Redis/ARQ is unavailable.
    """
    from app.jobs.models import BackgroundJob, JobStatus, JobType

    bg_job = BackgroundJob(
        project_id=project_id,
        job_type=JobType.NLP,
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
        arq_job = await redis.enqueue_job(
            "run_nlp_job", project_id, bg_job.id
        )
        bg_job.arq_job_id = arq_job.job_id
        session.add(bg_job)
        await session.commit()
        await redis.close()
    except Exception:
        # Fallback: run synchronously if ARQ/Redis not available
        logger.warning("ARQ unavailable, running NLP synchronously")
        from app.jobs.nlp import execute_nlp_job
        await execute_nlp_job(project_id, bg_job.id)
        await session.refresh(bg_job)

    return {
        "job_id": bg_job.id,
        "status": bg_job.status.value,
        "progress": bg_job.progress,
    }
```

**Step 6: Update NLP router to use dispatch**

Modify `backend/app/nlp/router.py` — update the `run_nlp_endpoint` to call `dispatch_nlp_job` and return a combined response. Add `dispatch_nlp_job` to imports from `app.nlp.service`.

Replace the `run_nlp_endpoint` function body:

```python
@router.post("/run")
async def run_nlp_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Trigger NLP processing for all unprocessed notes in the project."""
    result = await dispatch_nlp_job(session, project_id, current_user.id)
    return result
```

**Step 7: Run tests to verify nothing broke**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_worker.py tests/test_nlp_api.py -v`
Expected: PASS (falls back to synchronous when Redis unavailable in tests)

**Step 8: Commit**

```bash
git add backend/app/worker.py backend/app/jobs/nlp.py backend/app/nlp/service.py backend/app/nlp/router.py backend/tests/test_worker.py
git commit -m "feat: add ARQ worker with NLP job dispatch and sync fallback"
```

---

## Task 3: Queue monitoring admin API

**Files:**
- Create: `backend/app/admin/__init__.py`
- Create: `backend/app/admin/router.py`
- Create: `backend/app/admin/schemas.py`
- Create: `backend/app/admin/service.py`
- Modify: `backend/app/main.py` (register admin router)
- Create: `backend/tests/test_admin_api.py`

**Step 1: Write the failing test**

Create `backend/tests/test_admin_api.py`:

```python
"""Tests for admin queue monitoring API."""
import pytest
from app.auth.models import UserRole


async def _make_admin(client):
    """Register, login, and promote to platform admin."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "admin@test.com", "name": "Admin", "password": "testpass123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "admin@test.com", "password": "testpass123"},
    )
    # Promote to platform admin via direct DB update
    from app.common.database import get_session
    from app.auth.models import User
    from sqlalchemy import select, update

    async for session in client._transport.app.dependency_overrides[get_session]():
        await session.execute(
            update(User)
            .where(User.email == "admin@test.com")
            .values(role=UserRole.PLATFORM_ADMIN)
        )
        await session.commit()


@pytest.mark.asyncio
async def test_get_queues(app, client):
    """Admin can list queue stats."""
    await _make_admin(client)
    resp = await client.get("/api/v1/admin/queues")
    assert resp.status_code == 200
    data = resp.json()
    assert "queues" in data


@pytest.mark.asyncio
async def test_get_queues_forbidden_for_regular_user(app, auth_client):
    """Regular users cannot access admin endpoints."""
    resp = await auth_client.get("/api/v1/admin/queues")
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_get_workers(app, client):
    """Admin can list worker status."""
    await _make_admin(client)
    resp = await client.get("/api/v1/admin/workers")
    assert resp.status_code == 200
    data = resp.json()
    assert "workers" in data


@pytest.mark.asyncio
async def test_list_jobs(app, client):
    """Admin can list background jobs."""
    await _make_admin(client)
    resp = await client.get("/api/v1/admin/jobs")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_admin_api.py -v`
Expected: FAIL — 404 (routes don't exist)

**Step 3: Create admin schemas**

Create `backend/app/admin/__init__.py`:

```python
"""Admin monitoring and queue management."""
```

Create `backend/app/admin/schemas.py`:

```python
"""Schemas for admin queue monitoring API."""

from datetime import datetime

from pydantic import BaseModel


class QueueStats(BaseModel):
    name: str
    pending: int
    active: int
    complete: int
    failed: int


class QueuesResponse(BaseModel):
    queues: list[QueueStats]


class WorkerInfo(BaseModel):
    name: str
    queue: str
    current_job: str | None
    pid: int | None


class WorkersResponse(BaseModel):
    workers: list[WorkerInfo]


class JobListItem(BaseModel):
    id: str
    project_id: str | None
    job_type: str
    status: str
    progress: int
    error_message: str | None
    created_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
```

**Step 4: Create admin service**

Create `backend/app/admin/service.py`:

```python
"""Business logic for admin queue monitoring."""

import logging

from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.jobs.models import BackgroundJob, JobStatus

logger = logging.getLogger(__name__)


async def get_queue_stats(session: AsyncSession) -> list[dict]:
    """Get job counts grouped by status from the database.

    When Redis/ARQ is available this can be enriched with live queue data.
    Falls back gracefully to DB-only stats.
    """
    stmt = (
        select(BackgroundJob.job_type, BackgroundJob.status, func.count(BackgroundJob.id))
        .group_by(BackgroundJob.job_type, BackgroundJob.status)
    )
    result = await session.execute(stmt)
    rows = result.all()

    # Aggregate into per-type stats
    type_stats: dict[str, dict[str, int]] = {}
    for job_type, status, count in rows:
        if job_type not in type_stats:
            type_stats[job_type] = {"pending": 0, "running": 0, "completed": 0, "failed": 0}
        type_stats[job_type][status] = count

    return [
        {
            "name": job_type,
            "pending": stats.get("pending", 0),
            "active": stats.get("running", 0),
            "complete": stats.get("completed", 0),
            "failed": stats.get("failed", 0),
        }
        for job_type, stats in type_stats.items()
    ]


async def get_worker_info() -> list[dict]:
    """Get active ARQ worker info from Redis.

    Returns empty list if Redis is unavailable.
    """
    try:
        from arq import create_pool
        from app.worker import parse_redis_settings

        redis = await create_pool(parse_redis_settings())
        # ARQ stores worker heartbeats in Redis
        keys = await redis.keys("arq:worker:*")
        workers = []
        for key in keys:
            name = key.decode() if isinstance(key, bytes) else key
            workers.append({
                "name": name.replace("arq:worker:", ""),
                "queue": "default",
                "current_job": None,
                "pid": None,
            })
        await redis.close()
        return workers
    except Exception:
        logger.debug("Redis unavailable for worker info")
        return []


async def list_jobs(
    session: AsyncSession,
    status: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[BackgroundJob]:
    """List background jobs, optionally filtered by status."""
    stmt = select(BackgroundJob).order_by(BackgroundJob.created_at.desc())
    if status:
        stmt = stmt.where(BackgroundJob.status == status)
    stmt = stmt.offset(offset).limit(limit)
    result = await session.execute(stmt)
    return list(result.scalars().all())
```

**Step 5: Create admin router**

Create `backend/app/admin/router.py`:

```python
"""Admin API routes for queue monitoring and job management."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User, UserRole
from app.common.database import get_session
from app.dependencies import get_current_user
from app.admin.schemas import JobListItem, QueuesResponse, WorkersResponse
from app.admin.service import get_queue_stats, get_worker_info, list_jobs

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])


def require_platform_admin():
    """Dependency that requires platform admin role."""

    async def dependency(
        current_user: User = Depends(get_current_user),
    ) -> User:
        if current_user.role != UserRole.PLATFORM_ADMIN:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Platform admin required",
            )
        return current_user

    return dependency


@router.get("/queues", response_model=QueuesResponse)
async def queues_endpoint(
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """Get queue statistics."""
    stats = await get_queue_stats(session)
    return {"queues": stats}


@router.get("/workers", response_model=WorkersResponse)
async def workers_endpoint(
    _admin: User = Depends(require_platform_admin()),
):
    """Get active worker info."""
    workers = await get_worker_info()
    return {"workers": workers}


@router.get("/jobs", response_model=list[JobListItem])
async def list_jobs_endpoint(
    job_status: str | None = Query(None, alias="status"),
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _admin: User = Depends(require_platform_admin()),
):
    """List background jobs."""
    jobs = await list_jobs(session, status=job_status, limit=limit, offset=offset)
    return jobs
```

**Step 6: Register admin router in main.py**

Add to `backend/app/main.py` after other router imports:

```python
from app.admin.router import router as admin_router
```

And add in `create_app()` after other `include_router` calls:

```python
application.include_router(admin_router)
```

**Step 7: Run tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_admin_api.py -v`
Expected: PASS

**Step 8: Commit**

```bash
git add backend/app/admin/ backend/tests/test_admin_api.py backend/app/main.py
git commit -m "feat: add admin API for queue monitoring and job management"
```

---

## Task 4: Prometheus metrics

**Files:**
- Modify: `backend/pyproject.toml` (add dependency)
- Modify: `backend/app/main.py` (instrument app)
- Create: `prometheus.v2.yml`
- Modify: `docker-compose.v2.yml` (add prometheus service)

**Step 1: Write the failing test**

Create `backend/tests/test_metrics.py`:

```python
"""Tests for Prometheus metrics endpoint."""
import pytest


@pytest.mark.asyncio
async def test_metrics_endpoint_exists(app, client):
    """The /metrics endpoint returns Prometheus format data."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "http_request" in text or "HELP" in text
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_metrics.py -v`
Expected: FAIL — 404 (endpoint doesn't exist)

**Step 3: Add dependency**

Add `prometheus-fastapi-instrumentator>=7.0` to `backend/pyproject.toml` dependencies list.

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv lock && uv sync`

**Step 4: Instrument the app**

Modify `backend/app/main.py`. Add after the `application = FastAPI(...)` block inside `create_app()`:

```python
from prometheus_fastapi_instrumentator import Instrumentator
Instrumentator().instrument(application).expose(application)
```

**Step 5: Run test**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_metrics.py -v`
Expected: PASS

**Step 6: Create Prometheus config**

Create `prometheus.v2.yml`:

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: "cedars-backend"
    static_configs:
      - targets: ["backend:8000"]
```

**Step 7: Update docker-compose.v2.yml**

Add prometheus service to `docker-compose.v2.yml`:

```yaml
  prometheus:
    image: prom/prometheus:v2.51.0
    volumes:
      - ./prometheus.v2.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"
    depends_on:
      - redis
```

Also add the `worker` service:

```yaml
  worker:
    build: ./backend
    command: ["uv", "run", "arq", "app.worker.WorkerSettings"]
    depends_on:
      db:
        condition: service_healthy
      redis:
        condition: service_healthy
    environment:
      CEDARS_DATABASE_URL: postgresql+asyncpg://cedars:cedars@db:5432/cedars
      CEDARS_REDIS_URL: redis://redis:6379
```

**Step 8: Commit**

```bash
git add backend/pyproject.toml backend/uv.lock backend/app/main.py prometheus.v2.yml docker-compose.v2.yml backend/tests/test_metrics.py
git commit -m "feat: add Prometheus metrics and ARQ worker to docker-compose"
```

---

## Task 5: Project stats API

**Files:**
- Create: `backend/app/projects/stats.py`
- Modify: `backend/app/projects/router.py` (add stats endpoint)
- Create: `backend/tests/test_project_stats_api.py`

**Step 1: Write the failing test**

Create `backend/tests/test_project_stats_api.py`:

```python
"""Tests for project stats API."""
import pytest


async def _setup_project(client):
    """Register, login, create project, return project_id."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "stats@test.com", "name": "Stats User", "password": "testpass123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "stats@test.com", "password": "testpass123"},
    )
    resp = await client.post(
        "/api/v1/projects", json={"name": "Stats Project"}
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_project_stats_empty(app, client):
    """Stats for a new project return zero counts."""
    project_id = await _setup_project(client)
    resp = await client.get(f"/api/v1/projects/{project_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patients"]["total"] == 0
    assert data["notes"]["total"] == 0
    assert data["sentences"]["total"] == 0
    assert data["annotations"]["total"] == 0
    assert data["annotators"] == []


@pytest.mark.asyncio
async def test_project_stats_with_data(app, client):
    """Stats reflect uploaded data."""
    project_id = await _setup_project(client)

    # Insert test data directly
    from app.common.database import get_session
    from app.connectors.models import Patient, Note, PatientStatus
    from app.nlp.models import Sentence
    from datetime import datetime, UTC

    async for session in client._transport.app.dependency_overrides[get_session]():
        p = Patient(
            project_id=project_id, patient_id_ext="P001", status=PatientStatus.NLP_COMPLETE
        )
        session.add(p)
        await session.flush()

        n = Note(
            project_id=project_id,
            patient_id=p.id,
            text_id="N001",
            note_date=datetime.now(UTC),
            text="Patient has chest pain.",
        )
        session.add(n)
        await session.flush()

        s = Sentence(
            note_id=n.id,
            project_id=project_id,
            sentence_number=0,
            text="Patient has chest pain.",
            start_pos=0,
            end_pos=24,
            is_target=True,
        )
        session.add(s)
        await session.commit()

    resp = await client.get(f"/api/v1/projects/{project_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patients"]["total"] == 1
    assert data["patients"]["by_status"]["nlp_complete"] == 1
    assert data["notes"]["total"] == 1
    assert data["sentences"]["total"] == 1
    assert data["sentences"]["target"] == 1
```

**Step 2: Run test to verify it fails**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_project_stats_api.py -v`
Expected: FAIL — 404 or 405

**Step 3: Create stats service**

Create `backend/app/projects/stats.py`:

```python
"""Project-level statistics aggregation."""

from sqlalchemy import func, select, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.jobs.models import BackgroundJob, JobStatus
from app.nlp.models import Sentence


async def get_project_stats(session: AsyncSession, project_id: str) -> dict:
    """Aggregate all project statistics in a single call."""

    # Patients by status
    patient_stmt = (
        select(Patient.status, func.count(Patient.id))
        .where(Patient.project_id == project_id, Patient.deleted_at.is_(None))
        .group_by(Patient.status)
    )
    patient_result = await session.execute(patient_stmt)
    patient_rows = patient_result.all()
    patient_total = sum(count for _, count in patient_rows)
    patient_by_status = {s.value: 0 for s in PatientStatus}
    for status, count in patient_rows:
        patient_by_status[status.value if hasattr(status, "value") else status] = count

    # Notes count
    notes_total = (
        await session.execute(
            select(func.count(Note.id)).where(
                Note.project_id == project_id, Note.deleted_at.is_(None)
            )
        )
    ).scalar() or 0

    # Sentences
    sentence_stmt = select(
        func.count(Sentence.id),
        func.count(case((Sentence.is_target.is_(True), 1))),
        func.count(case((Sentence.is_negated.is_(True), 1))),
    ).where(Sentence.project_id == project_id)
    sent_result = await session.execute(sentence_stmt)
    sent_row = sent_result.one()
    sentences_total, sentences_target, sentences_negated = sent_row

    # Annotations by review status
    ann_stmt = (
        select(Annotation.review_status, func.count(Annotation.id))
        .where(Annotation.project_id == project_id)
        .group_by(Annotation.review_status)
    )
    ann_result = await session.execute(ann_stmt)
    ann_rows = ann_result.all()
    ann_total = sum(count for _, count in ann_rows)
    ann_by_status = {s.value: 0 for s in ReviewStatus}
    for status, count in ann_rows:
        ann_by_status[status.value if hasattr(status, "value") else status] = count

    # Events found
    events_found = (
        await session.execute(
            select(func.count(Annotation.id)).where(
                Annotation.project_id == project_id,
                Annotation.event_date.isnot(None),
            )
        )
    ).scalar() or 0

    # Per-annotator stats
    annotator_stmt = (
        select(
            Annotation.reviewed_by,
            User.email,
            User.name,
            func.count(Annotation.id),
            func.count(case((Annotation.event_date.isnot(None), 1))),
        )
        .join(User, User.id == Annotation.reviewed_by)
        .where(
            Annotation.project_id == project_id,
            Annotation.reviewed_by.isnot(None),
        )
        .group_by(Annotation.reviewed_by, User.email, User.name)
    )
    annotator_result = await session.execute(annotator_stmt)
    annotators = [
        {
            "user_id": row[0],
            "email": row[1],
            "name": row[2],
            "reviewed_count": row[3],
            "events_found": row[4],
        }
        for row in annotator_result.all()
    ]

    # Latest jobs
    latest_job_stmt = (
        select(BackgroundJob)
        .where(BackgroundJob.project_id == project_id)
        .order_by(BackgroundJob.created_at.desc())
        .limit(1)
    )
    latest_job_result = await session.execute(latest_job_stmt)
    latest_job = latest_job_result.scalar_one_or_none()

    active_jobs = (
        await session.execute(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.project_id == project_id,
                BackgroundJob.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
            )
        )
    ).scalar() or 0

    failed_jobs = (
        await session.execute(
            select(func.count(BackgroundJob.id)).where(
                BackgroundJob.project_id == project_id,
                BackgroundJob.status == JobStatus.FAILED,
            )
        )
    ).scalar() or 0

    return {
        "patients": {
            "total": patient_total,
            "by_status": patient_by_status,
        },
        "notes": {"total": notes_total},
        "sentences": {
            "total": sentences_total,
            "target": sentences_target,
            "negated": sentences_negated,
        },
        "annotations": {
            "total": ann_total,
            "reviewed": ann_by_status.get("reviewed", 0),
            "unreviewed": ann_by_status.get("unreviewed", 0),
            "skipped": ann_by_status.get("skipped", 0),
            "events_found": events_found,
        },
        "annotators": annotators,
        "jobs": {
            "latest": {
                "id": latest_job.id,
                "job_type": latest_job.job_type.value,
                "status": latest_job.status.value,
                "progress": latest_job.progress,
                "started_at": latest_job.started_at.isoformat() if latest_job.started_at else None,
                "completed_at": latest_job.completed_at.isoformat() if latest_job.completed_at else None,
            }
            if latest_job
            else None,
            "active_count": active_jobs,
            "failed_count": failed_jobs,
        },
    }
```

**Step 4: Add stats endpoint to project router**

Add to `backend/app/projects/router.py` after the existing `get_project_endpoint`:

```python
from app.projects.stats import get_project_stats

@router.get("/{project_id}/stats")
async def project_stats_endpoint(
    project_id: str,
    current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
    session: AsyncSession = Depends(get_session),
):
    """Get comprehensive project statistics."""
    return await get_project_stats(session, project_id)
```

**Step 5: Run tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest tests/test_project_stats_api.py -v`
Expected: PASS

**Step 6: Run full test suite**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v`
Expected: All tests pass

**Step 7: Commit**

```bash
git add backend/app/projects/stats.py backend/app/projects/router.py backend/tests/test_project_stats_api.py
git commit -m "feat: add consolidated project stats API endpoint"
```

---

## Task 6: Enhanced ProjectOverview frontend

**Files:**
- Modify: `frontend/src/projects/ProjectOverview.tsx`
- Create: `frontend/src/projects/types.ts` (if it doesn't have stats types yet)

**Step 1: Add stats types**

Add to `frontend/src/projects/types.ts` (or create if needed):

```typescript
export interface ProjectStats {
  patients: {
    total: number;
    by_status: Record<string, number>;
  };
  notes: { total: number };
  sentences: { total: number; target: number; negated: number };
  annotations: {
    total: number;
    reviewed: number;
    unreviewed: number;
    skipped: number;
    events_found: number;
  };
  annotators: {
    user_id: string;
    email: string;
    name: string;
    reviewed_count: number;
    events_found: number;
  }[];
  jobs: {
    latest: {
      id: string;
      job_type: string;
      status: string;
      progress: number;
      started_at: string | null;
      completed_at: string | null;
    } | null;
    active_count: number;
    failed_count: number;
  };
}
```

**Step 2: Update ProjectOverview**

Replace the top stats cards section in `frontend/src/projects/ProjectOverview.tsx` with a richer stats display that fetches from the new `/stats` endpoint.

Add a `useQuery` call for the stats endpoint:

```typescript
const { data: stats } = useQuery<ProjectStats>({
  queryKey: ["project-stats", projectId],
  queryFn: () => api.get<ProjectStats>(`/projects/${projectId}/stats`),
  refetchInterval: 10000, // poll every 10s for job progress
});
```

Replace the 3-card grid with a more comprehensive stats section:

- **Row 1:** 4 stat cards (Patients total, Notes total, Target Sentences, Annotations reviewed/total)
- **Row 2:** Progress bar showing annotation completion (reviewed / total)
- **Row 3:** Active job indicator (if `stats.jobs.active_count > 0` or `stats.jobs.latest?.status === "running"`, show a progress bar with the job progress percentage)
- **Row 4:** Annotator activity table (admin-only — check project role from outlet context) showing each annotator's reviewed count and events found
- **Row 5:** Job history — latest job status with timestamp

Keep the existing workflow stepper below the stats section. It should still use its own queries for step state logic.

The stat cards should use the existing design pattern: `rounded-lg border border-border bg-card px-5 py-4` with `text-sm text-muted-foreground` labels and `text-2xl font-semibold text-foreground` values.

For the annotator table, use a simple `<table>` with `text-sm` styling — no external table component needed.

For the job progress indicator, use the existing `Progress` component from `@/components/ui/progress`.

**Step 3: Verify manually**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npm run dev`

Check that the ProjectOverview page loads, shows the stats cards, and the workflow stepper still works. With no data, all stats should show 0 or "--".

**Step 4: Commit**

```bash
git add frontend/src/projects/ProjectOverview.tsx frontend/src/projects/types.ts
git commit -m "feat: add stats cards, job progress, and annotator table to project overview"
```

---

## Task 7: Final integration and cleanup

**Files:**
- Modify: `docker-compose.v2.yml` (verify all services)
- Run full test suites

**Step 1: Run all backend tests**

Run: `cd /Users/rsingh/Programming/CEDARS/backend && uv run pytest -v --tb=short`
Expected: All pass

**Step 2: Run frontend build check**

Run: `cd /Users/rsingh/Programming/CEDARS/frontend && npm run build`
Expected: No TypeScript errors

**Step 3: Final commit**

If any fixes were needed, commit them:

```bash
git add -A
git commit -m "fix: integration fixes for monitoring infrastructure"
```

---

## Verification Checklist

After all tasks complete, verify:

- [ ] `BackgroundJob` model exists and migration runs
- [ ] ARQ worker starts with `uv run arq app.worker.WorkerSettings`
- [ ] NLP `/run` endpoint creates a BackgroundJob and either dispatches to ARQ or falls back to sync
- [ ] `GET /api/v1/admin/queues` returns queue stats (admin only)
- [ ] `GET /api/v1/admin/workers` returns worker info (admin only)
- [ ] `GET /api/v1/admin/jobs` lists background jobs (admin only)
- [ ] `GET /metrics` returns Prometheus format data
- [ ] `GET /api/v1/projects/{id}/stats` returns consolidated project stats
- [ ] ProjectOverview shows stats cards, job progress, annotator table
- [ ] `docker-compose.v2.yml` includes worker and prometheus services
- [ ] All backend tests pass
- [ ] Frontend builds without errors
