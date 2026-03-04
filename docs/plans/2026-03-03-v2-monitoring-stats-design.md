# v2 Monitoring, Stats & Queue Infrastructure

**Date:** 2026-03-03
**Status:** Approved

## Goal

Bring v2 to parity with v1's monitoring capabilities (rq-dashboard, stats page, Prometheus) while leveraging the new architecture (FastAPI, React, PostgreSQL, ARQ).

## Decisions

- **Unified ARQ worker** with queue routing (not separate worker processes per domain)
- **First-party queue monitoring API** (replaces rq-dashboard with React-consumable endpoints)
- **Prometheus metrics** via `prometheus-fastapi-instrumentator`
- **Consolidated project stats endpoint** (one API call for the full project overview)
- **Frontend lives on ProjectOverview** (no separate admin page)

---

## 1. ARQ Worker Infrastructure

### New files

- `backend/app/worker.py` — ARQ `WorkerSettings` class, queue definitions
- `backend/app/jobs/__init__.py`
- `backend/app/jobs/nlp.py` — NLP pipeline job (migrate from synchronous `nlp/service.py:run_nlp_pipeline`)
- `backend/app/jobs/prediction.py` — Prediction/annotation generation job
- `backend/app/jobs/export.py` — Export job

### Worker configuration

```python
# backend/app/worker.py
from arq import cron
from arq.connections import RedisSettings
from app.config import settings

class WorkerSettings:
    functions = [run_nlp_job, run_prediction_job, run_export_job]
    redis_settings = RedisSettings.from_dsn(settings.redis_url)
    queue_name = "arq:queue"  # single queue, routing via function names
    max_jobs = 10
    job_timeout = 3600  # 1 hour
```

### Docker-compose addition

```yaml
worker:
  build: ./backend
  command: arq app.worker.WorkerSettings
  depends_on:
    db:
      condition: service_healthy
    redis:
      condition: service_healthy
  environment:
    CEDARS_DATABASE_URL: postgresql+asyncpg://cedars:cedars@db:5432/cedars
    CEDARS_REDIS_URL: redis://redis:6379
```

### Job model

Add a generic `BackgroundJob` table alongside `NlpJob`:

```
BackgroundJob:
  id: str (PK)
  project_id: str (FK, nullable for system jobs)
  job_type: enum (nlp, prediction, export)
  arq_job_id: str (links to ARQ's Redis job)
  status: enum (pending, running, completed, failed)
  progress: int (0-100)
  result_summary: JSON (nullable)
  error_message: str (nullable)
  created_by: str (FK users)
  started_at, completed_at, created_at: datetime
```

`NlpJob` will be migrated to use `BackgroundJob` as its backing store (or retained for backwards compat with additional fields like `total_notes`/`processed_notes`).

---

## 2. Queue Monitoring API

### Router: `backend/app/admin/router.py`

Prefix: `/api/v1/admin`
Access: admin users only (not project-scoped).

| Endpoint | Method | Returns |
|----------|--------|---------|
| `/queues` | GET | Queue names with pending/active/complete/failed counts |
| `/queues/{queue}/jobs` | GET | Paginated job list with status, timestamps, errors |
| `/workers` | GET | Active workers, current job, uptime |
| `/jobs/{job_id}/retry` | POST | Retry a failed job |
| `/jobs/{job_id}/cancel` | POST | Cancel a pending/running job |

### Implementation

Uses `arq.connections.ArqRedis` to query Redis directly for queue state and job results. Combines with `BackgroundJob` table for richer metadata.

---

## 3. Prometheus Metrics

### Dependency

Add `prometheus-fastapi-instrumentator>=7.0` to `pyproject.toml`.

### Integration in `main.py`

```python
from prometheus_fastapi_instrumentator import Instrumentator

def create_app() -> FastAPI:
    app = FastAPI(...)
    Instrumentator().instrument(app).expose(app, endpoint="/metrics")
    ...
```

### Default metrics

- `http_request_duration_seconds` (histogram by method, path, status)
- `http_requests_total` (counter)
- `http_requests_in_progress` (gauge)

### Docker-compose

```yaml
prometheus:
  image: prom/prometheus:v2.51.0
  volumes:
    - ./prometheus.v2.yml:/etc/prometheus/prometheus.yml
  ports:
    - "9090:9090"
```

With a `prometheus.v2.yml` scraping `backend:8000/metrics` every 15s.

---

## 4. Project Stats API

### Endpoint

`GET /api/v1/projects/{project_id}/stats`

Access: any project member (admin, annotator, viewer).

### Response schema

```json
{
  "patients": {
    "total": 150,
    "by_status": {
      "new": 10,
      "nlp_processing": 0,
      "nlp_complete": 80,
      "reviewing": 0,
      "reviewed": 60
    }
  },
  "notes": {
    "total": 2340
  },
  "sentences": {
    "total": 12000,
    "target": 450,
    "negated": 120
  },
  "annotations": {
    "total": 450,
    "reviewed": 320,
    "unreviewed": 100,
    "skipped": 30,
    "events_found": 45
  },
  "annotators": [
    {
      "user_id": "...",
      "email": "dr@example.com",
      "reviewed_count": 180,
      "events_found": 25
    }
  ],
  "jobs": {
    "latest_nlp": {
      "id": "...",
      "status": "completed",
      "total_notes": 2340,
      "processed_notes": 2340,
      "started_at": "...",
      "completed_at": "..."
    },
    "active_count": 0,
    "failed_count": 0
  }
}
```

### Implementation

Single service function with parallel SQL queries (patients GROUP BY status, notes COUNT, sentences COUNT WHERE is_target, annotations GROUP BY review_status, annotations GROUP BY reviewed_by).

Router: add to existing `backend/app/projects/router.py` or new `backend/app/projects/stats.py`.

---

## 5. Frontend: Enhanced ProjectOverview

### New sections on ProjectOverview

1. **Stats cards row** (top): patients total + by-status breakdown, notes count, sentences (total/target), annotations (reviewed/total with progress bar)

2. **Annotator activity table**: per-user review counts and events found — visible to admins

3. **Job status section**: latest NLP job with progress indicator, active/failed job counts with links

4. **Collapsible "System" section** (admin-only): queue depths, worker count, link to Prometheus

### Data fetching

Single `useQuery` call to `GET /projects/{projectId}/stats`. Replace the multiple existing queries in ProjectOverview (sources, predictors, validated, annotationStats) where possible, keeping the workflow stepper's existing queries.

---

## Non-goals (deferred)

- Grafana dashboards (use Prometheus UI directly for now)
- Custom Prometheus metrics beyond HTTP defaults (queue depth gauge, job duration histogram — add later)
- System-wide admin page (per-project view sufficient for now)
- WebSocket real-time job progress (polling via React Query refetchInterval)
