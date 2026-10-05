# Data

Last verified: cef611321063 on 2026-10-05 (source + live read-only)

The Data area gets clinical notes into a project. It is step 1 of the workflow ("Step 1 of 4: Data"), reached from the sidebar link "Data" (`/projects/:id/data`). An admin uploads a CSV or JSON file, or the bundled sample dataset. The admin previews it, maps columns to the four required fields, and uploads it. The file goes to S3, and a data source row is created as "Pending". The admin then clicks "Run Ingestion". An ARQ worker downloads the file from S3 and writes patients and notes. If no worker is up, an in-process task does the same work. A second source type connects to a Databricks SQL warehouse table. Every write endpoint is admin-only, but the page shows all of its controls to annotators and viewers too.

Overall: beta. On the parity stack's native S3 path, upload, preview, mapping, the sample dataset and ARQ ingestion all work end to end. There are four known problems:
- The ingestion status and cancel endpoints lose the job once its first batch commits.
- A crashed ingestion leaves the source "Ingesting..." forever.
- Purge fails on Postgres once any evaluation has run.
- Viewers see admin controls.

Purge, resync and per-source preview have no UI. Databricks was not driven, because it needs a workspace.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| data-source-list | `GET /data/sources` lists sources, newest first. The page renders cards under "Data sources" showing status and row count | beta | UI+API | 72ae7475 | 2026-10-05 | `connectors/router.py:53-59`, `common/crud.py:37-52`, `DataPage.tsx:806-835`, `tests/test_connectors_api.py::TestDataSourceCRUD::test_list_data_sources` |
| data-source-get | `GET /data/sources/{id}` returns one source, or 404 "Data source not found" | api-only | API | 72ae7475 | 2026-10-05 | `router.py:62-72`, `test_connectors_api.py::TestDataSourceCRUD::test_get_data_source`, `::test_get_nonexistent_data_source` |
| data-upload-preview | Drop zone, "Browse files", and `POST /upload/preview`, which reads the first 256 KB and returns columns plus 3 rows | beta | UI+API | 8197dee8 | 2026-10-05 | `router.py:90-147`, `DataPage.tsx:307-352`, `:449-469`. No backend test |
| data-column-mapping | "Map your columns" card. It auto-matches aliases (for example `text_date` to Note date), shows "Missing: ..." and enables the upload button only when all four fields are mapped | beta | UI | 8197dee8 | 2026-10-05 | `DataPage.tsx:41-50`, `:78-84`, `:527-644`. No frontend tests |
| data-upload-create | `POST /upload` validates the extension and mapping, puts the file at `projects/<pid>/uploads/<uuid>/<name>`, and creates a PENDING source | beta | UI+API | cf2dd65c | not driven | `connectors/service.py:91-146`, `common/s3.py:13-32`, `test_connectors_api.py::TestFileUpload::test_upload_csv_file` (S3 mocked), `::test_upload_unsupported_filetype`, `::test_upload_requires_auth` |
| data-sample-dataset | "Use sample dataset" fetches `/sample-data/simulated_patients.csv` (5 patients, 103 notes) and feeds it into the same preview and mapping path | beta | UI | a2ae6891 | 2026-10-05 (preview + mapping only) | `DataPage.tsx:58-62`, `:355-374`, `:470-487`, `frontend/public/sample-data/simulated_patients.csv` |
| data-ingest-start | `POST /ingest` creates a BackgroundJob and enqueues `run_ingestion_job` when `arq:queue:health-check` exists. Otherwise it runs in-process. Rows go in batches of 1000, deduplicated on `text_id` | beta | UI+API | 931512f3 | not driven (seed's run: job COMPLETED, `arq_job_id` set, 103 rows) | `service.py:229-301`, `jobs/ingestion.py:20-153`, `worker.py:57-61`, `test_connectors_api.py::TestIngestion::test_ingest_csv_data` (in-process only), `::test_ingest_invalid_config`, `::test_ingest_nonexistent_source` |
| data-ingest-status | `GET /ingest/status` drives the JobBanner states: "Run Ingestion", "Ingestion running…", "Ingestion complete", "Ingestion failed" | beta | UI+API | a5b72355 | 2026-10-05 (returns `null` for the completed job) | `service.py:304-331`, `jobs/ingestion.py:77-83`, `:116`, `JobBanner.tsx:44-47`, `:110-237`. No test |
| data-ingest-cancel | "Cancel" in the running banner calls `POST /ingest/cancel`. The job stops before its next batch, and the source becomes Failed with "Cancelled by user" | beta | UI+API | 1f5dfb8d | not driven | `service.py:334-362`, `ingestion.py:85-97`, `JobBanner.tsx:130-155`. No test |
| data-ingest-progress-ws | `/ws/projects/{pid}/jobs/{job_id}` pushes `{type,status,progress,result_summary}` every second until the job ends | beta | UI | 1f5dfb8d | not driven | `jobs/ws.py:14-55`, `main.py:134`, `JobBanner.tsx:65-93` |
| data-databricks-form | The "Databricks" toggle opens a form (host, HTTP path, token, catalog, schema, table, and the column names). "Create data source" calls `POST /sources`. The token is encrypted at rest | beta | UI+API | 8197dee8 | 2026-10-05 (form only, not submitted) | `DataPage.tsx:413-428`, `:660-802`, `service.py:33-63`, `test_connectors_api.py::TestDataSourceCRUD::test_create_data_source`, `tests/test_crypto.py` |
| data-databricks-ingest | Ingestion through `DatabricksConnector`: `SELECT 1` on validate, then paged `LIMIT/OFFSET` fetch | beta | UI+API | 53a93418 | not driven (SKIP: needs a Databricks workspace) | `connectors/databricks.py:60-154`, `registry.py:33-38`, `tests/test_connectors.py::TestDatabricksConnector` (mocked) |
| data-source-delete | The trash icon on a card soft-deletes the source with no confirm. Its patients and notes stay | beta | UI+API | 72ae7475 | not driven | `router.py:75-84`, `service.py:78-85`, `DataPage.tsx:259-265`, `:830`, `test_connectors_api.py::TestDataSourceCRUD::test_delete_data_source` |
| data-source-purge | `DELETE /sources/{id}/data?confirm=true` deletes the source's annotations, sentences, notes and orphan patients, and resets the source to PENDING | api-only | API | 511ec88e | not driven | `router.py:268-289`, `service.py:493-552`. No test |
| data-source-resync | `POST /sources/{id}/resync` re-fetches and upserts by `text_id` inside the request (no BackgroundJob) | api-only | API | 3d9432f8 | not driven | `router.py:247-265`, `service.py:152-217`, `:365-371`, `:416-490`. No test |
| data-source-preview | `GET /sources/{id}/preview?limit=N` returns columns, rows and `total_available` from the stored object | api-only | API | a5b72355 | 2026-10-05 | `router.py:183-201`, `test_connectors_api.py::TestPreview::test_preview_data_source` |
| data-role-gating | The API allows writes and source preview for admins only, and reads for all members. The page shows every write control to every role | beta | UI+API | 8197dee8 | 2026-10-05 | `router.py:40-289`, `dependencies.py:44-58`, `DataPage.tsx` (no role check anywhere) |

Why the grades:
- **No row is `stable`.** Each row has an open defect (see Gotchas), lacks a test, or was not driven live.
- **Tests.** The connector tests pass locally on SQLite and Postgres at cef611321063 (382/382 on each suite). CI has never run them green, because the SQLite job stops at lint (see README "Test evidence"). Ingestion tests run in-process with S3 mocked, so no test covers the ARQ path or real S3.
- **Frontend lint.** eslint (`npm run lint`) reports exhaustive-deps warnings at `DataPage.tsx:383` and `:392`: `handleDrop` and `handleFileInput` use `useCallback(..., [])`.

## How to get to it (user POV)

1. Log in. On "Projects", open a project.
2. Click "Data" in the sidebar. On the project Overview, the "Data" step's "Get started" (or "View") link goes to the same page.
3. Leave "File upload" selected. Then do one of these:
   - Drop a CSV or JSON file on "Drop a file here".
   - Click "Browse files".
   - Click "Use sample dataset".
4. The card shows the filename, "N columns detected", "Map your columns" with a select for each of "Patient ID", "Text ID", "Text", "Note date" and the optional "Source ref", and "Preview (first 3 rows)". When all four are mapped, it says "All required columns mapped".
5. Click "Upload and create data source". A card appears under "Data sources" with status "Pending" and a "Run Ingestion" button.
6. Click "Run Ingestion". The banner shows "Ingestion running…" with a progress bar and "Cancel". When the job finishes, the card reads "Ingested · N rows".
7. For Databricks, click "Databricks" and fill in the fields marked `*`. Click "Create data source", then "Run Ingestion" on the new card.
8. To remove a source, click the trash icon on its card. There is no confirmation.

## Driving it with control-cedars

Preconditions: the baseline. The seeded project already holds the sample (`{source}`, completed, 103 rows). For a fresh upload, first run `$CC seed --no-upload`. It creates a new empty project and points `{project}` at it. After that, `{source}` does not expand until you seed again.

- **data-source-list**: viewer lists sources → `$CC api GET '/projects/{project}/data/sources' --as viewer --save data-sources-viewer` → 200, one item, `status: completed`, `row_count: 103`.
- **data-source-get**: → `$CC api GET '/projects/{project}/data/sources/{source}' --as annotator` → 200 `row_count: 103`. With `00000000-0000-0000-0000-000000000000` in place of `{source}` and `--as admin --expect 404`, the call returns `"Data source not found"`.
- **data-upload-preview** and **data-column-mapping**: browse a local file, unmap one field, then remap it →
  ```
  $CC browser run - --as admin --save data-browse-preview <<'EOF'
  [{"goto":"/projects/{project}/data"},
   {"upload":{"css":"input[type=file]"},"file":"frontend/public/sample-data/simulated_patients.csv"},
   {"expect_text":"All required columns mapped"},
   {"select":{"role":"combobox","nth":3},"value":"— Select column —"},
   {"expect_text":"Missing: Note date"},
   {"expect":{"role":"button","name":"Upload and create data source"},"state":"disabled"},
   {"select":{"role":"combobox","nth":3},"value":"text_date"},
   {"expect":{"role":"button","name":"Upload and create data source"},"state":"enabled"},
   {"click":{"role":"button","name":"Cancel"}}]
  EOF
  ```
  → all steps PASS (2026-10-05). The run uploads nothing.
- **data-sample-dataset**: load the sample, then cancel →
  ```
  $CC browser run - --as admin --save data-sample-preview <<'EOF'
  [{"goto":"/projects/{project}/data"},
   {"click":{"role":"button","name":"Use sample dataset"}},
   {"expect_text":"10 columns detected"},
   {"expect_text":"All required columns mapped"},
   {"expect_text":"Preview (first 3 rows)"},
   {"click":{"role":"button","name":"Cancel"}},
   {"expect_text":"Drop a file here"}]
  EOF
  ```
  → PASS (2026-10-05).
- **data-upload-create**, **data-ingest-start**, **data-ingest-progress-ws** (mutating, run in the mutation pass): fresh project, sample through the UI, worker reads S3 →
  ```
  $CC seed --no-upload
  $CC browser run - --as admin --save data-upload <<'EOF'
  [{"goto":"/projects/{project}/data"},
   {"expect_text":"No data sources yet"},
   {"click":{"role":"button","name":"Use sample dataset"}},
   {"expect_text":"All required columns mapped"},
   {"click":{"role":"button","name":"Upload and create data source"}},
   {"expect_text":"simulated_patients.csv"},
   {"expect_text":"Pending"},
   {"click":{"role":"button","name":"Run Ingestion"}},
   {"wait":10},
   {"goto":"/projects/{project}/data"},
   {"expect_text":"Ingested · 103 rows","timeout":60},
   {"screenshot":"ingested"}]
  EOF
  $CC api GET '/projects/{project}/data/patients' --as viewer
  $CC db query "select status, arq_job_id is not null as via_arq, result_summary from background_jobs where job_type='INGESTION' order by created_at desc limit 1"
  ```
  → patients `total: 5`. The job row is `COMPLETED` with `via_arq = t`. `api GET '/projects/{project}/data/sources'` shows `config.s3_key` starting `projects/<pid>/uploads/`. On the parity stack the write and the worker's read both go through boto3's default chain with `CEDARS_S3_ENDPOINT=""`, as on ECS (`compose.parity.yml:17-38`, `s3.py:20-24`). The `goto` reload is there because the banner can miss the end of the job (see Gotchas).
- **data-ingest-status**: → `$CC api GET '/projects/{project}/data/sources/{source}/ingest/status' --as viewer` → today returns `null`, although `db query "select status, result_summary from background_jobs where job_type='INGESTION' order by created_at desc limit 1"` shows `COMPLETED` with no `data_source_id`. FAIL (defect).
- **data-ingest-cancel** (mutating): → after the job ends, `$CC api POST '/projects/{project}/data/sources/{source}/ingest/cancel' --as admin --expect 404` → `"No active ingestion job found"`. With `--as viewer --expect 403`, the call returns `"Insufficient permissions"`. The sample is a single batch, so a mid-run cancel needs a file over 1000 rows.
- **data-ingest-progress-ws**: find the job id with the `db query` above (`select id ...`), then `$CC ws '/ws/projects/{project}/jobs/<job_id>' --seconds 5 --as admin` → one `completed` message.
- **data-databricks-form**: fill the form without submitting →
  ```
  $CC browser run - --as admin --save data-dbx-form <<'EOF'
  [{"goto":"/projects/{project}/data"},
   {"click":{"role":"button","name":"Databricks","exact":true}},
   {"expect_text":"Connect to a Databricks SQL warehouse table"},
   {"expect":{"role":"button","name":"Create data source"},"state":"disabled"},
   {"expect_text":"Fill all required fields to continue"},
   {"fill":{"placeholder":"My clinical notes","exact":true},"value":"dbx-probe"},
   {"fill":{"placeholder":"adb-123.azuredatabricks.net","exact":true},"value":"nonexistent.invalid"},
   {"fill":{"placeholder":"/sql/1.0/warehouses/abcd1234","exact":true},"value":"/sql/1.0/warehouses/none"},
   {"fill":{"placeholder":"dapi...","exact":true},"value":"dapi-fake"},
   {"fill":{"placeholder":"clinical_data","exact":true},"value":"s"},
   {"fill":{"placeholder":"patient_notes","exact":true},"value":"t"},
   {"fill":{"placeholder":"patient_id","exact":true},"value":"patient_id"},
   {"fill":{"placeholder":"text_id","exact":true},"value":"text_id"},
   {"fill":{"placeholder":"text","exact":true},"value":"text"},
   {"fill":{"placeholder":"note_date","exact":true},"value":"note_date"},
   {"expect":{"role":"button","name":"Create data source"},"state":"enabled"}]
  EOF
  ```
  → PASS (2026-10-05).
- **data-databricks-ingest**: SKIP, needs a Databricks workspace. Failure path (mutating): create with host `nonexistent.invalid`, then run ingestion → card "Failed" with "Could not connect to Databricks: ..." (`databricks.py:47-57`).
- **data-source-delete** (mutating): → `$CC api DELETE '/projects/{project}/data/sources/{source}' --as viewer --expect 403`. Then the same call `--as admin --expect 204`. In the UI, click `{"css":"button:has(svg.lucide-trash-2)"}` and goto the page again to see the card disappear.
- **data-source-purge** (mutating): → `$CC api DELETE '/projects/{project}/data/sources/{source}/data' --as admin --expect 400` → `"Pass ?confirm=true to confirm data deletion"`. Then `.../data?confirm=true --as admin` → `{"deleted_notes":103,...}` on a project with no evaluation runs.
- **data-source-resync** (mutating): → `$CC api POST '/projects/{project}/data/sources/{source}/resync' --as admin` → 200 `message: "Re-synced 103 rows"`, and the notes count is unchanged.
- **data-source-preview**: → `$CC api GET '/projects/{project}/data/sources/{source}/preview?limit=2' --as admin --save data-preview-admin` → 200, 10 columns, 2 rows, `total_available: 103` (an API-side S3 read). With `--as viewer --expect 403`, the call returns 403.
- **data-role-gating**: → `$CC browser snapshot '/projects/{project}/data' --as viewer --save data-page-viewer` → the viewer sees "File upload", "Databricks", "Use sample dataset", "Browse files" and the trash button, the same as admin. Then run:
  ```
  $CC browser run - --as viewer --save data-sample-viewer <<'EOF'
  [{"goto":"/projects/{project}/data"},
   {"click":{"role":"button","name":"Use sample dataset"}},
   {"expect_text":"Insufficient permissions"},
   {"screenshot":"403"}]
  EOF
  ```
  → PASS (2026-10-05): the control is shown, then rejected (403 on `/upload/preview`). Anonymous access: `$CC api GET '/projects/{project}/data/sources' --as anon --expect 401` returns 401.

## Gotchas

**Ingestion status and recovery**
- **Status and cancel lose the job after one batch.** `dispatch_ingestion_job` stores `data_source_id` in `result_summary` (`service.py:244`). `execute_ingestion_job` then overwrites `result_summary` with `_summary()`, which has no `data_source_id` (`ingestion.py:77-83`, `:116`, `:144`). Status and cancel both filter on that key (`service.py:322-324`, `:353-354`), so they return `null` or 404 once the first batch commits. In the UI, a page reload during or after ingestion shows "Run Ingestion" again. The WS merge (`JobBanner.tsx:76-82`) is the only path that fires `onTerminal`. If the job is past its first batch before the banner's refetch, the card stays "Pending" or "Ingesting..." until reload.
- **Status is also project-wide.** It reads only the latest INGESTION job in the project (`service.py:310-318`). Starting ingestion on source B hides source A's job.
- **No concurrent-run guard.** Dispatch creates a job with no check for an active one (`service.py:239-248`).
- **A crash leaves the source "Ingesting..." forever.** The `except` branch fails only the job (`ingestion.py:146-149`), and the source stays RUNNING. The source card shows "Ingesting..." with no error. Because of the status defect above, the banner offers "Run Ingestion", which is the only recovery.
- **The in-process fallback is fragile.** The task is not kept in a strong reference (`service.py:292-295`), and it dies with the backend task. ECS runs two backend replicas.

**Upload and preview**
- **Uncaught S3 errors break the error message.** `POST /upload` catches only `EnvironmentError` and `ValueError` (`router.py:174-177`). A botocore error therefore returns 500 with a non-JSON body. The raw `fetch` then calls `resp.json()` on it (`DataPage.tsx:219`), so the user sees a JSON parse error, not a message. The raw `fetch` calls (`:213`, `:322`) also skip the 401 refresh that `api/client.ts:36-48` does.
- **Large JSON files fail preview.** Preview parses only the first 256 KB, and `json.loads` on a truncated array fails with "Could not parse JSON..." (`router.py:111-138`).
- **Whole files go through memory, blocking the event loop.** The upload reads the whole file (`router.py:164`). boto3 calls run synchronously inside async handlers (`service.py:138`, `file_upload.py:87`). Ingestion parses the whole object into a list (`file_upload.py:85-96`).
- **Bad dates still create patients.** A row with a bad date still creates its patient, because `_get_or_create_patient` runs before the date check (`service.py:597-613`). That can leave a patient with 0 notes.
- **Re-ingesting gives 0 new rows.** `text_id` is unique per project (`models.py:115`), and duplicates are skipped silently (`service.py:593-594`).

**Delete, purge and resync**
- **Delete does not refresh the list.** `DELETE /sources/{id}` returns 204. `api/client.ts:62` calls `res.json()` on it, which throws, so `onSuccess` never runs (`DataPage.tsx:259-265`). There is no `onError` either. The card stays until reload. After delete, purge is impossible (404), because `get_scoped` skips deleted rows (`common/crud.py:21-34`). No endpoint can remove those notes afterwards.
- **Purge fails on Postgres after any evaluation or review.** Purge deletes notes and patients but not `evidence`, `search_matches`, `evaluation_judgments` or `audit_log` rows that reference them (`service.py:519-539`). A live `pg_constraint` read shows those FKs as NO ACTION. Purge then fails with an FK violation (500) as soon as an evaluation, pipeline or patient lock has touched the data. SQLite does not enforce the FK, which hides this.
- **Resync runs inside the HTTP request** (`router.py:259`) and does a SELECT per row (`service.py:459-465`).

**Exposure and security**
- **Known security defects** affect `data-databricks-form`, `data-source-list` and `data-ingest-progress-ws`. Details are tracked privately, not in this public repo.

**Databricks**
- **Unordered paging.** The fetch pages with `LIMIT/OFFSET` and no `ORDER BY` (`databricks.py:81-100`). It does not report `total_rows`, so progress is a guess (`ingestion.py:106-122`).
- **Optional connector.** It registers only if `databricks-sql-connector` imports (`registry.py:33-38`).

**Locators for driving**
- **Selects and form inputs have no accessible names.** The column selects have none (`DataPage.tsx:139-156`), so use `{"role":"combobox","nth":N}` in field order: 0 Patient ID, 1 Text ID, 2 Text, 3 Note date, 4 Source ref. The Databricks `<Label>`s have no `htmlFor`, so the inputs are named only by placeholder.
- **The trash button has no name** (`DataPage.tsx:906-913`). Use `{"css":"button:has(svg.lucide-trash-2)"}`.
- **The file input is hidden** inside a label (`:459-469`). Use `upload` with `{"css":"input[type=file]"}`. The path is relative to the repo root.
