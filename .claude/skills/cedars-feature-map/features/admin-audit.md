# Admin and audit

Last verified: cef611321063 on 2026-10-05 (source + live read-only)

This area has two parts. The platform-admin endpoints (`/api/v1/admin/queues`, `/workers`, `/jobs`) report background-job counts and worker health across every project, and only a user whose global role is `platform_admin` may call them. The project audit log is an append-only table (`audit_log`). Annotation, patient-lock and data-lifecycle services write to it. Project admins can query it, and admins and annotators can read a per-patient activity timeline. Nothing in `frontend/src` calls `/admin/*`, `/audit` or `/activity`, and no page shows either part. Overall: **api-only**. The audit endpoints work live but have no endpoint tests, and bad filter values return 500. The admin endpoints have tests but cannot be driven, because no product path creates a platform admin.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| admin-queues | `GET /admin/queues`: BackgroundJob counts per job type, across all projects, as `{name, pending, active, complete, failed}` | api-only | API | 9c4beb61 | not driven (403 and 401 only) | `backend/app/admin/router.py:31-38`, `admin/service.py:13-39`, `tests/test_admin_api.py::test_get_queues`, `::test_get_queues_forbidden_for_regular_user` |
| admin-workers | `GET /admin/workers`: one synthetic `arq-worker` entry if the Redis key `arq:queue:health-check` exists, else `[]` | api-only | API | 9c4beb61 | not driven (403 only) | `admin/router.py:41-47`, `admin/service.py:42-62`, `test_admin_api.py::test_get_workers` |
| admin-jobs | `GET /admin/jobs?status=&limit=50&offset=0`: BackgroundJobs from every project, newest first | api-only | API | 9c4beb61 | not driven (403 only) | `admin/router.py:50-60`, `admin/service.py:65-77`, `test_admin_api.py::test_list_jobs` |
| admin-page | A platform-wide admin page in the UI | deferred | - | - | 2026-10-05 (`/admin` renders blank) | `docs/plans/2026-03-03-v2-monitoring-stats-design.md:232` ("System-wide admin page (per-project view sufficient for now)"). `frontend/src/App.tsx:91-129` has no `/admin` route |
| audit-query | `GET /projects/{id}/audit` (project admin): `{items:[{id, action, user_name, user_id, patient_id, detail, created_at}], total, limit, offset}`, newest first. `user_name` is "System" when there is no user | api-only | API | 511ec88e | 2026-10-05 | `backend/app/audit/router.py:20-43`, `audit/service.py:85-136`. No endpoint test. Live: 1 item, `data_ingested`, "System". Annotator and viewer get 403 |
| audit-filters-pagination | Filters `patient_id`, `user_id`, `action` (lowercase value), `since`, `until`. `limit` up to 200 (default 50), `offset` from 0 | api-only | API | 511ec88e | 2026-10-05 | `audit/router.py:23-29`, `audit/service.py:99-121`. Live: `action=data_ingested` total 1, `since=2099-…` total 0, `limit=201` 422, `limit=0` empty items with total 1. `action=bogus` and `limit=-1` return 500 |
| audit-patient-activity | `GET /projects/{id}/patients/{pid}/activity?limit=100` (admin, annotator): `summary {total_actions, unique_users, users[]}` plus `entries` | api-only | API | 511ec88e | 2026-10-05 | `audit/router.py:46-55`, `audit/service.py:38-82`. Live: annotator 200, viewer 403, unknown patient 200 with empty entries, `limit=-1` 500. The planned patient-detail section was never built (`docs/plans/2026-03-03-databricks-connector-and-audit-log-design.md:105`, `:201-206`) |
| audit-writers | Service code writes 10 of the 12 actions (table below). Each write is its own commit, and failures are logged and swallowed | api-only | worker+API | 511ec88e | 2026-10-05 (`data_ingested` only) | `audit/service.py:14-35`, call sites below. No test asserts that any write happens. `tests/test_enum_roundtrip.py:130-131` covers enum storage only |
| audit-model-actions | `PREDICTION_RAN` and `AUTO_ADJUDICATED` are defined but never written | stub | - | 511ec88e | not driven | `audit/models.py:27-29`. No `log_action` call uses them |

Why the grades:
- **Everything is `api-only` or lower.** Nothing in `frontend/src` reaches these endpoints. The audit endpoints have no endpoint tests at all. `tests/test_audit.py` has 6 model and import checks.
- **The admin rows** are tested, but the tests promote the user with an ORM update (`test_admin_api.py:6-26`). Live, only the 403 and 401 paths can be shown.

Who writes what:

| Action | Writer | User recorded |
|---|---|---|
| `annotation_reviewed`, `event_date_set` | `backend/app/annotations/review_service.py:146-156` | yes |
| `annotation_skipped` | `review_service.py:186` | yes |
| `patient_locked` | `review_service.py:254` | yes |
| `patient_unlocked` | `review_service.py:384` | yes |
| `event_date_deleted` | `review_service.py:431` | yes |
| `patient_reopened` | `review_service.py:526` | yes |
| `data_ingested` (sync ingest) and `data_resynced` | `backend/app/connectors/service.py:211-215` (through `:225`, `:370`) | no |
| `data_ingested` (background ingestion job) | `backend/app/jobs/ingestion.py:136-139` | no |
| `data_purged` | `connectors/service.py:547-550` | no |
| `prediction_ran`, `auto_adjudicated` | never written | - |

## How to get to it (user POV)

1. There is no UI for any of this. The sidebar has no admin or audit link, and `/admin` renders an empty page.
2. A project admin who wants the audit log must call `GET /api/v1/projects/<id>/audit` with their session cookie, for example from the browser devtools while signed in.
3. Admins and annotators can read one patient's timeline at `GET /api/v1/projects/<id>/patients/<patient id>/activity`. The patient detail page does not show it.
4. A platform admin calls `/api/v1/admin/queues`, `/workers` and `/jobs`. No product path creates a platform admin. Registration always creates `user` (`backend/app/auth/service.py:75`), and no endpoint changes the role.

## Driving it with control-cedars

Preconditions: the baseline. A fresh seed has exactly one audit row (`data_ingested`, no user) and one completed INGESTION BackgroundJob. Get a patient id with `PID=$($CC api GET "/projects/{project}/data/patients?limit=1" --as admin --json 2>/dev/null | jq -r '.items[0].id')`. Review-side audit rows appear only after the annotation mutation pass (`annotations.md`).

- **admin-queues**: → `$CC api GET /admin/queues --as admin --expect 403` → `"detail": "Platform admin required"`. Then `$CC api GET /admin/queues --as anon --expect 401` → "Not authenticated". The 200 path is SKIP: it needs a platform admin, which only a DB edit can create (CLAUDE.md forbids that). The data it would report can be checked read-only: `$CC db query "select job_type, status, count(*) from background_jobs group by 1,2"` → `INGESTION | COMPLETED | 1`.
- **admin-workers**: → `$CC api GET /admin/workers --as admin --expect 403` → "Platform admin required". The 200 path is SKIP for the same reason. The worker heartbeat itself is covered in `jobs.md` (`jobs-worker`).
- **admin-jobs**: → `$CC api GET "/admin/jobs?status=completed" --as admin --expect 403` → "Platform admin required". The 200 path is SKIP.
- **admin-page**: → `$CC browser snapshot /admin --as viewer` → an empty aria snapshot (no route, no "not found" page). Drove 2026-10-05 inside `projects-nonmember` (`projects.md`).
- **audit-query**: → `$CC api GET /projects/{project}/audit --as admin --save audit-admin` → 200, `total 1`, `items[0].action "data_ingested"`, `user_name "System"`, `user_id null`, `detail {data_source_id, row_count: 103}`.
- **audit-query** (role gating): → `$CC api GET /projects/{project}/audit --as annotator --expect 403` → "Insufficient permissions". Same with `--as viewer --expect 403`.
- **audit-filters-pagination**:
  - `$CC api GET "/projects/{project}/audit?action=data_ingested&limit=1" --as admin` → 200, `total 1`.
  - `$CC api GET "/projects/{project}/audit?since=2099-01-01T00:00:00Z" --as admin` → 200, `total 0`.
  - `$CC api GET "/projects/{project}/audit?limit=201" --as admin --expect 422`.
  - `$CC api GET "/projects/{project}/audit?limit=0" --as admin` → `items []`, `total 1`.
  - Defects: `$CC api GET "/projects/{project}/audit?action=bogus" --as admin --expect 500 --save audit-bad-action` and `$CC api GET "/projects/{project}/audit?limit=-1" --as admin --expect 500 --save audit-negative-limit` → "Internal Server Error". Once fixed, both should return 422.
- **audit-patient-activity**:
  - `$CC api GET "/projects/{project}/patients/$PID/activity" --as annotator --save audit-activity-annotator` → 200, `summary.total_actions 0` on a fresh seed.
  - `$CC api GET "/projects/{project}/patients/$PID/activity" --as viewer --expect 403`.
  - `$CC api GET /projects/{project}/patients/does-not-exist/activity --as admin` → 200, empty `entries`, not 404.
  - `$CC api GET "/projects/{project}/patients/$PID/activity?limit=-1" --as annotator --expect 500 --save audit-activity-negative-limit` (defect).
- **audit-writers**: → `$CC db query "select action, user_id is null as no_user, count(*) from audit_log group by 1,2"` → `DATA_INGESTED | t | 1` after seed (Postgres stores the enum NAME). After the annotation mutation pass, rerun it and expect `ANNOTATION_REVIEWED` and the lock rows with `no_user = f`. Then `$CC api GET "/projects/{project}/patients/$PID/activity" --as admin` → `summary.users` holds the annotator's name.
- **audit-model-actions**: SKIP. Nothing writes these actions. Check with `grep -rn -e PREDICTION_RAN -e AUTO_ADJUDICATED backend/app`, which matches only `audit/models.py`.

## Gotchas

- **Bad filter values return 500.** `action` is a plain `str` (`audit/router.py:25`) compared straight against the enum column (`audit/service.py:105`). On Postgres an unknown value is an invalid enum literal, so the query fails (live: `action=bogus` gives 500). `limit` has an upper bound but no lower one (`audit/router.py:28`, `:50`), so `limit=-1` reaches SQL as `LIMIT -1` and Postgres rejects it (live: 500 on both endpoints). `/admin/jobs` has the same raw-string filter (`admin/service.py:73-74`) and an unbounded `limit` (`admin/router.py:53-54`). It is probably the same 500 on a bad `status`, but that is not live-verified because the endpoint is unreachable.
- **Data actions never record who did them.** Ingest, resync and purge call `log_action` without `user_id` (`connectors/service.py:212-215`, `:547-550`, `jobs/ingestion.py:136-139`), so the log shows "System". A purge deletes patient data and is the action an auditor most needs to attribute. The purge and resync routes know the caller, but they never pass it to the service (`backend/app/connectors/router.py:252`, `:260`, `:274`, `:288`).
- **The log is not guaranteed complete.** `log_action` commits on the caller's session and swallows any exception after a rollback (`audit/service.py:31-35`). The callers commit their own change first (for example `review_service.py:142`, `:252`), so a failed audit write leaves the action done and unlogged, with only a server log line. If a future caller leaves work uncommitted, the audit commit or rollback will take that work with it. This is open finding D5 in the engineering wiki.
- **`/queues` drops cancelled jobs.** The service counts `cancelled` but the response has no field for it (`admin/service.py:26-39`), though `JobStatus.CANCELLED` exists (`backend/app/jobs/models.py:29`).
- **`/workers` is a heartbeat, not a worker list.** It returns at most one hard-coded `"arq-worker"`, and `current_job` holds the raw health-check string, not a job (`admin/service.py:50-57`). Any Redis error returns `[]` (`:60-62`), which looks the same as "no workers".
- **`/admin/jobs` and `/queues` cover BackgroundJob only.** Pipeline runs and evaluation sessions are not counted. The per-project equivalent is `GET /pipeline/queue` (`jobs.md`).
- **Platform admin cannot be reached.** `require_platform_admin` (`admin/router.py:15-28`) needs `UserRole.PLATFORM_ADMIN`, but nothing assigns it (`auth/service.py:75`). The tests promote the user with an ORM update (`test_admin_api.py:6-26`). Under the no-DB-edits rule (CLAUDE.md), this is the finding: an operator has no supported way to create the first platform admin.
- **Activity does not check the patient.** An unknown patient id returns 200 with empty entries (`audit/service.py:38-82`). The same is true for a patient from another project, which just matches nothing.
- **Viewers cannot see activity, but admins and annotators can** (`audit/router.py:52`). The full `/audit` query is admin-only (`:31`). Platform admins bypass both checks (`backend/app/dependencies.py:43-45`).
- **Action values differ by layer.** The API filter and responses use lowercase values (`data_ingested`), but Postgres stores the enum NAME (`DATA_INGESTED`). Use lowercase in `api` calls and uppercase in `db query`.
