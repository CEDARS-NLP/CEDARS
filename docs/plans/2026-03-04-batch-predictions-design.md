# Batch Predictions: Decouple Activation from Execution

**Date:** 2026-03-04
**Status:** Approved

## Problem

When a validated predictor is activated via `POST /evaluation/validated/{id}/activate`, the endpoint immediately calls `run_bulk_predictions()` synchronously within the HTTP request. This:

1. **Blocks the UI** until all predictions complete (could be minutes/hours for large datasets)
2. **Couples two distinct actions** — marking a predictor active vs. running predictions
3. **No progress visibility** — clinician has no idea how far along the run is
4. **No cancellation** — once started, it runs to completion or fails entirely
5. **All-or-nothing commit** — single transaction means no annotations are available until everything finishes

## Design

### Core Changes

**1. Decouple activation from prediction execution**

- `POST /evaluation/validated/{id}/activate` only activates the predictor config (no bulk run)
- A separate "Run Predictions" button on the Annotations page triggers prediction execution

**2. Background job via ARQ**

Prediction runs execute as ARQ background jobs using the existing `BackgroundJob` infrastructure:

- `BackgroundJob` record tracks status, progress, and results
- `JobType.PREDICTION` already exists in the enum
- Per-patient batching: group sentences by patient, commit after each patient completes
- Annotations become available for review as soon as each patient batch commits

**3. WebSocket progress updates**

Real-time progress via FastAPI WebSocket:

- Endpoint: `WS /ws/projects/{project_id}/jobs/{job_id}`
- Broadcasts after each patient batch: `{patients_processed, total_patients, current_patient_id, predictions_made, errors}`
- Frontend connects on job start, receives live updates without polling

**4. Cancellation support**

- `POST /annotations/predictions/cancel` sets a cancellation flag on the `BackgroundJob`
- Worker checks flag between patient batches — stops early if cancelled
- Annotations already committed (completed patients) are kept

**5. Prefetch next patient for review**

Frontend optimization for snappy annotation review:

- While clinician reviews current patient, background fetch loads next patient's data
- When current patient is completed, next patient renders instantly from prefetched cache
- Uses existing `GET /annotations/next-patient` endpoint

### API Changes

#### Modified Endpoints

```
POST /projects/{id}/evaluation/validated/{validated_id}/activate
  - BEFORE: activates predictor + runs bulk predictions synchronously
  - AFTER: activates predictor only, returns ValidatedPredictorResponse (no BulkRunStats)
```

#### New Endpoints

```
POST /projects/{id}/annotations/predictions/run
  - Creates BackgroundJob(PREDICTION), enqueues ARQ task
  - Returns: {job_id, status: "pending"}
  - Requires: active predictor, no running prediction job

GET  /projects/{id}/annotations/predictions/estimate
  - Returns: {sentence_count, estimated_prompt_tokens, estimated_total_tokens}
  - Reuses existing estimate_bulk_predictions() logic

GET  /projects/{id}/annotations/predictions/status
  - Returns: current/latest prediction job status + progress
  - {job_id, status, progress, patients_processed, total_patients, stats}

POST /projects/{id}/annotations/predictions/cancel
  - Sets cancellation flag on running job
  - Returns: {cancelled: true}

WS   /ws/projects/{project_id}/jobs/{job_id}
  - Real-time progress stream
  - Messages: {type: "progress", patients_processed, total_patients, ...}
  - Messages: {type: "completed", stats: {...}}
  - Messages: {type: "cancelled", stats: {...}}
```

### Backend Implementation

#### New file: `app/jobs/prediction.py`

Follows the `app/jobs/nlp.py` pattern:

```python
async def execute_prediction_job(project_id, job_db_id, session_factory=None):
    # 1. Mark job as RUNNING
    # 2. Query target sentences grouped by patient
    # 3. For each patient:
    #    a. Run predictor on all their target sentences
    #    b. Create Annotation records
    #    c. Commit batch (annotations immediately available)
    #    d. Update BackgroundJob progress
    #    e. Broadcast progress via WebSocket
    #    f. Check cancellation flag — break if cancelled
    # 4. Mark job COMPLETED (or CANCELLED)
```

#### Modified: `app/worker.py`

Replace `run_prediction_job` placeholder with real implementation.

#### Modified: `app/evaluation/router.py`

Remove `run_bulk_predictions()` call from `activate_validated_endpoint`.

#### New: `app/annotations/router.py` additions

Add prediction run/estimate/status/cancel endpoints.

#### New: WebSocket endpoint

Either in `app/annotations/router.py` or a dedicated `app/ws.py`.

### Frontend Changes

#### Annotations page

- **Run Predictions button**: Visible when active predictor exists and unannotated sentences remain
- **Confirmation dialog**: Shows token estimate, sentence count before starting
- **Progress banner**: Real-time progress bar with patients processed / total, connected via WebSocket
- **Cancel button**: Available while job is running
- **Seamless transition**: As predictions complete per-patient, annotation review queue populates

#### Evaluation page

- **"Activate & Run Predictions" → "Activate Predictor"**: Button only activates
- **Post-activation message**: Toast/banner directing user to Annotations page to run predictions

#### Annotation review (prefetch)

- When reviewing a patient, prefetch next patient's data in background
- On patient completion, render prefetched data immediately
- Fallback to normal loading if prefetch hasn't completed

### Data Flow

```
Evaluation Page                    Annotations Page
─────────────                      ────────────────
[Activate Predictor]               [Run Predictions]
       │                                  │
       ▼                                  ▼
  Set is_active=True              Create BackgroundJob
  (no predictions)                Enqueue ARQ task
       │                                  │
       │                                  ▼
       │                           ARQ Worker picks up
       │                                  │
       │                           ┌──────┴──────┐
       │                           │ Per-patient  │◄── WebSocket progress
       │                           │   batches    │    to frontend
       │                           │  (commit     │
       │                           │   each one)  │◄── Check cancel flag
       │                           └──────┬──────┘
       │                                  │
       │                                  ▼
       │                           Annotations available
       │                           for review immediately
       │                                  │
       └──────────────────────────────────┘
                                          │
                                          ▼
                                   [Review Annotations]
                                   (prefetch next patient)
```

### BackgroundJob Model

The existing `BackgroundJob` model already has everything needed:

- `job_type`: `JobType.PREDICTION`
- `status`: PENDING → RUNNING → COMPLETED/FAILED
- `progress`: 0-100 (percentage of patients processed)
- `result_summary`: JSON with prediction stats
- `error_message`: for failures

Add one field:

- `cancelled`: bool flag checked between batches

### Existing Infrastructure Used

- `BackgroundJob` model (already has `JobType.PREDICTION`)
- `ARQ worker` (already has `run_prediction_job` placeholder)
- `prediction_service.py` (reuse query logic, refactor into batched version)
- `estimate_bulk_predictions()` (reuse as-is)
