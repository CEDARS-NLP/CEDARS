# Why CEDARS v2: Technical Rationale

## The Problem with v1

CEDARS v1 was built as a research prototype — a single-project Flask app with MongoDB, server-rendered HTML, and a bolt-on LLM integration. It worked for small studies, but we hit hard limits as requirements grew.

---

## 1. Codebase Complexity

**v1:** Two files contained most of the application logic:
- `db.py` — 2,400 lines mixing database queries, business logic, NLP coordination, and queue management
- `ops.py` — 1,300 lines with business logic embedded directly in route handlers

Circular imports between `database.py`, `db.py`, `nlpprocessor.py`, and `api.py` meant changes in one area frequently broke another. No dependency injection — everything relied on global state, making unit testing impractical.

**v2:** Each domain is self-contained (models, schemas, service, router). Business logic lives in service modules, not route handlers. Dependency injection via FastAPI makes testing straightforward — 140+ tests run in under a minute against an in-memory database.

---

## 2. Frontend Limitations

**v1:** Jinja2 templates with vanilla JavaScript. Every user action required a full page reload. The annotation interface couldn't support:
- Keyboard-driven review (essential for reviewing thousands of annotations efficiently)
- Real-time progress updates during pipeline runs
- Rich interactive components (collapsible note context, inline evidence highlighting)

**v2:** React + TypeScript SPA with shadcn/ui components. Keyboard shortcuts for annotation review (A = no event, E = set event date, arrow keys = navigate). WebSocket updates show pipeline progress in real-time. The UI is responsive and fast — no page reloads.

---

## 3. Single-Tenant Architecture

**v1:** One CEDARS instance = one project. Running three studies meant deploying three separate instances, each with its own MongoDB, Redis, and worker processes. No shared user management, no way to compare across projects.

**v2:** Multi-tenant platform. One instance supports unlimited projects with role-based access control:
- **Admin** — full control over project configuration, data, and evaluation
- **Annotator** — review annotations, submit judgments
- **Viewer** — read-only access to data and results

Users see only the projects they belong to. This is essential for institutional deployment at MSK and for distributing CEDARS to other institutions.

---

## 4. No Unified Evaluation Framework

**v1:** PINES/BERT had no evaluation framework at all — you configured it and hoped it worked. The LLM evaluation that was added later was completely separate, with no way to:
- Evaluate on a sample before running on the full cohort
- Compare LLM vs PINES accuracy on the same patients
- Track evaluation metrics over time

**v2:** Unified evaluation session workflow that works the same for any predictor type:

```
Configure search queries + LLM prompt
    → Run on sample (100 patients)
    → Clinician reviews sample results
    → See accuracy/precision/recall/F1
    → Commit & run on full cohort
    → Annotations appear incrementally for review
```

This means you can evaluate a GPT-4o prompt, an Ollama model, and PINES on the same sample and compare them side-by-side before committing resources to a full run.

---

## 5. Database Limitations

**v1:** MongoDB — no schema enforcement, no foreign keys, no migrations. Data integrity relied entirely on application code. Schema changes required manual scripts with no rollback capability.

**v2:** PostgreSQL with SQLAlchemy + Alembic migrations. Every schema change is versioned and reversible. Foreign keys enforce data integrity at the database level. JSONB columns provide flexibility where needed (config snapshots, evidence metadata) without sacrificing relational guarantees.

---

## 6. Background Job Architecture

**v1:** RQ with two separate worker types (`worker-task` and `worker-ops`). The ops worker was hardcoded to a single instance, creating a bottleneck. Workers were synchronous, blocking on I/O during LLM API calls.

**v2:** ARQ (async Redis queue) with a unified worker pool. Workers are async-native, so they don't block while waiting for LLM responses. A single worker can process multiple patients concurrently. Queue routing replaces the need for separate worker types.

---

## Could We Fix v1 Instead?

Technically, yes. But every fix converges toward what v2 already is:

| Fix needed in v1 | What it actually means |
|---|---|
| Refactor db.py/ops.py into services | Rewrite the backend — same result as v2 |
| Add React annotation UI | Build the same frontend v2 already has |
| Add multi-tenancy to MongoDB | Add project_id scoping to every query, build RBAC from scratch |
| Add unified evaluation | Build it from scratch — v2 already has it working |
| Switch to PostgreSQL for data integrity | The database migration v2 already did |
| Make workers async | Requires async framework — i.e., FastAPI instead of Flask |

Refactoring v1 to meet current requirements would take longer than finishing v2, with higher regression risk and the same end result.

---

## Where v2 Stands Today

| Component | Status |
|---|---|
| Auth + user management | Done |
| Multi-project CRUD + RBAC | Done |
| Data upload + ingestion (CSV, 124K+ notes tested) | Done |
| LLM classification pipeline | Done |
| Evaluation session workflow (sample → review → commit → full run) | Done |
| Annotation review UI (keyboard-driven, patient-first) | Done |
| Pipeline re-run after cancel/completion | Done |
| Incremental annotation creation (review while pipeline runs) | Done |
| Export | Done |
| PINES integration | Deferred (straightforward — same predictor interface) |

The core workflow is end-to-end functional. Remaining work is integration polish, not missing architecture.
