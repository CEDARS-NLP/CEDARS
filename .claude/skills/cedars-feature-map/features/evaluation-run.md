# Evaluation run

Last verified: cef611321063 on 2026-10-05 (source + live)

Steps 3 to 5 of an evaluation session. Step 3 "Test the model on a sample" runs the project LLM on the sample patients the search matched. Step 4 "Check the model against yourself" is where admins and annotators judge each result and see accuracy, precision, recall and F1. Step 5 "Run it on everyone" commits the session and runs the full pipeline over every patient, with stats, cancel, resume and re-run. Two ARQ jobs do the work (`run_sample_llm_job`, `run_eval_pipeline_job`), and worker startup recovers orphaned full runs. Steps 1 and 2 are in `evaluation-setup.md`. Overall: beta. The happy path works on the fake LLM, and since `cef61132` an empty `{}` reply marks the patient failed instead of a fake negative. But a sample where every patient failed is shown as finished and can be committed. Re-run duplicates annotations. There are also known security defects, tracked privately (not in this public repo). DEV runs `cef61132` (`aws status`, 2026-10-05), so all of this is live on DEV.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| eval-sample-run | "Run on N patients" → `POST run-llm` (202). Clears old sample results, classifies each matched sample patient, writes NO_MATCH for the rest, sets the session REVIEWING | beta | UI+API | cef61132 | 2026-10-05 (UI + API) | `backend/app/evaluation/service.py:496-585`, `:607-779`, `frontend/src/projects/evaluation/SampleRunSection.tsx:66-183`, `tests/test_eval_service.py::TestLlmRun::test_run_llm_creates_patient_results`, `::test_run_llm_creates_no_match_results` |
| eval-sample-progress | Session polls every 3 s while `llm_status` is running. "N of M patients classified", then "Classified N patients, M failed, K had no matching notes." A run idle for 15 min may be restarted | beta | UI+API | 8f2676b6 | 2026-10-05 (UI) | `EvaluationSessionPage.tsx:41-74`, `service.py:39`, `:512-524`, `tests/test_eval_service.py::TestLlmRun::test_run_llm_rejects_concurrent_run`, `::test_run_llm_restarts_stalled_run` |
| eval-llm-failure-handling | A `{}` reply, an HTTP error or non-JSON text makes that patient FAILED with `error_message`. Native JSON mode is sent only to providers that support it | beta | API | cef61132 | 2026-10-05 (UI + API) | `backend/app/pipeline/classifier.py:104-145`, `backend/app/llm/client.py:58`, `:215-217`, `tests/test_pipeline_classifier.py::TestClassifyPatient::test_empty_object_raises_instead_of_defaulting`, `tests/test_llm_client.py::TestJsonModeParam::test_dropped_for_emulating_providers`, `tests/test_eval_service.py::TestLlmRun::test_run_llm_handles_failures` |
| eval-review-queue | One patient at a time: "Patient N of M", "LLM classification" card, matched notes, "Correct", "Wrong", "Skip", "Override event date", keys C W S E ? | beta | UI+API | 5329ec92 | 2026-10-05 (UI + API) | `EvalReviewPanel.tsx:105-544`, `service.py:886-965`, `router.py:320-334`, `tests/test_eval_service.py::TestReviewQueue::test_queue_empties_and_ignores_pipeline_results`, `tests/test_eval_review.py::test_next_unreviewed_returns_result` |
| eval-judgment | `POST results/{id}/judge` with `correct`, `wrong` or `skipped`, plus an optional date override | beta | UI+API | a5b72355 | 2026-10-05 (UI + API) | `service.py:850-883`, `router.py:376-398`, `tests/test_eval_service.py::TestReview::test_submit_judgment`, `::test_submit_judgment_with_date_override` |
| eval-results-browser | Collapsed "Browse every patient in the sample": tabs all, positive, negative, inconclusive, unreviewed. Each card has "Model was right", "Model was wrong", "Skip" | beta | UI+API | cef61132 | 2026-10-05 (UI + API) | `ResultsSection.tsx:27-273`, `service.py:785-847`, `tests/test_eval_service.py::TestListPatientResults::test_list_patient_results_filter_by_label` |
| eval-metrics | Accuracy, Precision, Recall, F1 and "Across N judged patients: …" over judged COMPLETED sample rows. Skips excluded | beta | UI+API | 5329ec92 | 2026-10-05 (UI + API) | `MetricsPanel.tsx:24-70`, `service.py:971-1049`, `tests/test_eval_service.py::TestReview::test_compute_metrics_mixed`, `::test_compute_metrics_preserves_llm_progress` |
| eval-commit | "Commit and run on all patients": REVIEWING → COMMITTED, snapshot to `committed_config`, then dispatch the full run | beta | UI+API | 8f2676b6 | 2026-10-05 (UI + API) | `CommitSection.tsx:42-108`, `service.py:1055-1121`, `:1159-1240`, `router.py:436-463`, `tests/test_eval_service.py::TestCommit::test_commit_session`, `tests/test_eval_router.py::TestCommit::test_commit_requires_reviewing_status` |
| eval-pipeline-stats | Step 5 grid Total, Matched, No match, Failed, Pending. Polls every 3 s while rows are queued or processing | beta | UI+API | 8f2676b6 | 2026-10-05 (UI + API) | `PipelineSection.tsx:34-188`, `service.py:1243-1284`, `router.py:466-479`. No tests |
| eval-pipeline-cancel | "Cancel" while running: run CANCELLED, session DISCARDED | beta | UI+API | f88d0b99 | not driven | `service.py:1287-1315`, `backend/app/pipeline/orchestrator.py:203-237`, `PipelineSection.tsx:115-128`. No tests |
| eval-pipeline-resume | "Resume" while running: PROCESSING rows back to QUEUED, enqueue another job | beta | UI+API | a5b72355 | not driven | `service.py:1355-1397`, `PipelineSection.tsx:101-114`. No tests |
| eval-pipeline-rerun | "Re-run pipeline" when done: new EventConfig and PipelineRun, sample results copied again, the rest queued | beta | UI+API | da6508b6 | not driven | `service.py:1400-1420`, `PipelineSection.tsx:130-143`. No tests |
| eval-pipeline-retry-failed | `POST pipeline/retry-failed` re-queues FAILED rows of one run | api-only | API | f88d0b99 | not driven | `service.py:1318-1352`, `router.py:498-511`. No frontend caller, no tests |
| eval-worker-sample-job | `run_sample_llm_job` wraps `execute_sample_llm` | beta | worker | a5b72355 | 2026-10-05 | `backend/app/worker.py:83-87`, `service.py:588-604` |
| eval-worker-pipeline-job | `run_eval_pipeline_job`: claims QUEUED rows with SKIP LOCKED, searches, classifies, writes one Annotation per classified patient, then annotations for copied sample rows, then COMPLETED | beta | worker | cef61132 | 2026-10-05 | `worker.py:90-381`. No tests (`tests/test_worker.py` covers NLP jobs only) |
| eval-orphan-recovery | Worker startup resets every RUNNING PipelineRun to QUEUED, PROCESSING rows to QUEUED, and re-enqueues it | beta | worker | a5b72355 | 2026-10-05 | `worker.py:384-437`, `:440-457`. No tests |
| eval-pipeline-ws | `/ws/projects/{id}/evaluation/{sid}` pushes pipeline stats | stub | WS | f88d0b99 | 2026-10-05 FAIL | `backend/app/evaluation/ws.py:14-60`, `backend/app/main.py:136`. No frontend caller |

Why the grades:
- **Driven live on 2026-10-05** on an isolated instance (`CEDARS_VERIFY_INSTANCE=live`, fake LLM, amd64).
  - The browser drives below ran as written: happy path, empty mode and viewer, each exit 0. Their follow-up checks matched.
  - Over the API: the fail-mode reply, orphan recovery, and repeat commits.
  - Not driven: cancel, resume, re-run and retry-failed (`eval-pipeline-*`), and `llm mode garbage`.
  - Evidence: `/tmp/cedars-verify/live/evidence/drive-eval-*` and `live-eval*`.
- **eval-sample-run, eval-review-queue, eval-commit** reach a misleading "done" state when every patient failed (see Gotchas). That is a known defect.
- **eval-judgment** has a known security defect (see Gotchas).
- **eval-pipeline-*** and the worker jobs have no tests at all. `test_full_workflow` mocks the dispatch.
- **eval-pipeline-retry-failed** has no UI. The Jobs page "Retry failed" targets PatientTask rows, not eval rows (`orchestrator.py:310-342`, see `jobs.md`).
- **eval-pipeline-ws** has a known security defect, and nothing calls it. Live, it closed with 0 messages for a real session: the status read after `db.expire` (`ws.py:32-34`) raises MissingGreenlet (see `jobs.md`, `jobs-ws-eval-progress`).
- **Tests.** Named tests pass locally on SQLite and on Postgres at cef611321063 (382/382 each). CI has never run them green; see README "Test evidence".

## How to get to it (user POV)

1. Finish steps 1 and 2 (`evaluation-setup.md`). The session page now shows step 3 enabled.
2. The page opens the first unfinished step, here "Test the model on a sample". It lists "Model", "Patients in sample", "Matched the search", "Estimated cost" (always "—"). Click "Run on N patients". When it ends the badge changes from "Draft" to "In review", and the page moves on to step 4 by itself. Reopen step 3 to see "Classified N patients…".
3. Step 4 "Check the model against yourself": the metrics sit on top. Below them the queue shows "Patient 1 of N" and "0 of N judged". Read the matched notes ("Previous note" and "Next note"), then click "Correct", "Wrong" or "Skip", or press C, W, S. "Override event date" (E) opens "Corrected event date". When the queue is empty it says "Every sample patient is judged".
4. Optional: open "Browse every patient in the sample" to filter by tab or change one judgment.
5. Click "Run it on everyone". It shows "Queries to lock", "Patients you judged" and "Agreement so far". Click "Commit and run on all patients". The step then shows the stats grid. While rows are pending it shows "Resume" and "Cancel"; when done, "Pipeline complete. N patients matched, M no match." and "Re-run pipeline".
6. Positive and negative results of the full run appear on the Annotations page (`annotations.md`).

## Driving it with control-cedars

Preconditions: the baseline, `$CC llm mode normal`, then the steps 1-2 drive from `evaluation-setup.md` (`eval-steps-1-2`), then capture `SID` as shown there. Take a timestamp before each drive: `T0=$(date -u +%Y-%m-%dT%H:%M:%S)`. For each failure drive start from a fresh `$CC seed` (for example `$CC seed --project-name drive-empty`), because a project can hold only one active session. `{project}` expands to the latest seed, and the drives click the first session named "Deep vein thrombosis".

- **eval-sample-run**, **eval-sample-progress**, **eval-review-queue**, **eval-judgment**, **eval-metrics**, **eval-commit**, **eval-pipeline-stats**, **eval-worker-pipeline-job**: steps 3 to 5 as admin →
  ```
  $CC browser run - --as admin --save eval-steps-3-5 --timeout 30 <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"text":"Deep vein thrombosis","nth":0}},
   {"expect_url":"/evaluation/[0-9a-f-]{36}$"},
   {"expect_text":"Patients in sample"},
   {"click":{"role":"button","name":"Run on 4 patients"}},
   {"expect_text":"Patient 1 of 4","timeout":180},
   {"expect_text":"In review","exact":true},
   {"expect_text":"Event detected"},
   {"expect_text":"90% likely"},
   {"click":{"role":"button","name":"Test the model on a sample"}},
   {"expect_text":"Classified 4 patients, 1 had no matching notes."},
   {"click":{"role":"button","name":"Check the model against yourself"}},
   {"expect_text":"Patient 1 of 4"},
   {"click":{"role":"button","name":"Correct"}},
   {"expect_text":"1 of 4 judged"},
   {"click":{"role":"button","name":"Correct"}},
   {"expect_text":"2 of 4 judged"},
   {"click":{"role":"button","name":"Correct"}},
   {"expect_text":"3 of 4 judged"},
   {"click":{"role":"button","name":"Correct"}},
   {"expect_text":"Every sample patient is judged"},
   {"expect_text":"Across 4 judged patients: 4 correctly flagged, 0 flagged in error, 0 missed, 0 correctly passed over."},
   {"screenshot":"reviewed"},
   {"click":{"role":"button","name":"Run it on everyone"}},
   {"expect_text":"Agreement so far"},
   {"click":{"role":"button","name":"Commit and run on all patients"}},
   {"expect_text":"Pipeline complete. 4 patients matched, 1 no match.","timeout":120},
   {"expect":{"role":"button","name":"Re-run pipeline"}},
   {"screenshot":"committed"}]
  EOF
  ```
  → exit 0. Then check the state the UI does not show:
  - `$CC llm calls --since "$T0"` → `classify/normal=4`. The full run makes no new calls, because all 5 patients were in the sample and their rows are copied.
  - `$CC api GET "/projects/{project}/evaluation/sessions/$SID/metrics" --as viewer` → `"tp":4,"fp":0,"tn":0,"fn":0,"accuracy":1.0,"f1":1.0,"total_reviewed":4,"total_pending":0`.
  - `$CC api GET "/projects/{project}/evaluation/sessions/$SID/pipeline/stats" --as viewer` → `"total":5,"queued":0,"processing":0,"completed":4,"failed":0,"no_match":1,"is_cancelled":false`.
  - `$CC db query "select status from evaluation_sessions_v2 where id = '$SID'"` → `completed` within a few seconds. The page badge still says "Committed" until reload.
  - `$CC db query "select count(*), sum(predicted_label) from annotations where project_id = (select id from projects order by created_at desc limit 1)"` → `4 | 4`. Add `count(event_date)` → `0`, although all 8 result rows (4 sample, 4 run copies) have a date: the pipeline drops it (`annotations.md`).
  - The review card shows the result's date one day early: "Event: Aug 5, 2018" for a stored `2018-08-06` (see Gotchas).
- **eval-worker-sample-job**: after "Run on 4 patients" in the drive above → `$CC stack logs worker --since 10m --grep run_sample_llm_job` → a `→ …:run_sample_llm_job('<SID>', '<project_id>')` line, then a `←` line with `{'patients_classified': 4, 'patients_no_match': 1, 'patients_failed': 0, …}` (2026-10-05). An all-failed run logs `'patients_failed': 4` with the same `●` success marker: the job itself never fails.
- **eval-results-browser** (read-only: open the cards but do not judge): needs a session in review with nothing judged. `$CC seed`, the steps 1-2 drive and the `SID=` capture in [evaluation-setup.md](evaluation-setup.md), then `$CC api POST "/projects/{project}/evaluation/sessions/$SID/run-llm" --as admin --body '{}' --expect 202`. Poll `$CC api GET "/projects/{project}/evaluation/sessions/$SID"` until `"status":"reviewing"` (a few seconds). The heredoc is unquoted so `$SID` expands; `browser run` itself expands only `{project}` and `{source}` →
  ```
  $CC browser run - --as admin --save eval-results-browser <<EOF
  [{"goto":"/projects/{project}/evaluation/$SID"},
   {"click":{"text":"Browse every patient in the sample"}},
   {"expect_text":"5 patients","exact":true},
   {"click":{"role":"button","name":"positive","exact":true}},
   {"expect_text":"4 patients","exact":true},
   {"click":{"role":"button","name":"negative","exact":true}},
   {"expect_text":"No negative patients in this sample."},
   {"click":{"role":"button","name":"unreviewed","exact":true}},
   {"expect_text":"5 patients","exact":true},
   {"click":{"role":"button","name":"positive","exact":true}},
   {"click":{"role":"button","name":"90% likely","nth":0}},
   {"expect":{"role":"button","name":"Model was right"}},
   {"screenshot":"results-browser"}]
  EOF
  ```
  → exit 0 (2026-10-05, a fresh sample: 4 positive, 1 no match, none judged). `exact` matters: "4 patients" without it also matches the step 3 header "4 patients classified", and "all" matches "Commit and run on all patients". "unreviewed" counts the NO_MATCH row too. API equivalent: `$CC api GET "/projects/{project}/evaluation/sessions/$SID/results?label=positive" --as viewer` → `total: 4`.
- **eval-llm-failure-handling** with `llm mode empty` (the pre-cef61132 Bedrock reply): `$CC seed`, the steps 1-2 drive, capture `SID`, then `$CC llm mode empty` →
  ```
  $CC browser run - --as admin --save eval-empty --timeout 30 <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"text":"Deep vein thrombosis","nth":0}},
   {"expect_text":"Patients in sample"},
   {"click":{"role":"button","name":"Run on 4 patients"}},
   {"expect_text":"Every sample patient is judged","timeout":180},
   {"expect_text":"In review","exact":true},
   {"expect_text":"accuracy against you appears"},
   {"expect_text":"0 patients classified, 4 failed"},
   {"click":{"role":"button","name":"Test the model on a sample"}},
   {"expect_text":"Classified 0 patients, 4 failed, 1 had no matching notes."},
   {"click":{"role":"button","name":"Run it on everyone"}},
   {"expect_text":"judged any sample patients yet"},
   {"expect":{"role":"button","name":"Commit and run on all patients"},"state":"enabled"},
   {"screenshot":"empty"}]
  EOF
  ```
  → exit 0, and that is the defect: nothing was classified, yet step 4 says every patient is judged and commit is offered. The step 3 header summary reads "0 patients classified, 4 failed". Session metrics (`api GET "/projects/{project}/evaluation/sessions/$SID" --as viewer`) → `"status":"reviewing"`, `"llm_status":"completed","llm_total":4,"llm_completed":0,"llm_failed":4,"llm_no_match":1`. `/metrics` → `"total_reviewed":0`. The UI never shows the reason, but the API does: `api GET "…/sessions/$SID/results"` returns each row's `error_message` (that route has no `response_model`, `router.py:337-357`). So does the DB: `$CC db query "select status, error_message, count(*) from patient_results where session_id = '$SID' group by 1, 2"` → `failed | Classification response has no 'event_detected' field: {} | 4` and `no_match | | 1`. `$CC llm calls --since "$T0"` → `classify/empty=4`. Before `cef61132` the same replies became 4 × "No event" at 50% and step 3 read "Classified 4 patients, 1 had no matching notes."
  - Commit in empty mode: "Commit and run on all patients" → the 4 FAILED sample rows are queued again and fail again → "Pipeline complete. 0 patients matched, 1 no match. 4 failed.", session `completed`, 0 annotations, `classify/empty=8` in total.
  - Commit after `$CC llm mode normal` instead: the full run classifies the 4 again (`classify/normal=4`) and shows "4 patients matched, 1 no match.", although no sample result was ever judged.
- **eval-llm-failure-handling** with `llm mode fail` (HTTP 500): same drive with `$CC llm mode fail` → the same UI text as empty mode. `error_message` starts with `Classification failed: ` followed by the LiteLLM error. `llm calls --since "$T0"` shows `classify/fail` of at least 4, up to 16, because LiteLLM may retry each call 3 times (`classifier.py:112`). `llm mode garbage` gives `Could not parse LLM response as JSON: I am unable to classify these notes.` Run `$CC llm mode normal` when done.
- **eval-orphan-recovery**: needs queued rows in a full run. `$CC seed`, steps 1-2, `$CC llm mode fail`, step 3 (4 failed), then `$CC llm mode slow` (20 s per call), commit in the UI ("Commit and run on all patients", expect "Running the committed configuration over every patient in the project."). Within 20 s run `$CC stack restart worker`, then `$CC stack logs worker --since 5m --grep 'orphan'` → `Auto-recovered orphaned pipeline run <id> (1 stuck rows reset)`. Then `$CC llm mode normal`. `$CC api GET "/projects/{project}/evaluation/sessions/$SID/pipeline/stats" --as viewer` → after about a minute `"completed":4,"no_match":1,"failed":0`. If the log says `No orphaned pipeline runs to recover`, the run had already finished.
- **eval-pipeline-resume**: in the same slow full run, before it finishes → `$CC api POST "/projects/{project}/evaluation/sessions/$SID/pipeline/resume" --as admin` → 200 `{"resumed":true,"reset_stuck":1,"remaining_queued":N,"run_id":"…"}`. In the UI, "Resume" does the same with no confirmation of the result. After the run, `$CC db query "select count(*), count(distinct patient_id) from annotations where project_id = (select id from projects order by created_at desc limit 1)"` → when the two counts differ, a patient was classified twice (see Gotchas).
- **eval-pipeline-cancel**: in a slow full run (set up as for orphan recovery, without the restart) →
  ```
  $CC browser run - --as admin --save eval-cancel --timeout 30 <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"text":"Deep vein thrombosis","nth":0}},
   {"expect_text":"Running the committed configuration over every patient in the project."},
   {"click":{"role":"button","name":"Cancel","exact":true}},
   {"expect_text":"This session was discarded. Clone it to start again."},
   {"expect_text":"Discarded","exact":true}]
  EOF
  ```
  → exit 0. `$CC db query "select status, is_cancelled from pipeline_runs where project_id = (select id from projects order by created_at desc limit 1)"` → `cancelled | t` at once. The worker stops after the patient it is on. `$CC api POST "/projects/{project}/evaluation/sessions/$SID/pipeline/rerun" --as admin --expect 400` → `Session must be in committed or completed state to re-run`.
- **eval-pipeline-rerun**: after the happy path, `$CC api POST "/projects/{project}/evaluation/sessions/$SID/pipeline/rerun" --as admin` → 200 `{"run_id":"…","total_patients":5}`, or click "Re-run pipeline". Then `$CC db query "select count(*) from annotations where project_id = (select id from projects order by created_at desc limit 1)"` → `8`, and `select count(*) from event_configs ...` → `2`. Today the results browser lists 10 patient cards.
- **eval-pipeline-retry-failed**: after the empty-mode commit → `$CC llm mode normal`, then `$CC api POST "/projects/{project}/evaluation/sessions/$SID/pipeline/retry-failed" --as admin` → 200 `{"requeued":4,"run_id":"…"}`. Stats then reach `"completed":4`. A second call → 400 `No failed patients to retry`.
- **Role gating** (API): `$CC api POST "/projects/{project}/evaluation/sessions/$SID/run-llm" --as annotator --expect 403`, `$CC api POST "/projects/{project}/evaluation/sessions/$SID/commit" --as annotator --expect 403`, `$CC api GET "/projects/{project}/evaluation/sessions/$SID/results/next" --as viewer --expect 403`, `$CC api POST "/projects/{project}/evaluation/sessions/$SID/pipeline/cancel" --as annotator --expect 403` → `{"detail":"Insufficient permissions"}`. `$CC api POST "/projects/{project}/evaluation/sessions/$SID/results/1/judge" --as viewer --body '{"judgment":"correct"}' --expect 403`. UI defect, on a REVIEWING session with unjudged patients (stop the happy-path drive before the first "Correct") →
  ```
  $CC browser run - --as viewer --save eval-viewer --timeout 30 <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"text":"Deep vein thrombosis","nth":0}},
   {"click":{"role":"button","name":"Test the model on a sample"}},
   {"expect":{"role":"button","name":"Run again on 4 patients"},"state":"enabled"},
   {"click":{"role":"button","name":"Check the model against yourself"}},
   {"expect_text":"Every sample patient is judged"},
   {"expect_no_text":"Patient 1 of 4"},
   {"snapshot":"viewer-step4"}]
  EOF
  ```
  → exit 0 (with `--strict` it exits 1 on the 403 from `GET .../results/next`). That shows the defect: the viewer sees an enabled run button and a queue that claims to be finished. Once fixed, this run should fail.
- **eval-pipeline-ws**: `$CC ws "/ws/projects/{project}/evaluation/$SID" --as admin --seconds 5`. For an existing session expect a close with a server error (MissingGreenlet suspected) and a traceback in `$CC stack logs backend --since 5m --grep 'MissingGreenlet|Traceback'`. Once fixed, an uncommitted session gives `{"type":"status","session_status":"reviewing"}`. An unknown session id gives `{"type":"error","detail":"Session not found"}`.

## Gotchas

- **Known security defects** affect `eval-commit`, `eval-judgment` and `eval-pipeline-ws`. Details are tracked privately, not in this public repo.
- **A sample where every patient failed looks finished.** The job sets REVIEWING whatever happened (`service.py:759-760`). Step 4 unlocks because `llm_status` is "completed" (`EvaluationSessionPage.tsx:92-93`). The queue has no COMPLETED rows, returns null, and the panel says "Every sample patient is judged" (`EvalReviewPanel.tsx:245-257`). Commit is allowed (`service.py:1055-1121`). No evaluation component renders the failure reason. `GET …/results` returns `error_message` because the route has no `response_model` (`router.py:337-357`). `PatientResultResponse` (`schemas.py:137-152`) lacks the field, so adding that schema as the response model would hide the reason from the API too. Confirmed live 2026-10-05 with the empty-mode drive above (exit 0). The red "Classification failed before it finished" notice appears only when the enqueue fails (`SampleRunSection.tsx:143-148`, `service.py:563-580`).
- **Re-run does not reclassify sample patients.** `dispatch_full_pipeline_run` copies every COMPLETED and NO_MATCH sample row into the new run (`service.py:1194-1225`). A committed session cannot re-run its sample from the UI (`SampleRunSection.tsx:66`). So the fabricated "No event, 50%" results from before `cef61132` survive "Re-run pipeline", contrary to that commit's message. Only a clone and a new sample run replaces them. Sample FAILED rows are queued again.
- **Re-run and resume duplicate data.** Each run writes a full set of annotations and never removes the previous run's (`worker.py:261-292`, `:314-366`). The copied-row block runs again on every resume or recovery of the same run. Stats, cancel, resume and retry pick one run with an unordered `distinct().limit(1)` (`service.py:1250-1253`, `:1296-1299`, `:1320-1323`, `:1361-1364`), so after a re-run they may report the old run. The results browser shows the rows of every run (`service.py:809-818`). "Resume" is offered while the run is live (`PipelineSection.tsx:101-114`); it puts the patient being classified back to QUEUED and enqueues a second job (`service.py:1372-1385`). "Re-run pipeline" appears as soon as no rows are pending, before the worker marks the session complete.
- **`run-llm` has no status check.** `run_llm_on_sample` checks only for a running classification (`service.py:510-533`). It deletes the sample results and judgments (`:535-541`), and the job then sets the session REVIEWING (`:759-760`). A COMMITTED, COMPLETED or DISCARDED session goes back to REVIEWING and can be committed a second time. The UI hides the button on locked sessions; the API does not refuse. **Confirmed live 2026-10-05**: `api POST "…/sessions/<completed id>/run-llm" --body '{}'` returned 202. The session went back to `reviewing` with 5 new unjudged sample rows, while the earlier run's 5 copied rows kept their judgments (`live-eval-runllm-on-completed.json`). The project then has an active session again, so `POST /sessions` returns 409. The re-run's results are then hidden: once any pipeline copy exists, `list_patient_results` returns only the copies (`service.py:806-818`), so step 4 and `GET /results` keep showing the earlier run's completed rows, while the DB holds the new ones (seen live on instance `journeys`: 5 failed sample rows listed as 5 completed copies).
- **`submit_judgment` has no status check either**, so locked sessions' judgments can change through the API (`service.py:850-883`). The results browser offers judge buttons on FAILED and NO_MATCH cards (`ResultsSection.tsx:114`, `:190`). `compute_metrics` ignores those judgments (`service.py:984-988`).
- **Role gating in the UI.** Step 3 "Run on N patients", step 5 commit, cancel, resume and re-run render for annotators and viewers. The results browser's judge buttons render for viewers (`ResultsSection.tsx:190`). A viewer's queue call gets 403, and with `retry: false` the panel shows "Every sample patient is judged" (`EvalReviewPanel.tsx:105-114`, `:245`). None of these mutations has error UI except commit and the sample run.
- **Keyboard shortcuts ignore modifiers.** The handler skips inputs and textareas but not Cmd or Ctrl (`EvalReviewPanel.tsx:197-231`). Cmd+C to copy note text judges the patient "correct".
- **A crashed sample run blocks the UI.** There is no recovery for `run_sample_llm_job`; `on_worker_startup` handles PipelineRuns only (`worker.py:384-437`). `llm_status` stays "running", so the button stays "Classifying" and disabled (`SampleRunSection.tsx:150-153`). The stall check reads `updated_at`, but progress writes do not touch it (`service.py:736-746`; the model has no `onupdate`, `models.py:93-96`). Only the run start and each `GET /metrics` set it (`service.py:558`, `:1045`). So the API allows a second run 15 min after the start even while a healthy long run is still going, and before that returns 400 `LLM classification is already running for this session.` Recovery after a crash: once `updated_at` is 15 min old, `POST …/run-llm` (or "Run again") restarts the run, and the backend logs "Restarting stalled sample LLM run" (`service.py:512-524`). Any `GET /metrics` restarts that wait, including a viewer's. MetricsPanel calls it whenever step 4 is open (`StepCard.tsx:84`, `MetricsPanel.tsx:18-24`), and react-query calls it again on window focus. Keep step 4 closed while you wait, or discard the session. Source only; not driven.
- **Orphan recovery treats every RUNNING run as an eval run.** It does not filter by run type (`worker.py:402-428`). A legacy PatientTask run caught by a restart is enqueued as `run_eval_pipeline_job`, finds no PatientResult rows and is marked FAILED (`worker.py:127-131`).
- **Cancel is final.** It discards the session (`service.py:1309-1313`), so PipelineSection hides (`PipelineSection.tsx:32`) and "Pipeline was cancelled…" (`:189-194`) can never render. Re-run then refuses with "Session must be in committed or completed state to re-run" (`service.py:1411-1412`), despite its docstring. Annotations already written stay. A cancel after the run finished returns 400 `Cannot cancel a completed/failed run` (`orchestrator.py:209-210`) with no error UI.
- **Steps open by themselves.** With no step clicked, the page opens the first unfinished one, and that moves as data arrives (`EvaluationSessionPage.tsx:97-110`). A drive that clicks the header of the step that is already open closes it (`:111`). Once one patient is classified, step 4 opens mid-run while the session is still DRAFT, so on a first run it says "This session is locked, so judgments can no longer change." until the run ends (`:91-92`, `:232-243`). The drives above wait for content instead of clicking the current step.
- **The badge lags.** Session polling runs only during a sample run (`EvaluationSessionPage.tsx:41-51`). After the full run ends the badge says "Committed" until reload.
- **Prompts carry whole notes.** Both jobs send the full text of every matched note (`service.py:690-697`, `worker.py:242-249`). Token use grows with note length, and "Estimated cost" is never computed.
- **`GET /metrics` writes.** `compute_metrics` saves the figures into `session.metrics` and bumps `updated_at` on every read, including a viewer's (`service.py:1031-1047`).
- **Enqueue failures after commit are silent.** `_enqueue_eval_pipeline_run` logs and swallows errors (`service.py:42-54`). The session is COMMITTED with every row QUEUED and no job. "Resume" is the only way out.
- **Copied-row annotations point at the patient's first note**, not a matched note, and join every matched sentence of every note into `sentence_text` (`worker.py:323-347`). See `annotations.md`.
- **Event dates display one day early in US time zones.** The stored `event_date` is a date-only string such as `2018-08-06`. `new Date("2018-08-06")` parses it as UTC midnight, and `toLocaleDateString` prints it in the browser's zone, so a reviewer in New York or California sees "Aug 5, 2018". Sites: `EvalReviewPanel.tsx:34-41`, `:361`, `AnnotationsPage.tsx:161-168`, `:1092`, `PatientDetailPage.tsx:226`. The override field prefills with `event_date.slice(0, 10)` (`EvalReviewPanel.tsx:148`), so the card and the field disagree by a day. Seen live 2026-10-05 in the step 4 card (`drive-eval-review-card` snapshot, browser in PDT). Note dates shift the same way: `note_date` is a UTC-midnight timestamp (`2010-01-15T00:00:00Z`), so it also lands on the previous day (`EvalNoteViewer.tsx:80`, `AnnotationsPage.tsx:1305`, `:1350`, `:1384`, `PatientDetailPage.tsx:280`; seen live as "1/14/2010" in `patients.md`). Format with `timeZone: "UTC"` to fix every site.
- **Result cards show the internal patient UUID.** The results browser labels each card with `result.patient_id` (`ResultsSection.tsx:67`), a UUID such as `def5119b-…`, while the step 4 card shows `patient_id_ext` (`EvalReviewPanel.tsx:321`). A reviewer cannot match a browser card to a patient, and nothing on the card links to the patient page. Seen live 2026-10-05.
