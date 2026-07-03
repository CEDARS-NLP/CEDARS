# CEDARS v2 Backend — Code Review Remediation Plan

**Date:** 2026-07-02
**Status:** Phases 1 + 0 + 2 + 3 DONE; Phase 4 partial
**Source:** Full backend review (4 parallel reviewers: DRY, Postgres-portability, correctness, testing)
**Trigger:** A single bug (LLM `api_base`) had 4 copies; a schema-casing bug crashed prod but passed tests. Both point to systemic issues: duplication and SQLite-only testing.

## Progress (2026-07-02, autonomous session)

- **Phase 1 DONE** (commit 64d13687): Postgres test path (testcontainers or CI
  service container, schema built from Alembic migrations not create_all) +
  `.github/workflows/backend-v2.yml` (SQLite + Postgres jobs, py3.12/uv). Running
  the suite on Postgres immediately caught real prod bugs SQLite hid.
- **Phase 0 DONE** (commits b41a98a5, 17a4116a, 3d9432f8):
  - Migration f8a1c2d3e4b5: annotations table was missing 5 model columns
    (pipeline_run_id, patient_task_id, predicted_reasoning, reviewer_label,
    reviewer_notes) → annotation review/stats broken on Aurora. Also converts
    review_status enum→VARCHAR to match the model.
  - predicted_label == "1" → == 1 (int/str, 4 sites).
  - ingestion audit NameError (total_rows → inserted_rows).
  - Verified: the OTHER 6 enums (ConnectorType, IngestionStatus, PatientStatus,
    UserRole, PredictorType, AuditAction) PASS on Postgres — stored uppercase and
    bound uppercase, internally consistent. Enum approach = **B** confirmed
    empirically: do NOT add values_callable to them (would break them).
  - Test FK-seeding (seed_project_and_user helper) so model unit tests pass on PG.
- **Phase 4 partial** (commit 3d9432f8): list_patients bounds, Redis probe logging.
  Still TODO: N+1 note fetch (evaluation/service.py:622 — deferred, needs
  end-to-end run to verify safely), cancellation-race SELECT FOR UPDATE, unbounded
  schema list inputs, Redis leak async-context.
- **Full suite: 323 passed on Postgres, all passing on SQLite.**

Decisions locked (autonomous): enum approach **B**; keep create_all for local dev,
tests use migrations; committed landed fixes.

---

## Meta-findings (why bugs kept reaching production)

1. **DRY violations** — one bug lives in N places. LLM helpers ×4, CRUD+soft-delete ×8, JSON-parse ×3, 404 handlers ×12. The Bedrock fix took 4 separate edits and *still* missed one (`classifier.py`), which re-broke "run on sample."
2. **Tests use SQLite + `create_all`; prod uses Postgres + Alembic.** An entire class of bug (enum casing, int/str comparison, FK strictness, migration drift) is structurally invisible until deploy. **Highest-leverage fix.**

Fixes already landed this session (context): LLM `_connection_kwargs` Bedrock guard ×4 files; `PipelineRunStatus`/`PatientTaskStatus` `values_callable`; S3 config guard; project LLM clear-field logic; nginx upstream. These are in the working tree, **uncommitted**.

---

## Phase 0 — Immediate crashers (P0, hours)

Fix + deploy ASAP; these crash on Postgres today.

| # | Bug | Location | Fix |
|---|-----|----------|-----|
| 0.1 | Undefined `total_rows` — **every successful ingestion crashes** at audit log | `connectors/service.py:212` | `total_rows` → `inserted_rows` |
| 0.2 | `predicted_label == "1"` (int col vs str) — same class as stats 500 | `annotations/query_service.py:79`; `annotations/review_service.py:208,234,308` | Compare to int `1` |
| 0.3 | `annotations/stats` int/str 500 (already identified) | annotations stats query | Compare `predicted_label` to int |
| 0.4 | 6 enums name≠value (latent PG crash) | ConnectorType, IngestionStatus, PatientStatus (`connectors/models.py`); UserRole (`auth/models.py`); PredictorType (`predictors/models.py`); AuditAction (`audit/models.py`) | Apply `_enum_column` (values_callable) — but see Phase 2 decision on approach |

**Verification gap:** none of these are caught by the current SQLite suite. Phase 3 must land to prevent regression.

---

## Phase 1 — Postgres in CI (P0, highest leverage)

Without this, every Phase 0/2 fix is unverified and regressions recur.

1. **Add testcontainers Postgres fixture** (`tests/conftest.py`) that runs **Alembic migrations** (not `create_all`) — this catches both enum casing AND create_all-vs-migration drift.
2. **Gate by env var** (`CEDARS_USE_POSTGRES_TESTS=1`) so local SQLite runs stay fast; PG runs in CI.
3. **Fix the stale CI** (`.github/workflows/ci.yml`): currently Python 3.9 + Poetry + MongoDB env vars (all v1 leftovers). Update to Python 3.12 + `uv` + Postgres service container.
4. **Reconcile `create_all` vs Alembic** — decide one source of truth. Recommend: tests and prod both use migrations; keep `create_all` only for throwaway local dev, or drop it. The divergence is the root of the enum bug.

Dep: `testcontainers[postgres]>=4.0` in dev group.

---

## Phase 2 — Enum handling, done once and correctly (P1) ✅ DONE (2026-07-02)

**Approach B, confirmed empirically.** Landed commit `611b33ae`:
`tests/test_enum_roundtrip.py` — a cross-backend guard that inserts AND reads
back *every member of every persisted enum* on both SQLite (`create_all`) and
Postgres (Alembic migrations). 326 passed on both backends.

**What the round-trip test proved about the "3 miscased ALTER migrations":**
they are *not* live crashers, so no migration rewrite was done (rewriting
already-applied history would be an ad-hoc DB patch — forbidden by CLAUDE.md).

- `jobstatus`/`jobtype` native types were created UPPERCASE and `BackgroundJob`
  binds the enum NAME (no `values_callable`), so the `CANCELLED` (b5f066242811)
  and `INGESTION` (c3a1e7f82d9b) ALTERs added *matching* uppercase labels →
  correct, round-trip PASS.
- `patienttaskstatus` was created lowercase and the model binds the lowercase
  value via `enum_column` → valid. Migration `ec642691720e` added a
  `NO_MATCH` label; the model's `no_match` value round-trips PASS. (The stray
  uppercase label is harmless cruft, not corruption.)
- Dedicated regression guards for both ALTER-added members
  (`PatientTaskStatus.NO_MATCH`, `JobStatus.CANCELLED`) are in the test file.

**Teeth verified:** mutating `enum_column` to bind member *names* instead of
*values* fails the sweep on Postgres exactly as the original prod bug did.

Below is the original decision analysis, preserved for context:

**Decision was:** the enums split into two groups (verified against live Aurora):
- **Stored UPPERCASE** (work today by luck): auditaction, connectortype, ingestionstatus, jobstatus, jobtype, judgmentvalue, nlpjobstatus, patientstatus, predictortype, projectrole, reviewstatus(varchar), userrole.
- **Stored lowercase** (crash): pipelinerunstatus, patienttaskstatus (already fixed via `values_callable`).
- **Stale/wrong values**: sessionstatus PG type has `SAMPLING/RUNNING` (v1); code has `DRAFT/COMMITTED/DISCARDED` (v2 uses VARCHAR — OK, but the old enum type lingers).
- **Migrations added UPPERCASE to lowercase types**: `CANCELLED` (b5f066242811), `INGESTION` (c3a1e7f82d9b), `NO_MATCH` (ec642691720e) → duplicate-label corruption.

**Recommended approach (pick one in review):**
- **(A) Standardize on `values_callable` everywhere** + a migration to normalize all PG enum types to lowercase values. Cleanest long-term; one convention. Requires a data migration for existing rows.
- **(B) Leave working uppercase enums alone; only fix the lowercase-stored ones** (already done) + fix the 3 miscased ALTER migrations. Lowest risk, but keeps two conventions.

Add a **cross-backend enum test** (asserts every enum round-trips identically on SQLite + Postgres) so this can never silently diverge again.

---

## Phase 3 — DRY consolidation (P1–P2) ✅ DONE (2026-07-02)

Landed as 4 commits on `feature/v2-platform`, each a subset of a tree that
passed the full suite on **both** SQLite and Postgres (323 each):

| Commit | Concept | Copies | New home |
|--------|---------|--------|----------|
| `72ae7475` | CRUD + soft-delete (`select().where(project_id, deleted_at.is_(None))`) | ~8 | `app/common/crud.py`: `get_scoped`/`list_scoped`/`soft_delete` |
| `fbb327ff` | LLM plumbing (`_litellm_model`, `_connection_kwargs`, JSON extract, token usage) | 4 | `app/llm/client.py` — `complete`/`complete_json`; call sites keep only prompts + per-call params |
| `fbb327ff` | JSON-from-LLM-response parse | 3–4 | folded into `app/llm/client.py:extract_json` (depth-matched, handles arrays + trailing commas) |
| `8733580f` | 404 helper | 47 raises / 9 routers | `app/common/errors.py:raise_not_found()` |
| `4ed493ef` | Pagination response wrapper | 2 | `app/common/schemas.py:PaginatedResponse[T]` |
| `72ae7475` | `now_utc()` timestamp helper | ~30 | `app/common/utils.py` |
| `72ae7475` | `_enum_column` / db types | — | `app/common/db_types.py` (promoted from pipeline/models.py, re-exported as `_enum_column`) |

Net ~-274 lines (LLM files alone: ~-370).

**Deliberate deviation:** did NOT add a `SoftDeleteMixin`. The `deleted_at`
columns have per-model `sa_column` declarations; redeclaring them via a mixin
would risk exactly the schema/migration-drift bug class Phase 1 exists to
catch, for little gain. Extracted the *query* logic only — zero schema impact.
`classify_patient`/`suggest_queries`/`generate_search_patterns` re-raise
`ValueError` (parse failures) before their catch-all so error contracts held;
`predictors/llm._parse_response` keeps its graceful no-raise fallback.

---

## Phase 4 — Robustness (P2)

| Issue | Location | Fix |
|-------|----------|-----|
| N+1 note fetch per patient | `evaluation/service.py:622-637` | Single `.where(Note.patient_id.in_(ids))`, group in Python |
| Race in cancellation check | `worker.py:164-171` | `SELECT FOR UPDATE` on the run row (mirror `orchestrator._check_no_active_run`) |
| Unbounded list/dict inputs | `pipeline/schemas.py:13`, `evaluation/schemas.py:17,22` | Pydantic `max_length` on lists |
| Missing pagination bounds | `connectors/service.py:687` | `limit: int = Field(le=1000)`, `offset: ge=0` |
| Silent `except Exception: pass` | `orchestrator.py:517` | Log at WARNING |
| Redis connection leak on error | `connectors/service.py:249-269` | `async with create_pool(...)` |
| Cross-project resource access | eval/pipeline routers | Assert fetched resource `.project_id == path project_id` |
| Databricks SQL f-string LIMIT/OFFSET | `connectors/databricks.py:65,72,87` | Parameterize (keep identifier validation) |

---

## Coverage gaps (untested modules)

`app/common/*`, `dependencies.py`, all WebSocket handlers (`*/ws.py`), `connectors/databricks.py`, light coverage on `admin/service.py`, `audit/service.py`. Add tests as each phase touches them.

---

## Recommended sequence

1. **Phase 1 (Postgres CI)** — first, so everything after is verified.
2. **Phase 0 (crashers)** — with PG tests now catching them.
3. **Phase 2 (enums)** — decide approach A vs B.
4. **Phase 4 (robustness)** — independent, parallelizable.
5. **Phase 3 (DRY)** — last, largest churn, guarded by PG suite.

Phases 0/2/4 fan out cleanly to parallel agents (independent files). Phase 3 is best done as one coordinated refactor.

## Open decisions for reviewer
1. ~~Enum approach A vs B~~ — **RESOLVED: approach B**, confirmed empirically by
   the Phase 2 round-trip test (611b33ae). No migration rewrite needed.
2. `create_all` fate: drop entirely (migrations everywhere) or keep for local-only?
   (Still open; tests already use migrations on the PG path.)
3. ~~Commit the already-landed session fixes now~~ — done (Phase 0 commits).
