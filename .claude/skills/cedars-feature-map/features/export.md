# Export

Last verified: cef611321063 on 2026-10-05 (source + live)

Export is the last step of the project workflow ("Step 4 of 4: Export"). Admins and viewers download a project's annotations as CSV or JSON from the Export page. They can filter to reviewed rows or to rows that have an event date. A separate API-only endpoint writes annotations, predictions or evaluation rows into a Databricks table. Overall: CSV export and the stats work. JSON export returns 500 as soon as the project has any annotation created through the UI. The Databricks export has no UI, and two of its three types crash. No test covers the CSV, JSON or stats endpoints. DEV runs `cef61132` (`aws status`, 2026-10-05), so every defect below is live on DEV.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| export-page | Export page: breadcrumb, stat cards, "Export format" and "Annotation filter" radio groups, "Download N annotations" button | beta | UI | 8197dee8 | 2026-10-05 | `frontend/src/projects/ExportPage.tsx:89-244`, `App.tsx:128`, `AppSidebar.tsx:25`. No frontend tests |
| export-stats | `GET /export/stats` returns `total`, `reviewed`, `events`, `total_eval_tokens` | beta | UI+API | 3c83f16b | 2026-10-05 | `backend/app/export/router.py:30-37`, `export/service.py:13-45`. No tests |
| export-csv | `GET /export/annotations/csv` returns `text/csv`. The page saves it as `annotations-<pid8>.csv` | beta | UI+API | 3c83f16b | 2026-10-05 | `router.py:51-65`, `service.py:66-103`, `ExportPage.tsx:48-60`. No tests |
| export-json | `GET /export/annotations` returns `list[ExportAnnotationRow]`. The page pretty-prints it to `annotations-<pid8>.json` | stub | UI+API | 3c83f16b | 2026-10-05 FAIL | `export/schemas.py:11` vs `backend/app/worker.py:278-291`, `:352-365`. No tests |
| export-filters | `status=reviewed` keeps `review_status == reviewed`. `status=events` keeps rows with `event_date` set. The button count switches to match | beta | UI+API | 3c83f16b | 2026-10-05 (API) | `service.py:56-59`, `ExportPage.tsx:36-47`. Live: `reviewed` 1, `events` 1, `all` 5 rows; an unknown `status` returns 200 with all rows |
| export-role-gating | Admin and viewer can read. Annotator gets 403 and anon gets 401, but the sidebar still shows Export to annotators | beta | UI+API | 3c83f16b | 2026-10-05 | `router.py:34`, `:45`, `:56`, `AppSidebar.tsx:25` |
| export-dbx-annotations | `POST /export/databricks` with `export_type=annotations` writes every non-unreviewed annotation to `catalog.schema.target_table` | stub | API | 9a85ad8b | not driven | `export/databricks.py:131`, `:141`, `annotations/models.py:51-54` |
| export-dbx-predictions | Same endpoint, `export_type=predictions`: every annotation with a predicted label | api-only | API | 9a85ad8b | not driven | `databricks.py:149-172`, `tests/test_export_databricks.py::TestExportToDatabricks::test_exports_rows_to_databricks` (mocked) |
| export-dbx-evaluation | Same endpoint, `export_type=evaluation`: evaluation judgments | stub | API | 9a85ad8b | not driven | `databricks.py:178-181`, `evaluation/models.py:3` |

Why the grades:
- **export-csv and export-stats** work, but no test covers them, so they cannot be `stable`.
- **export-json** crashes. The only UI path that creates annotations is the evaluation full pipeline, and it never sets `sentence_id`. The response model requires that field (see Gotchas).
- **export-role-gating** has a defect: the UI shows Export to annotators, whom the API rejects.
- **Tests.** The only export tests are the 10 in `backend/tests/test_export_databricks.py`, all mocked. They pass locally on SQLite and Postgres at cef611321063 (382/382 on each suite). CI has never run them green, because the SQLite job stops at lint (see README "Test evidence").

## How to get to it (user POV)

1. Log in. On the "Projects" list, open a project.
2. Open the page one of three ways:
   - Sidebar link "Export". Every role sees it.
   - The "Export" step on the project Overview, link "Get started". It is locked until annotations exist (`ProjectOverview.tsx:475-477`).
   - The "Export" link on the right of the "Workflow steps" breadcrumb, from the Annotations page.
3. The page shows heading "Export" and the subtitle "Download annotated data as CSV or JSON". Below them are the "Export statistics" cards: "Total annotations", "Reviewed", "Events found", plus "Eval tokens used" when that count is above 0.
4. Under "Export options", pick a format ("CSV" or "JSON"). Under "Include", pick "All annotations", "Reviewed only" or "Events only".
5. Click "Download N annotations". The button is disabled when N is 0. On success the page shows "Downloaded N annotations as CSV" (or JSON). On failure it shows a red `role=alert` line.

## Driving it with control-cedars

Preconditions: the baseline. The seeded project has **0 annotations**, so only the empty-project checks run on a fresh seed. For row-level checks, first finish a committed evaluation session's full pipeline (see `evaluation-run.md`). Then review at least one annotation with an event date (see `annotations.md`).

- **export-page**: viewer opens Export from the sidebar →
  ```
  $CC browser run - --as viewer --save export-page <<'EOF'
  [{"goto":"/projects/{project}"},
   {"click":{"role":"link","name":"Export","exact":true}},
   {"expect_url":"/export$"},
   {"expect":{"role":"heading","name":"Export","exact":true}},
   {"expect":{"role":"status","name":"Export statistics"}},
   {"expect_text":"Total annotations"},
   {"click":{"role":"radio","name":"JSON"}},
   {"click":{"role":"radio","name":"Reviewed only"}},
   {"expect":{"role":"button","name":"Download 0 annotations"},"state":"disabled"},
   {"screenshot":"empty"}]
  EOF
  ```
  → exit 0. On an empty project the button is disabled with N = 0.
- **export-stats**: read the counts → `$CC api GET /projects/{project}/export/stats --as admin --save export-stats` → HTTP 200 `{"total":0,"reviewed":0,"events":0,"total_eval_tokens":0}` on a fresh seed. After a pipeline run, `total` equals the row count from `$CC db query "select count(*) from annotations where project_id = (select id from projects order by created_at desc limit 1)"`.
- **export-csv**: download through the UI, then check the body →
  ```
  $CC browser run - --as admin --save export-csv <<'EOF'
  [{"goto":"/projects/{project}/export"},
   {"click":{"role":"radio","name":"CSV"}},
   {"click":{"role":"radio","name":"All annotations"}},
   {"click":{"role":"button","name":"Download"}},
   {"expect_text":"annotations as CSV"},
   {"screenshot":"done"}]
  EOF
  ```
  → "Downloaded N annotations as CSV" is shown. The runner has no download step, so check the file contents through the API: `$CC api GET /projects/{project}/export/annotations/csv --as admin --save export-csv-body` → HTTP 200. The first line is `patient_id,note_id,sentence_id,sentence_text,predicted_label,predicted_score,predictor_model,reasoning,review_status,reviewed_by,reviewed_at,event_date`, and there are `total` data rows. On a fresh seed you get the header line only (driven 2026-10-05). `api` does not print response headers, so the `Content-Disposition` filename is source-only (`router.py:64`).
- **export-json**: after annotations exist → `$CC api GET /projects/{project}/export/annotations --as admin --save export-json` → today HTTP 500 (`Internal Server Error`, plain text). In the UI, the same flow with radio "JSON" shows "Request failed". Once fixed, expect HTTP 200 and an array of `total` objects with `sentence_id: null`. A fresh seed returns `[]`. Driven 2026-10-05 after a committed session: HTTP 500, and `$CC stack logs backend --grep sentence_id` shows `ResponseValidationError: 5 validation errors … ('response', 0, 'sentence_id') … 'input': None`.
- **export-filters**: count the rows per filter → `$CC api GET '/projects/{project}/export/annotations/csv?status=reviewed' --as viewer` and `'...csv?status=events'` → data rows equal `reviewed` and `events` from `/export/stats`. Cross-check with `$CC db query "select review_status, count(*), count(event_date) from annotations where project_id = (select id from projects order by created_at desc limit 1) group by 1"`. Count rows with a CSV parser, not `wc -l`: `sentence_text` holds quoted newlines (live: 24 lines, 5 rows). Driven 2026-10-05: 5 annotations, 1 reviewed with a date → `status=reviewed` 1, `status=events` 1, `status=all` 5, matching `/export/stats` (`total` 5, `reviewed` 1, `events` 1).
- **export-role-gating**: check the API → `$CC api GET /projects/{project}/export/stats --as annotator --expect 403` and `$CC api GET /projects/{project}/export/annotations/csv --as annotator --expect 403` → `{"detail":"Insufficient permissions"}`. `$CC api GET /projects/{project}/export/annotations --as anon --expect 401` → `{"detail":"Not authenticated"}`. Then check the UI defect:
  ```
  $CC browser run - --as annotator --save export-annotator <<'EOF'
  [{"goto":"/projects/{project}/export"},
   {"expect":{"role":"link","name":"Export","exact":true}},
   {"expect":{"role":"status","name":"Export statistics"},"state":"hidden"},
   {"expect_no_text":"Insufficient permissions"},
   {"expect":{"role":"button","name":"Download 0 annotations"},"state":"disabled"}]
  EOF
  ```
  → exit 0, with a `403 GET .../export/stats` warning. That shows the defect: annotators reach a page with no stats, a disabled button and no message. Once fixed, this run should fail.
- **export-dbx-annotations / export-dbx-predictions / export-dbx-evaluation**: SKIP, needs a real Databricks workspace and a Databricks data source with an encrypted token. Gating can be checked without a workspace once POSTs are allowed: `$CC api POST /projects/{project}/export/databricks --as viewer --body '{"data_source_id":"{source}","target_table":"t","export_type":"annotations"}' --expect 403`. `export_type":"bogus"` as admin gives 400 `Invalid export_type 'bogus'. Must be one of: [...]`.

## Gotchas

- **JSON export returns 500 for UI-created annotations.** `ExportAnnotationRow.sentence_id: str` is required (`export/schemas.py:11`), but `Annotation.sentence_id` is nullable (`annotations/models.py:37`). The evaluation pipeline creates every annotation the UI can produce, and it never sets `sentence_id` (`worker.py:278-291`, `:352-365`; also `jobs/pipeline.py:178-191`). Response validation fails, and FastAPI returns a plain-text 500 because no handler is registered. The client cannot parse that body and shows "Request failed" (`api/client.ts:51-52`). This was reproduced at model level in-process today. Only the API-only bulk-prediction paths set `sentence_id` (`annotations/prediction_service.py:93`, `jobs/prediction.py:135`).
- **Databricks annotations export crashes on any row.** `review_status` is a VARCHAR column (`annotations/models.py:51-54`, changed in a5b72355), so a loaded row holds a plain `str`. `databricks.py:141` calls `ann.review_status.value`, which raises AttributeError, and that becomes 500 "Export to Databricks failed" (`router.py:95-97`). The CSV path guards this with `hasattr` (`service.py:97`). The tests patch `_fetch_export_rows` (`tests/test_export_databricks.py:88`, `:129`), so they never see it. With zero non-unreviewed rows it returns `rows_exported: 0` instead.
- **Databricks evaluation export always fails.** It imports `EvaluationJudgment` and reads `EvaluationSession.predictor_config_id` (`databricks.py:178-181`). Neither exists any more (`evaluation/models.py:3`). The ImportError is raised before the empty-rows check, so the result is 500 every time.
- **Databricks error mapping.** Any `ValueError` returns 404 (`router.py:93-94`). That covers a missing data source and an invalid catalog, schema or table name from `_fqn` (`connectors/databricks.py:36-44`). A file-upload data source has no `token`, `host` or `schema` keys, so it raises KeyError and returns 500, not 400. The connection opens before the name is validated (`databricks.py:83-88`).
- **Databricks export blocks the event loop.** Synchronous driver calls run inside an async route (`databricks.py:83-103`), one `cursor.execute` per row. The batch loop does not batch anything (`:95-99`).
- **CSV skips token refresh.** It uses raw `fetch` (`ExportPage.tsx:49-53`), not `api.get`. After the 15-minute access token expires, the user gets "Export failed" and is not redirected to login. JSON goes through `api.get`, which refreshes.
- **The success message count comes from the stats** (`ExportPage.tsx:75-78`), not from the rows actually downloaded.
- **IDs in the exports are internal UUIDs.** In CSV and JSON, `patient_id`, `note_id` and `reviewed_by` are internal UUIDs, not `patient_id_ext` or `text_id` (`service.py:88-98`; `connectors/models.py:79`, `:121`). The Databricks export does include `text_id`, but its `patient_id` and `reviewer` are also UUIDs (`databricks.py:137-144`).
- **"Events found" counts only reviewer-set dates.** The LLM's event date goes to `PatientResult.event_date` (`worker.py:255`), not to the annotation. "Events found" and "Events only" stay at 0 until a reviewer sets a date (`annotations/review_service.py:78-79`).
- **"Reviewed only" excludes skipped rows.** Marking an event can auto-skip later annotations (`review_service.py:102-121`), and those rows drop out of this filter.
- **"Eval tokens used" counts sample runs only.** It sums `metrics.token_usage` across all evaluation sessions, discarded ones included (`service.py:33-43`). Full-pipeline tokens are stored per `PatientResult` (`worker.py:257`), so they are not counted.
- **Exports are not audit-logged.** `AuditAction` has no export action (`audit/models.py:13-34`).
- **Downloads in headless tests.** The page clicks a blob link and revokes it immediately (`ExportPage.tsx:54-60`). Assert on the feedback text, then fetch the body with `api`.
