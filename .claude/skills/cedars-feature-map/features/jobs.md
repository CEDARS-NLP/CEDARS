# Jobs

Last verified: cef611321063 on 2026-10-05 (source + live)

The Jobs area covers background work: pipeline runs (one PipelineRun per full evaluation pipeline), BackgroundJobs (ingestion, NLP, prediction) and the ARQ worker that runs them. The "Job dashboard" page (sidebar "Jobs", every role) lists runs, shows whether the worker is alive and offers Cancel, Retry failed and Rerun. Three WebSocket endpoints stream progress. Only the ingestion banner on the Data page uses one, and all other pages poll. The two pipeline sockets crash on any real run. Overall: **beta**. Listing, stats and worker status work. It also has known security defects, tracked privately (not in this public repo). "Retry failed" always returns 400 for the runs the UI creates, and a failure shows no message.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| jobs-page | "Job dashboard" page: run cards, newest first, polled every 5 s; empty state "No pipeline runs yet" | beta | UI+API | 8197dee8 | 2026-10-05 (empty state) | `frontend/src/projects/JobDashboardPage.tsx:310-344`, `App.tsx:124`, `AppSidebar.tsx:23`, `backend/app/pipeline/router.py:230`, `tests/test_pipeline_orchestration.py::TestRunManagement::test_list_runs`. No frontend tests |
| jobs-queue-status | `GET /pipeline/queue`: "Worker online/offline", "N in queue", pipeline and job counts, polled every 5 s | beta | UI+API | 3d9432f8 | 2026-10-05 | `pipeline/orchestrator.py:478-540`, `router.py:219`, `JobDashboardPage.tsx:247-297`. No test covers `/queue` |
| jobs-run-stats | Expanded card: Total / Queued / Processing / Completed / Failed / No Match, plus a progress bar while active. Eval runs are read from PatientResult | beta | UI+API | ad104d90 | not driven | `orchestrator.py:368-409` (fallback `:391-404`), `router.py:257`, `JobDashboardPage.tsx:55-59`, `:161-184`, `test_pipeline_orchestration.py::TestRunManagement::test_get_run_stats` |
| jobs-patient-tasks | "Patient tasks" table (Patient / Status / Error / Duration), first 50 rows only | beta | UI+API | ad104d90 | not driven | `orchestrator.py:440-475`, `router.py:288`, `JobDashboardPage.tsx:68-73`, `:186-225`, `TestRunManagement::test_get_run_tasks` |
| jobs-config-snapshot | "Config snapshot" prints `run.config_snapshot` as JSON | beta | UI+API | f47a09a5 | not driven | `JobDashboardPage.tsx:227-233`, `pipeline/schemas.py:63`, `evaluation/service.py:1097-1109`, `:1174-1182`. Known security defect (tracked privately) |
| jobs-cancel-run | "Cancel" on an active run (admin API). A linked eval session becomes DISCARDED | beta | UI+API | a5b72355 | not driven | `orchestrator.py:203-236`, `router.py:306`, `TestRunManagement::test_cancel_run` |
| jobs-retry-failed | "Retry failed" re-queues failed PatientTask rows (admin API) | stub | UI+API | 43250aa2 | not driven | `orchestrator.py:310-342` vs `:391-404`, `router.py:340`, `JobDashboardPage.tsx:135-146`. No test |
| jobs-rerun | "Rerun" on a terminal run. Eval runs delegate to `evaluation.service.rerun_pipeline` | beta | UI+API | a5b72355 | not driven | `orchestrator.py:239-307`, `evaluation/service.py:1411-1412`, `router.py:324`, `JobDashboardPage.tsx:147-158`. No test |
| jobs-retry-stalled | `POST /pipeline/retry-stalled?stale_minutes=10` re-queues PatientTask rows stuck in PROCESSING; returns `{"requeued":N}` | api-only | API | ad104d90 | not driven | `router.py:358`, `orchestrator.py:412-437`, `TestRunManagement::test_retry_stalled` |
| jobs-run-metrics | `GET /pipeline/runs/{id}/metrics`: calibration metrics. No page calls it | api-only | API | 6cdbc989 | not driven | `router.py:272`, `tests/test_pipeline_metrics.py::test_compute_metrics` |
| jobs-run-sample-full-api | `POST /pipeline/events/{id}/run-sample` and `/run-full` (EventConfig runs that track work in PatientTask). Nothing in the UI calls them | api-only | API | ad104d90 | not driven | `router.py:179`, `:200`, `TestRunSample`, `TestRunFull`, `TestConcurrentRunRejection` in `test_pipeline_orchestration.py` |
| jobs-worker | ARQ worker: 8 functions, `max_jobs=10`, `job_timeout=3600`, `max_tries=1`, heartbeat key `arq:queue:health-check` | beta | worker | cef61132 | 2026-10-05 | `backend/app/worker.py:440-457`, `stack logs worker`: "Starting worker for 8 functions", `run_ingestion_job` 1.65 s. `tests/test_worker.py` covers only dispatch |
| jobs-worker-orphan-recovery | On worker start, RUNNING runs go back to QUEUED, their PROCESSING PatientResults go back to queued, and the run is re-enqueued | beta | worker | a5b72355 | 2026-10-05 | `worker.py:384-437`. Live: `stack restart worker` mid-run → "Auto-recovered orphaned pipeline run … (1 stuck rows reset)" 3 s later, run finished 5/5, the in-flight patient was classified twice. No test |
| jobs-worker-export | `run_export_job` | stub | worker | 32e9e99f | not driven | `worker.py:64-66` returns `{"status":"not_implemented"}` |
| jobs-ws-job-progress | `/ws/projects/{pid}/jobs/{job_id}`: progress for one BackgroundJob, polled every 1 s. The Data page ingestion banner uses it | beta | UI+WS | 1f5dfb8d | 2026-10-05 (terminal message only) | `backend/app/jobs/ws.py:14-46`, `components/JobBanner.tsx:64-93`, `DataPage.tsx:918-929`, `main.py:134`. No test |
| jobs-ws-pipeline-progress | `/ws/projects/{pid}/pipeline/{run_id}`: run counters plus stats | stub | WS | a5b72355 | 2026-10-05 FAIL | `pipeline/ws.py:34-40`: `MissingGreenlet` on every existing run (live). Bad IDs work. No frontend consumer, no test |
| jobs-ws-eval-progress | `/ws/projects/{pid}/evaluation/{sid}`: full-pipeline progress for a committed session | stub | WS | a5b72355 | 2026-10-05 FAIL | `evaluation/ws.py:31-34`: `MissingGreenlet` on every existing session (live). Bad IDs work. No frontend consumer, no test |

Why the grades:
- **Nothing is `stable`.** The dashboard has two known defects (a security defect tracked privately, and no role gating). `/queue`, retry, rerun, orphan recovery and the WebSockets have no tests.
- **jobs-retry-failed is `stub`.** The UI only creates eval-session runs, and those track work in PatientResult, not PatientTask. The button appears whenever `stats.failed > 0`, but the endpoint finds no PatientTask rows and returns 400 "No failed tasks to retry" (`orchestrator.py:318-326`). It works only for runs started through the API-only `run-sample` / `run-full`.
- **Sample run cards never appear from the UI.** The Step 3 sample LLM run creates no PipelineRun, so UI users only ever see "Full run" cards (`evaluation/service.py:1174-1182`).

## How to get to it (user POV)

1. Log in, then open a project from "Projects".
2. Click "Jobs" in the sidebar. Every role sees it.
3. The page shows heading "Job dashboard" and the subtitle "Monitor pipeline runs, cancel active jobs, and retry failures."
4. The status card shows "Worker online" or "Worker offline", "N in queue" (only when above 0), and two counts: "Pipeline: N done · N failed" and "Jobs: N done · N failed". An "N active" badge appears when something is active.
5. Run cards appear after an evaluation session is committed and its full pipeline starts (see `evaluation-run.md`). Each card is a toggle showing "Full run", a status badge and "N patients · vN · <date>". Click it to see the stats grid, "Patient tasks" and "Config snapshot".
6. The card buttons: "Cancel" while queued or running; "Retry failed" when the run failed or has failed patients; "Rerun" when completed, failed or cancelled.
7. Ingestion progress is not on this page. It is the "Ingestion running…" banner on the Data page (`JobBanner.tsx:136`).

## Driving it with control-cedars

Preconditions: the baseline. A fresh seed has no pipeline runs and one completed INGESTION BackgroundJob. Every bullet that needs a run first needs a committed evaluation session with a full pipeline dispatched (`evaluation-run.md`). Get IDs with `$CC db query "select id, status, run_type from pipeline_runs order by created_at desc limit 1"` and `$CC db query "select id, job_type, status from background_jobs order by created_at desc limit 1"`.

- **jobs-page**: viewer opens the dashboard from the sidebar →
  ```
  $CC browser run - --as viewer --save jobs-page <<'EOF'
  [{"goto":"/projects/{project}"},
   {"click":{"role":"link","name":"Jobs","exact":true}},
   {"expect_url":"/jobs$"},
   {"expect":{"role":"heading","name":"Job dashboard"}},
   {"expect_text":"Monitor pipeline runs, cancel active jobs, and retry failures."},
   {"expect_text":"No pipeline runs yet"},
   {"screenshot":"empty"}]
  EOF
  ```
  → exit 0 on a fresh seed. Driven 2026-10-05 as `browser snapshot /projects/{project}/jobs --as viewer --wait-text 'Job dashboard'`. Same data via the API: `$CC api GET /projects/{project}/pipeline/runs --as viewer` → 200 `[]`.
- **jobs-queue-status**: `$CC api GET /projects/{project}/pipeline/queue --as admin --save jobs-queue` → 200, `worker_active: true`, `arq_queued: 0`, `background_jobs.completed: 1` after seed (driven 2026-10-05). `--as anon --expect 401` → `{"detail":"Not authenticated"}` (driven). The UI shows "Worker online".
- **jobs-run-stats / jobs-patient-tasks / jobs-config-snapshot**: expand the newest run card →
  ```
  $CC browser run - --as admin --save jobs-run-card <<'EOF'
  [{"goto":"/projects/{project}/jobs"},
   {"expect":{"role":"heading","name":"Job dashboard"}},
   {"click":{"role":"button","name":"Full run","nth":0}},
   {"expect_text":"No Match","exact":true},
   {"expect_text":"Patient tasks"},
   {"expect_text":"Config snapshot"},
   {"screenshot":"expanded"}]
  EOF
  ```
  → exit 0. The stats should match `$CC api GET /projects/{project}/pipeline/runs/<run_id>/stats --as viewer` (`total`, `completed`, `failed`, `no_match`).
- **jobs-cancel-run**: with a run active (slow it down first with `$CC llm mode slow`, 20 s per call), click Cancel →
  ```
  $CC browser run - --as admin --save jobs-cancel <<'EOF'
  [{"goto":"/projects/{project}/jobs"},
   {"click":{"role":"button","name":"Cancel","exact":true}},
   {"expect_text":"cancelled"}]
  EOF
  ```
  → the badge reads "cancelled", and `$CC db query "select status from evaluation_sessions_v2 order by created_at desc limit 1"` → `discarded`. Restore with `$CC llm mode normal`. API role check: `$CC api POST /projects/{project}/pipeline/runs/<run_id>/cancel --as viewer --expect 403` → `{"detail":"Insufficient permissions"}`.
- **jobs-retry-failed**: run with `$CC llm mode fail` so patients fail, then `$CC api POST /projects/{project}/pipeline/runs/<run_id>/retry-failed --as admin --expect 400` → `{"detail":"No failed tasks to retry"}`, even though the stats show `failed > 0`. Clicking "Retry failed" in the UI shows nothing (the defect). Once fixed, expect 200 and the failed PatientResults back at `queued`.
- **jobs-rerun**: on a completed run, `$CC api POST /projects/{project}/pipeline/runs/<run_id>/rerun --as admin` → 200 with a new run, which `GET .../pipeline/runs` lists. On a cancelled run (session DISCARDED) → `--expect 400`: "Session must be in committed or completed state to re-run". The UI shows nothing.
- **jobs-rerun (role gating)**: a viewer sees the admin-only buttons →
  ```
  $CC browser run - --as viewer --save jobs-viewer-buttons <<'EOF'
  [{"goto":"/projects/{project}/jobs"},
   {"expect":{"role":"button","name":"Rerun","exact":true}}]
  EOF
  ```
  → exit 0 on a terminal run proves the defect. It should fail once the buttons are hidden by role.
- **jobs-retry-stalled**: `$CC api POST '/projects/{project}/pipeline/retry-stalled?stale_minutes=1' --as admin` → 200 `{"requeued":0}` for eval runs (PatientResult rows are never touched). `--as annotator --expect 403`.
- **jobs-run-metrics**: `$CC api GET /projects/{project}/pipeline/runs/<run_id>/metrics --as viewer` → 200 with zeros until reviews exist.
- **jobs-run-sample-full-api**: SKIP-able. It needs a legacy EventConfig, and the UI never creates one outside an eval commit. `$CC api POST /projects/{project}/pipeline/events/<event_config_id>/run-sample --as admin` → 200, then `tasks` lists PatientTask rows.
- **jobs-worker**: `$CC stack logs worker --grep 'Starting worker'` → "Starting worker for 8 functions: run_nlp_job, …" (driven). `$CC api GET /projects/{project}/pipeline/queue --as admin` → `worker_active: true`.
- **jobs-worker-export**: SKIP, because nothing enqueues it. `grep -rn run_export_job backend/app` finds only its definition and its registration (`worker.py:64-66`, `:445`). `$CC stack logs worker --grep 'Starting worker'` lists it among the registered functions. Export runs synchronously in the request (`export.md`).
- **jobs-worker-orphan-recovery**: `$CC llm mode slow`, start a full run, wait for `$CC db query "select status from pipeline_runs order by created_at desc limit 1"` → `running`, then `$CC stack restart worker` → `$CC stack logs worker --grep 'Auto-recovered orphaned pipeline run'` → one line with the run ID, and the run finishes. `$CC llm mode normal` afterwards. ARQ cancels in-flight jobs on SIGTERM (`job_completion_wait` defaults to 0), so the run stays `running` until the new worker recovers it.
- **jobs-ws-job-progress**: `$CC ws /ws/projects/{project}/jobs/<job_id> --as admin --seconds 5` → `{"type":"completed","job_id":…,"status":"completed","progress":100,…}` (driven 2026-10-05). A bad ID returns `{"type":"error","detail":"Job not found"}` (driven).
- **jobs-ws-pipeline-progress / jobs-ws-eval-progress**: `$CC ws /ws/projects/{project}/pipeline/<run_id> --as admin --seconds 5 --save ws-pipeline` → expected: one message with `total_patients`, `processed_patients` and stats, then close on terminal. `$CC ws /ws/projects/{project}/evaluation/<session_id> --as admin` → expected: `completed` once queued and processing reach 0. Actual (2026-10-05, a real running run and its session): 0 messages, close 1000, exit 1. `$CC stack logs backend --grep MissingGreenlet` shows the traceback. Bad IDs return "Run not found" and "Session not found" (driven).

## Gotchas

- **There is no annotations WebSocket.** CLAUDE.md lists "WebSocket (job progress, annotations)", but `main.py:134-136` mounts only the jobs, pipeline and evaluation sockets. Annotation pages poll.
- **Known security defects** affect `jobs-config-snapshot` and the three WebSocket endpoints. Details are tracked privately, not in this public repo.
- **Buttons ignore role and errors.** Cancel, Retry failed and Rerun render for viewers and annotators. The API answers 403 (`router.py:306`, `:324`, `:340`). None of the three mutations has `onError` (`JobDashboardPage.tsx:76-92`), so 400 and 403 responses are silent.
- **Cancel discards the evaluation session** (`orchestrator.py:218-233`; `evaluation/service.py:1287-1312` does the same from the session page). After that, "Rerun" on the cancelled card always gets 400 (`evaluation/service.py:1411-1412`), silently.
- **A QUEUED run whose enqueue failed is stuck.** `_enqueue_pipeline_run` / `_enqueue_eval_pipeline_run` only log on failure (`orchestrator.py:45-57`, `evaluation/service.py:42-54`). Orphan recovery only picks up RUNNING runs (`worker.py:401-404`), and Rerun rejects active runs. The only way out is Cancel, which discards the session. BackgroundJobs stuck in PENDING or RUNNING are never recovered either.
- **"Worker online" can be stale for up to an hour.** `WorkerSettings` sets no `health_check_interval` (`worker.py:440-457`), so ARQ refreshes the key hourly with a 3601 s TTL. A graceful stop deletes the key; a SIGKILL or OOM leaves it. During that window ingestion still enqueues to ARQ (`connectors/service.py:262`) and nothing runs it. "Worker offline" also shows when Redis is down, because the probe only logs a warning (`orchestrator.py:519-522`).
- **Every worker restart or deploy cancels in-flight jobs.** ARQ's SIGTERM handler cancels running tasks (default `job_completion_wait=0`; `worker.py:440-457` does not override it). Pipeline runs left RUNNING are recovered on the next start. An ingestion, NLP or prediction BackgroundJob left RUNNING is not, and its data source stays `running`. `update-service --force-new-deployment` on the worker triggers this.
- **The pipeline WebSockets crash on real IDs.** Both handlers call `expire()` on the ORM object and then read an attribute, which makes SQLAlchemy reload it synchronously inside async code. The result is `MissingGreenlet`, and the socket closes before sending anything (`pipeline/ws.py:34-40`, `evaluation/ws.py:31-34`). The fix is `await session.refresh(obj)` instead of `expire()`. No page uses these sockets yet, so users are unaffected today.
- **A rolling worker deploy can process one run twice.** The worker service leaves `deployment_minimum_healthy_percent`/`deployment_maximum_percent` at the ECS defaults of 100/200 (`infra/cedars-v2/ecs.tf:176-190`). The new task therefore starts while the old one still runs. Its startup hook re-enqueues every RUNNING run (`worker.py:401-430`) without an ARQ `_job_id` (`evaluation/service.py:50`), so both workers process the run until the old one gets SIGTERM. This comes from reading the source. `stack restart worker` stops before it starts, so it cannot show the overlap.
- **Job counts omit cancelled.** `background_jobs` has no cancelled bucket (`orchestrator.py:532-537`).
- **The ingestion banner loses its job after the first batch.** The job is created with `result_summary={"data_source_id": …}` (`connectors/service.py:244`), and the worker replaces it with row counts (`jobs/ingestion.py:77-83`, `:116`). The status and cancel lookups filter on `data_source_id` (`connectors/service.py:323`, `:353`), so after one batch they return `null` (live: `GET .../ingest/status` → 200 `null`). JobBanner then shows the run button again and never opens the WebSocket (`JobBanner.tsx:64-65`). The 103-row sample finishes in one batch, so the banner never shows progress for it. See `data.md`.
- **JobBanner has no fallback.** `onerror` is empty, and there is no `onclose`, no reconnect and no `refetchInterval` (`JobBanner.tsx:44-47`, `:85-87`). If the socket drops, progress freezes until the page reloads. The effect depends on the inline `jobQueryKey` array (`:93`), so it can reconnect on every render.
- **WebSocket resource use.** `jobs/ws.py:27` opens a new DB session on every 1 s poll. `pipeline/ws.py:27` holds one session for the whole connection. Long runs keep a pooled connection per viewer.
- **Proxy timeouts differ.** The ALB idle timeout is 300 s (`infra/cedars-v2/alb.tf:18`). The frontend nginx `/ws/` block uses the 60 s default `proxy_read_timeout` (`frontend/nginx.conf:20-27`), but on ECS it never runs because the ALB routes `/ws/*` straight to the backend (`alb.tf:110-111`).
- **The run card toggle has no accessible name of its own and no `aria-expanded`.** Locate it by its text "Full run" and `nth` (`JobDashboardPage.tsx:104-121`). `Progress` drops `value` before Radix Root, so it has no `aria-valuenow` (`components/ui/progress.tsx:20-23`). Check progress with numbers from `/stats`.
- **Overview "Latest job" shows progress × 100.** BackgroundJob progress is already 0-100 (`jobs/ingestion.py:120`, `projects/stats.py:145`), but `ProjectOverview.tsx:573-575` multiplies it by 100, so a running job reads like "4000% complete". See `projects.md`.
- **The tasks table caps at 50 rows** (`?limit=50`, `JobDashboardPage.tsx:70`) and has no pager. The API allows up to 200 with `offset` (`router.py:288`).
- **Polling rates.** Run list and queue every 5 s (`JobDashboardPage.tsx:251`, `:313`); stats every 3 s while active (`:58`); tasks every 5 s while expanded and active (`:73`). The evaluation session page polls every 3 s while `llm_status === "running"` (`projects/evaluation/EvaluationSessionPage.tsx:46-62`).
- **Tests never exercise enqueueing.** An autouse fixture makes `arq.create_pool` raise (`tests/conftest.py:85-94`), so every test takes the "worker unavailable" branch.
