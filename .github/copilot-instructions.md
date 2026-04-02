# CEDARS Copilot Instructions

CEDARS (Clinical Event Detection and Recording System) is an NLP platform for clinical event detection in EHRs. The repository contains **two parallel generations** of the system that coexist:

- **v1** (`cedars/`): Production Flask app with MongoDB + RQ + MinIO
- **v2** (`backend/` + `frontend/`): In-progress FastAPI rewrite with PostgreSQL + ARQ + React/TypeScript

Always clarify which generation a task applies to — they have separate dependencies, test suites, and conventions.

---

## Build, Test, and Lint Commands

### v2 Backend (`backend/`) — uv + FastAPI
```bash
cd backend
uv sync                                                      # install deps
uv sync --group dev                                          # include dev deps
uv run uvicorn app.main:app --reload                         # dev server (port 8000)
uv run arq app.worker.WorkerSettings                         # start ARQ worker
uv run alembic upgrade head                                  # run migrations
uv run alembic revision --autogenerate -m "description"      # create migration
uv run pytest                                                # all tests
uv run pytest tests/test_projects_api.py::test_name -v      # single test
uv run ruff check .                                          # lint
uv run ruff format .                                         # format
```

Tests use **SQLite in-memory** (`sqlite+aiosqlite://`) with `StaticPool` — no external services needed.

### v1 CEDARS (`cedars/`) — uv + Flask
```bash
cd cedars
uv sync                                                      # install deps
uv sync --group dev                                          # include dev deps
uv run gunicorn -c gunicorn.conf.py "app.wsgi:create_app()"  # run app
uv run pytest                                                # all tests
uv run pytest tests/test_file.py::test_name -v              # single test
uv run pytest --cov=app                                      # with coverage
uv run flake8 ./                                             # lint
```

Required env var for v1 tests: `PROMETHEUS_MULTIPROC_DIR=/tmp/prometheus-multiproc`

### v2 Frontend (`frontend/`) — npm + Vite + React
```bash
cd frontend
npm install
npm run dev         # dev server (port 5173)
npm run build       # production build (tsc + vite)
npm run lint        # eslint
npx tsc --noEmit   # type check only
```

---

## Architecture

### v2 Data Flow
```
React frontend (Vite/port 5173)
    → api/client.ts (fetch wrapper, auto-refresh JWT)
    → FastAPI backend (port 8000) /api/v1/...
        → PostgreSQL via SQLAlchemy async + SQLModel
        → Redis/ARQ for background jobs (NLP, ingestion, predictions)
        → S3/MinIO for file storage
        → PINES service (optional) for Longformer-based NLP
```

### v2 Backend Module Layout
Each domain lives in its own package under `backend/app/`:
```
auth/           — JWT auth (httpOnly cookies), user model, platform roles
projects/       — multi-tenant project CRUD, membership
connectors/     — data ingestion (file upload, Databricks), Patient/Note models
nlp/            — spaCy pipeline, search queries, sentence extraction
pipeline/       — EventConfig → PipelineRun → PatientTask → Evidence state machine
annotations/    — review workflow, bulk prediction dispatch
evaluation/     — eval sessions, search matches, patient results
predictors/     — LLM/PINES predictor config and execution
jobs/           — BackgroundJob tracking, WebSocket progress (ARQ tasks)
audit/          — immutable AuditEntry log
export/         — CSV/JSON export
admin/          — platform-admin endpoints
common/         — shared: database session, S3 client
```

Every domain package follows the same pattern: `models.py` → `schemas.py` → `service.py` → `router.py`.

### v2 Access Control
Two levels:
1. **Platform role** (on `User` model): `platform_admin` bypasses all project checks
2. **Project role** (`ProjectMember`): `admin` > `annotator` > `viewer`

Use the `require_project_role("admin", "annotator")` dependency factory in routers. Platform admins automatically pass all role checks.

### v1 Architecture (Flask/MongoDB)
- `cedars/app/db.py` — monolithic data layer (~2200 lines); all DB access goes through it
- `cedars/app/ops.py` — main Flask blueprint with annotation UI routes
- `cedars/app/nlpprocessor.py` — spaCy + NegEx pipeline
- `cedars/app/predictors/` — LLM/PINES predictor system (same design as v2)
- Config via `.env` file; all env vars use no prefix (unlike v2's `CEDARS_` prefix)

### Background Jobs
- **v2**: ARQ (`arq app.worker.WorkerSettings`). Tasks defined in `backend/app/worker.py`. All models must be imported at worker startup (see worker.py comments). WebSocket endpoints at `/ws/projects/{id}/jobs/{id}` push progress.
- **v1**: RQ with two queues (`task` and `ops`). Job IDs use `-` as separator, never `:`.

---

## Key Conventions

### v2 Backend
- **SQLModel** for all models. Use `table=True` for DB models. `sa_column=Column(...)` for type overrides (e.g. `DateTime(timezone=True)`, `JSON`).
- **All datetimes are UTC**: `datetime.now(UTC)`, never `datetime.utcnow()`.
- **UUIDs as strings**: `id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)`.
- **JSONB on PostgreSQL, JSON on SQLite**: Use `Column(JSONB if postgres else JSON)` pattern for dict fields. See `pipeline/models.py` for the canonical pattern.
- **Alembic migrations**: When adding a model, also import it in `migrations/env.py` (and `tests/conftest.py`) so metadata is registered.
- **Async throughout**: Sessions from `get_session()` dependency, `AsyncSession`, `async_sessionmaker`. Never use sync SQLAlchemy.
- **Config via `Settings`**: All settings in `backend/app/config.py` use `CEDARS_` env prefix. Access via `from app.config import settings`.
- **Line length**: 100 characters (ruff).
- **Router prefix pattern**: `router = APIRouter(prefix="/api/v1/projects/{project_id}/...", tags=[...])`.

### v2 Frontend
- **API client**: Use `api.get/post/put/delete` from `@/api/client.ts`. It handles JWT refresh automatically on 401.
- **Auth**: `useAuth()` hook from `AuthProvider`. Auth state lives in React context, not localStorage.
- **Routing**: React Router v6 with nested routes. Project pages live under `/projects/:projectId/`.
- **Styling**: Tailwind CSS + shadcn/ui components. Use `cn()` from `@/lib/utils` for class merging.
- **Path alias**: `@/` maps to `src/`.

### v1 Flask
- **RQ job IDs**: Use `-` as separator (e.g., `spacy-{patient_id}`), never `:` (breaks RQ 1.16+).
- **Config loading**: Single `dotenv_values(".env")` call in `config.py`; import `config` elsewhere rather than re-calling `dotenv_values`.
- **Enums**: Class-based in `cedars/app/cedars_enums.py` — use `PatientStatus`, `ReviewStatus`.
- **Pydantic v2**: Models use `model_config = ConfigDict(...)` syntax, not `class Config`.

### Shared
- **Python**: 3.10–3.12 only. 3.13 blocked by `nmslib-metabrainz`.
- **Imports**: stdlib → third-party → local. Separate groups with blank lines.
- **Naming**: `CamelCase` classes, `snake_case` functions/variables, `UPPER_SNAKE_CASE` constants.
- **LLM integration**: LiteLLM 1.40+ for all LLM providers (OpenAI, Anthropic, Ollama, Bedrock, etc.).

---

## Testing Patterns

### v2 Backend Tests
- **In-memory SQLite** for all tests — no real DB/Redis needed.
- `conftest.py` provides `app`, `client`, and `client_factory` async fixtures.
- Register all new models in `conftest.py` imports (the `# noqa: F401` imports ensure tables exist in test DB).
- ARQ is patched to always fail (`ConnectionError`), triggering synchronous fallback paths.
- Pytest config: `asyncio_mode = "auto"` — all async tests work without `@pytest.mark.asyncio`.

### v1 Flask Tests
- Uses `mongomock` + `fakeredis` + `pytest-minio-mock`.
- `PROMETHEUS_MULTIPROC_DIR` must be set (to any existing dir) before importing the app.
- Session-scoped `db` fixture pre-populates test data from `tests/simulated_patients.csv`.
