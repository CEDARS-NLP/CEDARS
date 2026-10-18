# Multi-surface journeys

Last verified: cef611321063 on 2026-10-05 (live)

A journey crosses areas, so it can fail where no single area file looks. Each one names the sub-feature IDs it touches, the invariant that must hold across areas, the last live result, and the API path to drive it. For the UI path, follow each area file's "Driving it" bullet for that sub-feature. Use this file for questions like "what happens to X after Y" and for release smoke tests. Journeys run in the order below, and each assumes the state the one before it left.

Preconditions for all: an isolated instance, because these journeys mutate data and inject failures. Run `export CEDARS_VERIFY_INSTANCE=journeys-<date>`, then `$CC doctor` (if your name is UP and you did not start it, pick another), then the README baseline (`stack up`, `seed`). The evidence cited below is on instance `journeys`; a new name keeps it intact. The blocks are copy-pasteable in bash or zsh, in order, in one shell: each one reuses `$CC`, `$P`, `$S`, `$B` and `$RUN` from the block before. `api --field` prints one value, and `api GET … --until PATH=VALUE` polls until it holds (exit 1 on timeout). To run a subset, run journey 1 first, then close each journey's session before the next one clones (commit it as journey 3 does, or `$CC api DELETE $B --expect 200` to discard): a clone is a new session, and it returns 409 while one is draft, reviewing or committed (`evaluation/service.py:78-93`). Counts such as journey 5's 20 annotations assume all five ran. Journey 2 starts from a clone of journey 1's session. Once a session is committed, its results list shows only the pipeline copies (`evaluation/service.py:806-818`), so a re-run's new sample results would be invisible there.

| ID | Journey | Areas | Last live | Result |
|---|---|---|---|---|
| j-evaluate-to-export | Evaluate, commit, full pipeline, annotate, export | evaluation, jobs, annotations, export | 2026-10-05 | PARTIAL: counts agree; event dates dropped; JSON export 500 |
| j-llm-failure-recovery | LLM returns empty, then errors, then recovers | evaluation-run, predictors-nlp | 2026-10-05 | PASS |
| j-worker-crash-recovery | Worker dies mid-run; the run still finishes | jobs, evaluation-run, platform-ops | 2026-10-05 | PASS (WebSocket progress FAIL) |
| j-security-sweep | Security checks across roles (details tracked privately) | projects, evaluation-run, jobs | 2026-10-05 | FAIL (known security defect) |
| j-repeat-commit | A second committed session on the same project | evaluation-run, annotations, export | 2026-10-05 | FAIL: duplicate annotations |
| j-role-sweep | Each role walks every page; UI and API must agree | all | 2026-10-05 (per area, read-only) | FAIL: UI shows controls the API rejects |
| j-review-reopen | Review a patient, reopen it, re-claim it | annotations, patients | not driven | source: decisions wiped, lock kept |
| j-ingest-visibility | Upload, ingest, watch progress, browse patients | data, jobs, patients | 2026-10-05 (seed path) | PARTIAL: counts agree; status lookup loses the job |
| j-deploy-rehearsal | Old release with data, new migration, roll | platform-ops | 2026-10-05 | PASS (64d13687 → cef61132, 16 steps) |
| j-databricks-round-trip | Connect, ingest, evaluate, export to Databricks | data, export | not driven | SKIP: needs a Databricks workspace |

## j-evaluate-to-export

Touches: `data-sample-dataset`, `eval-session-create`, `eval-step1-event`, `eval-step2-queries`, `eval-step2-execute`, `eval-sample-run`, `eval-judgment`, `eval-metrics`, `eval-commit`, `eval-pipeline-stats`, `jobs-page`, `ann-source-commit`, `ann-queue-lock`, `ann-event-date`, `ann-stats`, `export-stats`, `export-csv`, `export-filters`, `export-json`.

Invariants:
1. Patients matched in step 2 = sample results in step 3 (5 = 5 on the sample).
2. Metrics follow judgments: `correct` on a positive is tp, `wrong` is fp, `skipped` is not counted.
3. After commit, `pipeline/stats.completed + failed + no_match` = `total`, and the session reaches `completed`.
4. Annotation rows = `/annotations/stats.total` = `/export/stats.total` = CSV data rows.
5. Each annotation carries the LLM's event date, or the reviewer's override.
6. JSON export returns the same rows as the CSV.

```bash
CC=.claude/skills/verify-cedars/control-cedars; P=/projects/{project}/evaluation/sessions
S=$($CC api POST $P --body '{"search_queries":[]}' --expect 201 --field id); B=$P/$S   # 409 if a draft, reviewing or committed session exists
$CC api PUT $B/event-config --body '{"event_name":"Venous thromboembolism","event_description":"DVT or PE","include_criteria":"","exclude_criteria":""}' --expect 200 --field status
$CC api PUT $B/queries --body '{"search_queries":[{"query":"dvt","type":"include"},{"query":"thrombosis","type":"include"},{"query":"embolism","type":"include"}]}' --expect 200 --field status
$CC api POST $B/queries/execute --body '{}' --expect 200 --save j1-execute       # 5 patients, 10 notes on the sample
$CC api POST $B/run-llm --body '{}' --expect 202 --field status
$CC api GET $B --until metrics.llm_status=completed --until status=reviewing --field metrics   # a few seconds
$CC api GET "$B/results?page_size=100" --save j1-results --field 'results[*].event_date'   # 5 dates, all positive 0.9
n=0; for R in $($CC api GET "$B/results?page_size=100" --field 'results[*].id'); do   # 3 correct, 1 wrong, 1 skipped
  case $n in 3) J=wrong ;; 4) J=skipped ;; *) J=correct ;; esac; n=$((n+1))
  $CC api POST $B/results/$R/judge --body "{\"judgment\":\"$J\"}" --expect 200 --field review_judgment; done
$CC api GET $B/metrics --save j1-metrics                                         # invariant 2
RUN=$($CC api POST $B/commit --body '{}' --expect 200 --field pipeline_run_id)
$CC api GET $B --until status=completed --timeout 180 --field status
$CC api GET $B/pipeline/stats --save j1-pipeline-stats                           # invariant 3
$CC api GET /projects/{project}/annotations/stats --field total; $CC api GET /projects/{project}/export/stats --field total
$CC api GET /projects/{project}/export/annotations/csv --as viewer > /tmp/j1.csv   # count with python csv, not wc -l
python3 -c 'import csv;print(sum(1 for _ in csv.DictReader(open("/tmp/j1.csv"))))'
$CC db query "select count(*), count(event_date) from annotations where project_id='{project}'"   # invariant 5
$CC api GET /projects/{project}/export/annotations --as viewer --expect 200 --save j1-export-json   # invariant 6
```

Last live result (2026-10-05). The blocks in this file were extracted verbatim and run in order on a fresh `seed` (`journeys-from-md-2.log` on instance `journeys`, zsh exit 0):
- Invariants 1-4 PASS: 5 matched patients / 10 notes, the sample classified in 3 s with 5 dates, tp 3 / fp 1 with 1 skipped (accuracy 0.75), the session completed 3 s after commit, pipeline 5/5, then 5 = 5 = 5 = 5.
- Invariant 5 FAIL: all 5 annotations have `event_date` NULL, although every result has a date (`ann-source-commit`).
- Invariant 6 FAIL: HTTP 500 "Internal Server Error". An earlier drive's backend log showed `ResponseValidationError` on `sentence_id` (`export-json`).
- UI path, on a fresh `seed`: the `evaluation-setup.md` steps 1-2 drive and the `evaluation-run.md` steps 3-5 drive both exit 0. They end at "Pipeline complete. 4 patients matched, 1 no match." with 4 annotations: 4 positive, and 0 with an event date, although all 8 result rows have one (invariant 5 FAIL again). A different query set from the API path, so the numbers differ.
- The pipeline made no LLM calls, because it reuses completed sample results (`evaluation/service.py:1194-1225`). The evaluator's verdicts do not carry over: every annotation starts `unreviewed`.

## j-llm-failure-recovery

Touches: `eval-sample-run`, `eval-llm-failure-handling`, `llm-client-providers`, `llm-json-mode`.

Invariant: a broken provider never produces a fabricated label. Each patient fails with a readable error. Re-running after the provider recovers replaces the failed results.

```bash
S=$($CC api POST $P/$S/clone --expect 201 --field id); B=$P/$S                  # draft copy: same event and queries
$CC api POST $B/queries/execute --body '{}' --expect 200 --field matched_patients
$CC llm mode empty; $CC api POST $B/run-llm --body '{}' --expect 202 --field status
$CC api GET $B --until metrics.llm_status=completed --field metrics.llm_failed    # 5, 1 call per patient
$CC api GET "$B/results?page_size=100" --field 'results[*].error_message' | sort | uniq -c   # "Classification response has no 'event_detected' field: {}"
$CC llm mode fail; $CC api POST $B/run-llm --body '{}' --expect 202 --field status   # allowed from reviewing; clears old results
$CC api GET $B --until metrics.llm_status=completed --timeout 400 --field metrics.llm_failed   # 5, 4 calls per patient (3 retries)
$CC api GET "$B/results?page_size=100" --field 'results[*].error_message' | cut -c1-80 | sort | uniq -c   # "litellm.InternalServerError … Retried: 3 times"
$CC llm mode normal; $CC api POST $B/run-llm --body '{}' --expect 202 --field status
$CC api GET $B --until metrics.llm_status=completed --field metrics.llm_completed # 5, positive, event_date set
$CC llm calls                                                                     # counts since stack up; the difference is your cost proxy
```

Last live result (2026-10-05): PASS (`journeys-from-md-2.log` on instance `journeys`). Empty: 5 failed, each with "Classification response has no 'event_detected' field: {}". Fail: 5 failed after 18 s, each with "Classification failed: litellm.InternalServerError…", 4 calls per patient. Normal: 5 completed. Empty replies were silently discarded on Bedrock before cef61132 fixed it; this is that regression check. Run it on a session that was never committed. On a committed one, the results list shows only the earlier pipeline copies, so the failures are invisible (seen live: `5 null` from an earlier draft of this block). With every result failed, `results/next` returns `null` and the metrics are all zeros, and the session stays `reviewing`, so the user's only way out is to re-run. `garbage` mode was not driven.

## j-worker-crash-recovery

Touches: `eval-commit`, `jobs-worker-orphan-recovery`, `eval-orphan-recovery`, `jobs-ws-pipeline-progress`, `jobs-ws-eval-progress`.

Invariant: killing the worker mid-run loses no patients. The run finishes, and the stats agree with the patient results.

```bash
$CC llm mode empty; $CC api POST $B/run-llm --body '{}' --expect 202 --field status   # failed sample results are re-queued on commit
$CC api GET $B --until metrics.llm_status=completed --field metrics.llm_failed    # 5
$CC llm mode slow; RUN=$($CC api POST $B/commit --body '{}' --expect 200 --field pipeline_run_id)
$CC api GET $B/pipeline/stats --until processing=1 --field queued                # 4
$CC ws /ws/projects/{project}/pipeline/$RUN --as admin --seconds 4 --save j3-ws   # should print progress; exit 1 with 0 messages
$CC stack restart worker
$CC llm mode normal; $CC api GET $B --until status=completed --timeout 300 --field status
$CC stack logs worker --since 5m --grep 'Auto-recovered orphaned pipeline run'   # after the wait: the worker logs it a few seconds after start
$CC api GET $B/pipeline/stats --field completed                                  # 5
```

Last live result (2026-10-05, `journeys-from-md-2.log` on instance `journeys`):
- Recovery PASS: the worker logged "Auto-recovered orphaned pipeline run … (1 stuck rows reset)" a few seconds after the restart, and the session completed 5/5 6 s later. The in-flight patient was classified twice; one extra LLM call per crash is the cost. The log line lands after the restart command returns, so grep only after the wait.
- WebSocket FAIL: the pipeline socket closed 1000 with 0 messages (`j3-ws.json`), and the backend logged `sqlalchemy.exc.MissingGreenlet` for that connection (`pipeline/ws.py:34-40`; the eval socket fails the same way, `evaluation/ws.py:31-34`).
- Not reproduced: the ECS rolling-deploy overlap, where old and new workers run together. `stack restart` stops before it starts. See `jobs.md` Gotchas.

## j-security-sweep

Touches: tracked privately.

The invariant, the probes and the results are tracked privately, not in this public repo. The public block below only clones, classifies and commits, so the later journeys' counts still hold.

```bash
S=$($CC api POST $P/$S/clone --expect 201 --field id); B=$P/$S
$CC api POST $B/queries/execute --body '{}' --expect 200 --field matched_patients
$CC api POST $B/run-llm --body '{}' --expect 202 --field status
$CC api GET $B --until metrics.llm_status=completed --until status=reviewing --field status
RUN=$($CC api POST $B/commit --body '{}' --expect 200 --field pipeline_run_id)
$CC api GET $B --until status=completed --timeout 180 --field status
```

Last live result (2026-10-05): FAIL (known security defect).

## j-repeat-commit

Touches: `eval-session-clone`, `eval-commit`, `ann-source-commit`, `ann-patient-status`, `export-stats`.

Invariant: re-evaluating a project replaces or reconciles the earlier annotations. It must not stack new ones on top.

```bash
S=$($CC api POST $P/$S/clone --expect 201 --field id); B=$P/$S                  # 409 while another session is draft, reviewing or committed
$CC api POST $B/queries/execute --body '{}' --expect 200 --field matched_patients
$CC api POST $B/run-llm --body '{}' --expect 202 --field status
$CC api GET $B --until metrics.llm_status=completed --until status=reviewing --field status
RUN=$($CC api POST $B/commit --body '{}' --expect 200 --field pipeline_run_id)
$CC api GET $B --until status=completed --timeout 180 --field status
$CC db query "select patient_id, count(*) from annotations where project_id='{project}' group by 1 order by 2 desc limit 5"
$CC db query "select count(*) annotations, count(distinct pipeline_run_id) runs from annotations where project_id='{project}'"
```

Last live result (2026-10-05): FAIL. After the four commits these journeys make on one project, `annotations` held 20 rows for 5 patients from 4 pipeline runs: 4 per patient, one full set per commit, none dated (`journeys-from-md-2.log` on instance `journeys`; first seen with 15 rows from 3 runs on instance `live`). Patients already REVIEWED come back into the Annotations queue, because the queue picks any patient with an unreviewed label-1 annotation, but their status stays REVIEWED (`review_service.py:204-225`, `:249-250`; source only). `/export/stats.total` grows the same way. The worker does not deduplicate (`worker.py:278-292`). Only one draft, reviewing or committed session can exist per project (`evaluation/service.py:78-93`), so to re-evaluate you discard the current session (`DELETE`, 200, which sets `discarded`) or wait for it to complete. A completed session can also be committed again: `run-llm` has no status check and puts it back to `reviewing` (confirmed live, see `evaluation-run.md` Gotchas).

## j-role-sweep

Touches every `*-role-gating` row, plus `auth-route-guards`, `jobs-cancel-run`, `jobs-rerun`, `patients-reopen-role-gating`, `projects-settings-save`.

Invariant: if the UI shows a control to a role, the API accepts that role. If the API rejects a role, the UI hides the control or explains the denial.

Drive: for each of `viewer` and `annotator`, run each area's role bullets (`--expect 403` on the API, and `browser run` that expects the control). Collect the mismatches.

Last live result (2026-10-05, read-only per area): FAIL. The sidebar is the same for every role (`AppSidebar.tsx:18-26`). These controls render for roles the API rejects:
- Export page for annotators (403);
- Jobs Cancel / Retry failed / Rerun (403, silent);
- project settings Save once the form is dirty (403);
- Data upload and delete;
- patient "Re-open for review".

Gating confirmed live on the API:
- run-llm, commit and discard are admin-only;
- judge accepts admin and annotator, and rejects viewers;
- annotation review rejects viewers;
- `patient/next` rejects viewers.

## j-review-reopen

Touches: `ann-queue-lock`, `ann-review-no-event`, `ann-event-date`, `ann-patient-status`, `ann-reopen`, `patients-reopen`, `patients-status-filter`.

Invariant: reopening a REVIEWED patient keeps its decisions (that is what the confirm text promises) and puts the patient back in the queue for any annotator.

Drive: review every annotation of one patient (`annotations.md` bullets) → Patients "Reviewed" filter shows it → admin `POST /annotations/patient/<id>/reopen` → `db query` the annotations' `review_status`, `event_date` and lock columns → `GET /annotations/patient/next --as annotator`.

Status: not driven. The source says reopen resets every decision (`review_service.py:514-522`) and keeps the old lock (`:511-524`).

## j-ingest-visibility

Touches: `data-sample-dataset`, `data-upload-create`, `data-ingest-start`, `data-ingest-status`, `data-ingest-progress-ws`, `jobs-ws-job-progress`, `jobs-queue-status`, `patients-list`.

Invariant: while ingestion runs, the user can see its progress and cancel it. When it ends, Patients shows every row: 5 patients and 103 notes for the sample.

Drive: `$CC seed --no-upload`, then the `data.md` upload bullets ("Use sample dataset", "Run Ingestion"). Then `$CC api GET /projects/{project}/data/sources/{source}/ingest/status` and `$CC api GET /projects/{project}/data/patients`.

Last live result (2026-10-05, seed path): the counts PASS (5 / 103). `ingest/status` returns `null` once a batch has committed, because the worker overwrites `result_summary.data_source_id` (`jobs/ingestion.py:77-83`). The banner therefore loses the job, and cancel returns 404 after the first 1000 rows.

## j-deploy-rehearsal

Touches: `ops-deploy-runbook`, `ops-deploy-rehearsal`, `ops-migrations`.

Invariant: the AWS runbook keeps the old release serving while the new migration runs, and then the roll succeeds. The order is old tasks + data → migrate task with the new image → old tasks still healthy → force-new-deployment.

```bash
$CC deploy rehearse --from aws          # what DEV runs now (read-only AWS lookup)
$CC deploy rehearse --from 64d13687     # just before b41a98a5; crosses the annotations-columns migration
```

It needs a fresh DB, so give it its own instance (`export CEDARS_VERIFY_INSTANCE=rehearse-<date>`). The last migration landed on 2026-07-02, so any `--from` at or after b41a98a5 tests only the mechanics. Refs before cf2dd65c cannot start: their frontend nginx crashes, as it did on the first ECS deploy. Last result: PASS, with details in `platform-ops.md` under `ops-deploy-rehearsal`.

## j-databricks-round-trip

Touches: `data-databricks-form`, `data-databricks-ingest`, `export-dbx-annotations`, `export-dbx-predictions`, `export-dbx-evaluation`.

SKIP: it needs a Databricks workspace and a token, and the parity stack has neither. The source says 2 of 3 export types crash (`export/databricks.py:141`, `:178-181`), so expect at least those to fail once a workspace is available.
