# Backend Review (`backend/`)

## Overall outcome

High-signal architecture/code review completed for `backend/` with findings prioritized by severity.

## Critical

### 1) Unsafe JWT secret default
- **File:** `backend/app/config.py`
- **Issue:** `secret_key` defaults to `"change-me-in-production"`.
- **Risk:** If not overridden, tokens can be forged.
- **Fix:** Make it required and fail startup when unset/default.

## High

### 1) Race condition in evaluation session creation
- **File:** `backend/app/evaluation/service.py`
- **Issue:** Active-session check and create are not concurrency-safe.
- **Risk:** Duplicate active sessions under concurrent requests.
- **Fix:** Add locking (`FOR UPDATE`) and/or DB uniqueness constraint for active statuses.

### 2) Race condition in pipeline run dispatch
- **File:** `backend/app/pipeline/orchestrator.py`
- **Issue:** Active-run check is not atomic with creation.
- **Risk:** Duplicate queued/running runs for one config.
- **Fix:** Lock parent row and/or add partial unique index for active statuses.

### 3) WebSocket polling DB session churn
- **File:** `backend/app/pipeline/ws.py`
- **Issue:** New DB session created every polling iteration.
- **Risk:** Connection pool pressure/exhaustion with many clients.
- **Fix:** Reuse session or redesign polling/notification path.

### 4) Non-atomic purge operation
- **File:** `backend/app/connectors/service.py`
- **Issue:** Multi-step delete path without stronger isolation.
- **Risk:** Partial deletion/orphan state on failure.
- **Fix:** Wrap related deletes in a transactional block/savepoint.

### 5) N+1 query in patient cleanup
- **File:** `backend/app/connectors/service.py`
- **Issue:** Per-patient count checks in loop.
- **Risk:** Poor performance at scale.
- **Fix:** Replace with bulk anti-join/`NOT EXISTS` delete strategy.

### 6) Worker recovery/run-state consistency risk
- **File:** `backend/app/worker.py`
- **Issue:** Recovery can requeue per-patient work without fully coherent run-state reset.
- **Risk:** Stuck/inconsistent orchestration state.
- **Fix:** Ensure run status transitions are updated atomically with patient resets.

### 7) JWT decode path loses error specificity
- **File:** `backend/app/auth/service.py`
- **Issue:** All JWT decode errors collapse into one path.
- **Risk:** Harder to distinguish expired vs invalid token flows.
- **Fix:** Handle expiration separately from invalid-signature/malformed errors.

## Medium

1. In-process fallback ingestion jobs can be orphaned on API process restart (`backend/app/connectors/service.py`).
2. Concurrent review updates need stricter race-safe predicates (`backend/app/annotations/review_service.py`).
3. Hot query path likely needs composite index on `(pipeline_run_id, status)` (`backend/app/evaluation/models.py`).
4. Missing recovery-focused tests for orphaned/stuck run scenarios (`backend/tests/`).
5. Cookie security defaults need stronger production-time validation (`backend/app/config.py`).
6. Token usage aggregation strategy may become fragile at very large scale (`backend/app/jobs/prediction.py`).

## What is already strong

- Good async discipline and session handling patterns.
- Explicit pipeline/evaluation state-machine modeling.
- Worker startup includes recovery logic.
- Broad test suite coverage footprint.
- ORM-based query construction avoids raw SQL injection patterns.

