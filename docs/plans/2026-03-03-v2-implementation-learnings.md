# CEDARS v2 Implementation Learnings

**Purpose:** Compare v1 (Flask/MongoDB) implementation against v2 (FastAPI/React/PostgreSQL) implementation. Document what was done, what Claude did, and where the new approach is better or worse than the original.

**Audience:** Engineering team, for knowledge sharing and decision validation.

**Status:** Living document — updated after each implementation task.

---

## Overall Architecture Comparison

| Aspect | v1 (Current) | v2 (Reimplementation) | Verdict |
|--------|-------------|----------------------|---------|
| Backend framework | Flask 3.x (sync, WSGI) | FastAPI (async, ASGI) | v2: native async, auto OpenAPI docs, Pydantic-first |
| Frontend | Jinja2 + Bootstrap + vanilla JS | React + TypeScript + shadcn/ui | v2: SPA, richer interactivity, type safety |
| Database | MongoDB (+ SQLite via repository pattern) | PostgreSQL (JSONB for flexibility) | v2: ACID, migrations, relational integrity, single backend |
| ORM/ODM | PyMongo (raw) + custom repository layer | SQLAlchemy 2.0 + SQLModel + Alembic | v2: type-safe, migration-managed, async |
| Queue | RQ (sync, 2 worker types) | ARQ (async, unified pool) | v2: fewer moving parts, async-native |
| Auth | flask-login (session-based) | JWT (stateless) | v2: API-friendly, no server-side session state |
| Package management | uv (cedars) + Poetry (PINES) | uv (unified) | v2: single tool across all Python |
| Multi-tenancy | One project per instance | Multi-project platform | v2: major capability gain |
| Object storage | MinIO only | S3-compatible abstraction | v2: works with AWS S3, MinIO, GCS |

---

## Task-by-Task Learnings

### Phase 0: Scaffolding

#### Task 0.1: Initialize Backend (FastAPI)

**v1 approach:** Flask app factory in `cedars/app/__init__.py` (130 lines). Config loaded from `.env` via `dotenv_values()` in multiple places (was 3x, fixed to 1x in Phase 1 refactor). Blueprint-based routing with circular import risk (`database.py` imports `db`, `nlpprocessor`, `api`).

**v2 approach:** FastAPI app factory in `backend/app/main.py`. Config via pydantic-settings (`app/config.py`) — single source of truth, validated at startup, type-safe. CORS configured for SPA development.

**What v2 does better:**
- Config validation at startup (pydantic-settings raises errors for missing/invalid values immediately, vs Flask where bad config surfaces at runtime)
- No circular import risk (clean dependency graph from the start)
- CORS configured for API-first development
- OpenAPI docs auto-generated at `/docs`

**What v1 did well:**
- Flask's simplicity for server-rendered apps — fewer moving parts when you don't need an SPA
- Blueprint system is straightforward for route organization

**Claude's implementation notes:**
- Created clean separation between app factory and config from day one
- Used asynccontextmanager for lifespan (FastAPI best practice vs Flask's before_first_request which was removed in Flask 2.3)

---

#### Task 0.4: Initialize Frontend (React + TypeScript + Vite)

**v1 approach:** 19 Jinja2 templates in `cedars/app/templates/`, Bootstrap CSS, vanilla JavaScript. No build step. No type checking. Page reloads on every navigation.

**v2 approach:** React 18 + TypeScript + Vite. TanStack Query for server state. React Router for client-side navigation. Tailwind CSS for styling.

**What v2 does better:**
- Type safety across the entire frontend (TypeScript catches bugs at compile time)
- SPA navigation (no page reloads, instant transitions)
- Component reuse (React components vs Jinja2 macros/includes)
- Build-time optimization (Vite tree-shaking, code splitting)
- Vite dev server with HMR (instant feedback during development)
- Proxy configuration for API calls (no CORS issues in dev)

**What v1 did well:**
- Zero build step — edit HTML, refresh browser, done
- Simpler mental model (server renders HTML, client displays it)
- Works without JavaScript enabled
- Smaller payload for simple pages

**Tradeoff:** v2 adds build complexity and a Node.js dependency, but the annotation UI needs the interactivity that React provides (keyboard shortcuts, real-time updates, complex state).

---

#### Task 0.6: Docker Compose v2 Stack

**v1 approach:** Single `docker-compose.yml` with 10+ services, 4 profiles (cpu, gpu, selfhosted, superbio). MongoDB, Redis, MinIO, Flask, workers, PINES, Prometheus, nginx. Missing `depends_on` for workers, no healthchecks on some services.

**v2 approach:** Separate `docker-compose.v2.yml` with just infrastructure (PostgreSQL, Redis, MinIO). All services have healthchecks. Application services will be added later.

**What v2 does better:**
- Healthchecks on every service from day one
- PostgreSQL over MongoDB: proper schema migrations (Alembic), ACID transactions, JSONB for flexible data
- Cleaner separation: infrastructure services separate from application services
- Simpler initial stack (3 services vs 10+)

**What v1 did well:**
- Profile system (cpu/gpu/selfhosted/superbio) for different deployment targets — should be replicated in v2
- Worker scaling via WORKER_SCALE env var

**Known v1 issues being fixed:**
- Workers could start before DB was ready (missing depends_on) — v2 uses healthcheck conditions
- worker-ops hardcoded to scale: 1 — v2 uses unified worker pool

---

## Architectural Decisions Log

| Decision | Rationale | Risk | Mitigation |
|----------|-----------|------|-----------|
| FastAPI over Flask | Async-native, Pydantic-first, OpenAPI auto-docs, unifies with PINES | Team needs to learn async patterns | FastAPI has excellent docs; async SQLAlchemy is mature |
| PostgreSQL over MongoDB | ACID, migrations, relational integrity, JSONB for flexibility | Requires schema design upfront | JSONB columns for variable metadata; Alembic for evolution |
| React over Jinja2 | Rich annotation UI needs interactivity | Adds frontend build complexity | Vite makes this fast; TypeScript catches errors early |
| JWT over sessions | Stateless auth, API-friendly | Token revocation is harder | Redis blacklist for revoked tokens; short-lived access tokens |
| Unified worker pool | Fewer containers, simpler ops | Queue starvation risk | ARQ queue priorities; separate queues in same worker |
| S3-compatible abstraction | Works with AWS S3, MinIO, GCS | Lowest-common-denominator API | boto3 S3 API is the de facto standard |

---

## Metrics (Updated Per Phase)

| Metric | v1 | v2 (so far) | Notes |
|--------|-----|-------------|-------|
| Backend lines of code | ~5,800 (core) + ~41,000 (evaluation) | ~60 | Just scaffolding so far |
| Frontend lines of code | 19 templates (~2,000 est.) | ~30 | Just scaffolding |
| Test lines | ~1,962 | 0 | Tests coming in Task 0.3 |
| Docker services | 10+ | 3 (infra only) | App services added later |
| Config sources | 3 (was), 1 (after Phase 1 fix) | 1 (pydantic-settings) | Single source of truth |
| Database backends | 2 (MongoDB + SQLite) | 1 (PostgreSQL) | Simpler, JSONB for flexibility |

---

## What Claude Did Well

- Clean project structure from the start (no god modules)
- Proper async patterns (asynccontextmanager lifespan, async SQLAlchemy)
- Pydantic-settings for config (type-safe, validated, documented)
- Healthchecks on all Docker services
- TypeScript configured from day one (not bolted on later)
- Vite proxy for seamless API development

## What Claude Could Improve

- (To be updated as implementation progresses)

---

*Last updated: Phase 0, Tasks 0.1, 0.4, 0.6 complete*
