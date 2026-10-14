# Annotations

Last verified: cef611321063 on 2026-10-05 (source + live)

Annotations is step 3 of the project workflow ("Step 3 of 4: Annotations"). Annotators and admins review LLM findings one patient at a time. The page claims and locks the next patient. The reviewer then answers each annotation with "No Event" or "Set Event Date". In v2 the only UI path that creates annotations is committing an evaluation session, whose full pipeline writes one patient-level annotation per matched patient. A separate API-only path, "bulk predictions", runs the active predictor config over spaCy target sentences. The routes are in `backend/app/annotations/router.py`, the page is `frontend/src/projects/AnnotationsPage.tsx`, and patient status lives on `patients.status`. Overall: the patient-first review loop works once a commit has run. It has several data-integrity defects: reopen wipes decisions, label-0 annotations block completion, and locks never expire. Bulk predictions are API-only, and they find 0 sentences once any commit has run.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| ann-source-commit | Committing an evaluation session runs `run_eval_pipeline_job`. It writes one annotation per patient with matched notes: `sentence_id` NULL, `predicted_label` 1 when the LLM said positive, else 0 | beta | UI (via Evaluation) | eb306712 | 2026-10-05 | `backend/app/worker.py:90-381`, `:278-292`, `:315-366`; `evaluation/service.py:1159-1240`. No test runs the job. Live: 5 annotations for 5 patients, all `event_date` NULL although the LLM set one |
| ann-queue-lock | Opening "Annotations" calls `GET /patient/next`. It picks the oldest unlocked patient that has an unreviewed label-1 annotation, locks it to the caller and sets REVIEWING | beta | UI+API | 3c83f16b | 2026-10-05 | `annotations/review_service.py:195-288`, `AnnotationsPage.tsx:508-518`, `tests/test_annotations_api.py::TestPatientReview::test_get_next_patient`, `::test_next_patient_all_complete`. Live: annotator claimed patient A; admin's `patient/next` then returned patient B |
| ann-unlock | Leaving the page, or moving to the next patient, sends `POST /patient/{id}/unlock` through `navigator.sendBeacon` | beta | UI+API | 8a1e3022 | not driven | `AnnotationsPage.tsx:835-845`, `review_service.py:358-387`, `::TestPatientReview::test_unlock_patient` |
| ann-review-no-event | "No Event" (key A) posts `/{id}/review` with `event_date: null`. The annotation becomes reviewed | beta | UI+API | 3c83f16b | not driven | `router.py:330-348`, `review_service.py:51-162`, `AnnotationsPage.tsx:1177-1193`, `::TestAnnotationReview::test_review_annotation`, `::TestPatientReview::test_full_patient_review_flow` |
| ann-event-date | "Set Event Date" (key E) opens an "Event date" input with "Confirm" and "Cancel". When skip-after-event is on, the review also skips the patient's unreviewed annotations from notes on or after that date | beta | UI+API | a5b72355 | 2026-10-05 (API) | `review_service.py:78-139`, `AnnotationsPage.tsx:1196-1253`, `::TestAnnotationReview::test_review_with_event_date`, `::TestPatientReview::test_review_with_event_date_skips_post_event`, `::test_review_event_date_respects_skip_after_event_false` |
| ann-delete-event-date | The trash icon "Delete event date" (key D) on the "Event: ..." chip clears the date and reverts the patient's skipped annotations | beta | UI+API | 3c83f16b | not driven | `review_service.py:390-437`, `AnnotationsPage.tsx:1086-1108`, `::TestPatientReview::test_delete_event_date` (flaky on Postgres CI) |
| ann-skip-api | `POST /{id}/skip` marks one annotation skipped. No button calls it | api-only | API | 3c83f16b | 2026-10-05 | `router.py:370-386`, `review_service.py:165-192`, `::TestAnnotationReview::test_skip_annotation` |
| ann-matched-notes | Pipeline annotations (no `sentence_id`) show "Matched Sentence" and "Full Note" with a "Note i / n" pager. The data is `GET /patient/{id}/matched-notes?annotation_id=` | beta | UI+API | a5b72355 | not driven | `query_service.py:158-340`, `AnnotationsPage.tsx:563-570`, `:1260-1370`, `tests/test_annotation_matched_notes.py::TestMatchedNotesAnnotationFallback::test_prefers_search_match_when_available` |
| ann-context-view | Sentence-level annotations show "Sentence Under Review" plus the note through `GET /{id}/context`. Only the API-only bulk predictions create such annotations | api-only | API (UI branch) | 3c83f16b | 2026-10-05 (API) | `query_service.py:114-155`, `router.py:284-305`, `AnnotationsPage.tsx:553-560`, `:1372-1460`, `::TestAnnotationReview::test_annotation_context` |
| ann-shortcuts | Keys A, E, D, arrows, Shift+arrows, Home, End. "?" or the "Keyboard shortcuts" button opens the "Keyboard Shortcuts" overlay | beta | UI | 8a1e3022 | not driven | `AnnotationsPage.tsx:367-388`, `:775-832`. No frontend tests |
| ann-stats | `GET /stats` drives the header "N/M reviewed \| K remaining". `GET /patient/{id}/stats` drives "Review progress" and the Pending/Done/Skipped tiles | beta | UI+API | 3c83f16b | 2026-10-05 | `query_service.py:68-111`, `review_service.py:440-489`, `AnnotationsPage.tsx:1044-1081`, `:1500-1527`, `::TestAnnotationReview::test_get_stats`, `::TestPatientReview::test_patient_stats`. Live: `events_found` 0 → 1 after one dated review |
| ann-patient-status | Patient status moves NEW → REVIEWING (claimed) → REVIEWED (no unreviewed annotations left). It moves back to REVIEWING on delete-event-date or reopen | beta | UI+API | 3c83f16b | not driven | `connectors/models.py:29-36`, `review_service.py:39-48`, `:247-250`, `:424-428`, `:511` |
| ann-reopen | Admin "Re-open for review" on Patient detail. A REVIEWED patient goes back to REVIEWING and into the queue | beta | UI+API | 4e484c93 | not driven | `router.py:254-265`, `review_service.py:492-531`, `PatientDetailPage.tsx:183-241`. Only `TestReopenPatient::test_reopen_nonexistent_patient` |
| ann-list-api | `GET /annotations` (`status`, `patient_id`, `limit`, `offset`), `GET /{id}`, `GET /next` | api-only | API | 3c83f16b | 2026-10-05 (`[]`) | `router.py:167-205`, `:271-281`, `query_service.py:30-65`, `::TestAnnotationReview::test_list_annotations`, `::test_get_next_unreviewed` |
| ann-estimate | `GET /estimate` gives a token estimate for target sentences that have no annotation. Admin only | api-only | API | 3c83f16b | 2026-10-05 (0 sentences) | `router.py:97-107`, `prediction_service.py:109-154`. No test |
| ann-predictions-run | `POST /predictions/run` queues `run_prediction_job` on ARQ (or runs in-process when no worker answers). It runs the active predictor over every unannotated target sentence | api-only | API | d97d1890 | not driven | `prediction_service.py:157-236`, `jobs/prediction.py:64-160`, `tests/test_prediction_dispatch_api.py::TestPredictionJobDispatch::test_run_dispatches_job`, `tests/test_prediction_job.py::test_processes_all_sentences_per_patient` |
| ann-bulk-run-sync | `POST /run` does the same work synchronously, inside the request | api-only | API | 3c83f16b | not driven | `router.py:110-124`, `prediction_service.py:22-106`, `::TestBulkRun::test_run_predictions`, `::test_run_without_predictor` |
| ann-predictions-status | `GET /predictions/status` returns the latest prediction job, or `null` | api-only | API | d97d1890 | 2026-10-05 (`null`) | `router.py:141-148`, `prediction_service.py:239-263`, `::TestPredictionJobDispatch::test_status_returns_job_info` |
| ann-predictions-cancel | `POST /predictions/cancel` flags the running job. The job stops before the next patient | api-only | API | d97d1890 | not driven | `prediction_service.py:266-300`, `jobs/prediction.py:107-116`, `::test_cancel_returns_404_when_no_running_job`, `tests/test_prediction_job.py::test_cancellation_stops_after_current_patient` |
| ann-role-gating | Admin and annotator can claim and review. Viewers can read stats and lists. Anonymous callers get 401. Estimate, bulk runs, cancel and reopen are admin only | beta | UI+API | 3c83f16b | 2026-10-05 | `router.py:97-386`, `dependencies.py:33-58`, `components/AppSidebar.tsx:24` |

Why the grades:
- **Review loop rows** (`ann-queue-lock` through `ann-delete-event-date`, `ann-stats`, `ann-patient-status`) are capped at beta by the defects in Gotchas: label-0 annotations block completion, locks never expire, and keyboard A re-reviews items. None can be driven live until a commit has run. `test_delete_event_date` also fails intermittently on Postgres CI (IndexError at `tests/test_annotations_api.py:421`: the list is empty after `/patient/next`).
- **ann-source-commit**: the commit-time `confidence_threshold` is ignored, sample-copied annotations point at the wrong note, and no test runs the job.
- **ann-reopen**: wipes every decision, although the UI and the docstring say decisions are kept.
- **Bulk prediction rows**: no page calls them. The old Predictor and Pipeline pages were removed in 27320f5f.
- **ann-role-gating**: viewers see the "Annotations" link and get a misleading empty state, not a "read only" message.

## How to get to it (user POV)

1. Log in as an annotator or admin. On "Projects", open the project.
2. Annotations exist only after an admin commits an evaluation session and its full pipeline finishes (see [evaluation-run.md](evaluation-run.md)). Before that the page shows "No annotations yet". It suggests "Validate and activate a predictor in Evaluation", which is stale wording.
3. Open the page one of three ways:
   - the sidebar link "Annotations";
   - the "Annotations" card ("Review predictions") on Overview;
   - the "Workflow steps" breadcrumb.
4. The page claims a patient and shows the region "Patient annotation review":
   - a top bar with "Previous annotation" / "Next annotation", "i of n", one dot per annotation (`Annotation i: <status>`), a status badge and "Keyboard shortcuts";
   - a left panel with "Review progress" and the Pending/Done/Skipped tiles, the "AI Prediction" card ("Event Detected", "NN% likely", "Reasoning", "Model:"), "No Event" (A) and "Set Event Date" (E);
   - a right panel with "Matched Sentence" (with a note pager) and "Full Note".
5. Click "No Event", or click "Set Event Date", pick a date in "Event date" and click "Confirm". When the patient has no unreviewed annotation left, the page shows "Patient <id> complete — ..." and "Loading next patient...", then claims the next patient.
6. Once the queue is empty: "All patients reviewed". If every remaining patient is locked by someone else: "No patients available".
7. Admins can reopen a reviewed patient from Patients → patient → "Re-open for review".

## Driving it with control-cedars

Preconditions: the baseline, **plus the evaluation-run journey committed first**: drive `eval-commit` in [evaluation-run.md](evaluation-run.md) and wait until its full pipeline run is COMPLETED. A fresh seed has 0 annotations, all 5 patients NEW and 0 sentences (checked live 2026-10-05). Only the empty-state, stats and gating checks run before a commit. The review steps change data, so run them only in the mutation pass. Shorthand used below: `PROJ="(select id from projects order by created_at desc limit 1)"`.

- **ann-source-commit**: confirm the precondition, that the evaluation-run journey `eval-commit` ([evaluation-run.md](evaluation-run.md)) has run → `$CC db query "select predicted_label, review_status, count(*), count(sentence_id) from annotations where project_id = $PROJ group by 1,2"` → before the commit, 0 rows. After it, one row per matched patient: `count(sentence_id)` is 0, label 1 for patients the fake LLM marks positive (`dvt`/`thromb`/`embol` with no negation cue), all `unreviewed`.
- **ann-stats**: read the stats of the empty project (read-only) → `$CC api GET /projects/{project}/annotations/stats --as viewer` → HTTP 200 `{"total":0,"unreviewed":0,"reviewed":0,"skipped":0,"events_found":0,"is_complete":false}` (driven 2026-10-05). After a commit, `total` equals the number of label-1 annotations, not all annotations. Then `$CC browser snapshot /projects/{project}/annotations --as annotator --wait-text 'No annotations yet'` → `heading "Annotation Review"`, `status` "No annotations yet" (driven 2026-10-05).
- **ann-queue-lock**: the annotator opens the page and claims a patient →
  ```
  $CC browser run - --as annotator --save ann-claim <<'EOF'
  [{"goto":"/projects/{project}/annotations"},
   {"expect":{"role":"region","name":"Patient annotation review"}},
   {"expect":{"role":"navigation","name":"Annotation sequence"}},
   {"expect_text":"AI Prediction"},
   {"expect_text":"Event Detected"},
   {"expect":{"role":"button","name":"No Event"},"state":"enabled"},
   {"screenshot":"claimed"}]
  EOF
  ```
  → exit 0. Then `$CC db query "select patient_id_ext, status, locked_by is not null as locked from patients where project_id = $PROJ order by created_at"` → the oldest patient with a label-1 annotation is REVIEWING with `locked = t`. The lock **stays** after the run: closing the browser does not unmount React, so no unlock beacon is sent.
- **ann-unlock**: leave the page through in-app navigation, which unmounts it →
  ```
  $CC browser run - --as annotator --save ann-unlock <<'EOF'
  [{"goto":"/projects/{project}/annotations"},
   {"expect":{"role":"region","name":"Patient annotation review"}},
   {"click":{"role":"link","name":"Patients","exact":true}},
   {"expect_url":"/patients$"},
   {"wait":1}]
  EOF
  ```
  → the same `db query` shows `locked = f`, and status is still REVIEWING. Unlocking someone else's patient is a silent no-op: `$CC api POST /projects/{project}/annotations/patient/<patient_id>/unlock --as admin` returns HTTP 200 `{"ok":true}`, and the annotator's lock stays.
- **ann-review-no-event**:
  ```
  $CC browser run - --as annotator --save ann-no-event <<'EOF'
  [{"goto":"/projects/{project}/annotations"},
   {"click":{"role":"button","name":"No Event"}},
   {"expect_text":"complete —"},
   {"expect_text":"Loading next patient..."},
   {"screenshot":"after"}]
  EOF
  ```
  → pipeline patients have one annotation each, so one click completes the patient. `$CC db query "select status from patients where patient_id_ext = '<ext>' and project_id = $PROJ"` → `REVIEWED`.
- **ann-event-date**:
  ```
  $CC browser run - --as annotator --save ann-event-date <<'EOF'
  [{"goto":"/projects/{project}/annotations"},
   {"click":{"role":"button","name":"Set Event Date"}},
   {"fill":{"label":"Event date","exact":true},"value":"2024-01-15"},
   {"click":{"role":"button","name":"Confirm","exact":true}},
   {"expect_text":"1 event"},
   {"screenshot":"after"}]
  EOF
  ```
  → `$CC db query "select event_date, review_status from annotations where project_id = $PROJ and event_date is not null"` → one row, `2024-01-15 00:00:00+00`, `reviewed`. Skipping only shows with several annotations per patient, which pipeline runs never create (see Gotchas).
- **ann-delete-event-date**: needs a patient that is still open with a date set. Pipeline patients complete in one action, so drive it with the API instead: `$CC api POST /projects/{project}/annotations/<annotation_id>/delete-event-date --as annotator` → HTTP 200 `{"annotation":{"event_date":null,"review_status":"unreviewed",...},"reverted_count":N}`. Repeat the call → 404 `Annotation not found or no event date set`. In the UI the control is `{"role":"button","name":"Delete event date"}`.
- **ann-shortcuts**:
  ```
  $CC browser run - --as annotator --save ann-shortcuts <<'EOF'
  [{"goto":"/projects/{project}/annotations"},
   {"click":{"role":"button","name":"Keyboard shortcuts"}},
   {"expect":{"role":"heading","name":"Keyboard Shortcuts"}},
   {"press":"Escape"},
   {"press":"e"},
   {"expect":{"label":"Event date","exact":true}},
   {"screenshot":"shortcuts"}]
  EOF
  ```
  → the overlay opens and E shows the date input. Do not press A in a shared stack, because it submits a review.
- **ann-patient-status**: follow the status through the bullets above with `$CC db query "select patient_id_ext, status, locked_by is not null as locked from patients where project_id = $PROJ order by 1"` → NEW before the claim, REVIEWING and locked after `ann-queue-lock`, REVIEWED after `ann-review-no-event`, and REVIEWING again after `ann-delete-event-date` or `ann-reopen`.
- **ann-skip-api** (mutating): no button calls it. Pick an annotation id from `$CC db query "select a.id, p.patient_id_ext, p.status from annotations a join patients p on p.id = a.patient_id where a.project_id = $PROJ"`, then `$CC api POST /projects/{project}/annotations/<annotation_id>/skip --as viewer --expect 403` → `Insufficient permissions`. `--as annotator` → HTTP 200, `review_status: "skipped"`, `reviewed_by` set. Re-run the `db query` → the patient is REVIEWED. Driven 2026-10-05 on a NEW, unlocked patient that nobody had claimed: it went straight to REVIEWED (see Gotchas).
- **ann-context-view**: `$CC api GET /projects/{project}/annotations/<annotation_id>/context --as viewer --save ann-context` → HTTP 200 with `text`, `text_id`, `note_date`, `note_tags`, `sentences` and `search_keywords`. On a pipeline annotation (driven 2026-10-05) it also returns 200, with `sentences: []` and the session's include keywords (`["dvt","thromb"]`), but the page never calls it for those (`AnnotationsPage.tsx:559`). Unknown id → `--expect 404` `Annotation not found`. The "Sentence Under Review" UI branch needs a sentence-level annotation from `ann-predictions-run`.
- **ann-matched-notes**: after the claim → `$CC api GET '/projects/{project}/annotations/patient/<patient_id>/matched-notes?annotation_id=<annotation_id>' --as viewer` → HTTP 200 with the matched notes. Without `annotation_id` the call returns 422 `Field required` (driven 2026-10-05). In the UI, check `expect_text` "Matched Sentence" and "Note 1 /".
- **ann-reopen**: admin only → `$CC api POST /projects/{project}/annotations/patient/<patient_id>/reopen --as annotator --expect 403`. Then as admin → HTTP 200 `{"ok":true}`. `$CC db query "select review_status, event_date from annotations where patient_id = '<patient_id>'"` → `unreviewed`, NULL: the decisions are gone, despite the confirm text. The UI flow is in [patients.md](patients.md).
- **ann-list-api**: `$CC api GET '/projects/{project}/annotations?status=unreviewed&limit=5' --as viewer` → HTTP 200 array (`[]` on a fresh seed, driven 2026-10-05). `$CC api GET /projects/{project}/annotations/00000000-0000-0000-0000-000000000000 --as viewer --expect 404` → `{"detail":"Annotation not found"}` (driven 2026-10-05).
- **ann-estimate**: `$CC api GET /projects/{project}/annotations/estimate --as admin` → HTTP 200 `{"sentence_count":0,"estimated_prompt_tokens":0,...}` (driven 2026-10-05). It stays 0 after any commit (see Gotchas).
- **ann-predictions-run / ann-bulk-run-sync**: needs an active predictor config and NLP target sentences, both API-only. See `pred-crud`, `pred-activate` and `nlp-run` in [predictors-nlp.md](predictors-nlp.md). Then `$CC api POST /projects/{project}/annotations/predictions/run --as admin` → HTTP 200 job. With no active predictor → 400 `No active predictor configured for this project`. With the fake LLM every bulk prediction comes back label 0, so nothing reaches the review queue (see Gotchas).
- **ann-predictions-status**: `$CC api GET /projects/{project}/annotations/predictions/status --as viewer` → HTTP 200 `null` before any job (driven 2026-10-05).
- **ann-predictions-cancel**: `$CC api POST /projects/{project}/annotations/predictions/cancel --as admin --expect 404` with no job running → `No running prediction job found`.
- **ann-role-gating**: all read-only, driven 2026-10-05:
  - `$CC api GET /projects/{project}/annotations/patient/next --as viewer --expect 403` → `{"detail":"Insufficient permissions"}`. The same holds for `/annotations/next`.
  - `$CC api GET /projects/{project}/annotations/estimate --as annotator --expect 403`.
  - `$CC api GET /projects/{project}/annotations/stats --as anon --expect 401` → `Not authenticated`.
  - UI defect check, after a commit: `$CC browser snapshot /projects/{project}/annotations --as viewer --wait-text 'No patients available'` → the viewer gets a 403 on `patient/next` and sees "All patients may be locked by other reviewers", not a read-only notice.

## Gotchas

- **A second commit re-queues reviewed patients.** The queue picks any patient with an unreviewed label-1 annotation, whatever its status (`review_service.py:204-225`). Claiming leaves REVIEWED as it is (`:249-250`). After a second commit, a REVIEWED patient returns to the queue with the new run's annotations, while Patients still shows it "Reviewed". Source only (see `j-repeat-commit`).
- **Skip ignores the claim and the lock.** `skip_annotation` loads the annotation by project and id and never checks `locked_by` (`review_service.py:165-192`). Any admin or annotator can skip annotations on a patient that someone else has locked, or that nobody has claimed. With no unreviewed annotations left, `_check_patient_completion` (`:21-48`) moves the patient to REVIEWED. Live 2026-10-05: a NEW, unlocked patient went straight to REVIEWED, without ever being REVIEWING.
- **Annotations come only from a commit.** On a fresh seed the page shows "No annotations yet", and its hint ("Validate and activate a predictor in Evaluation") points at a flow that no longer exists (`AnnotationsPage.tsx:1550-1557`; predictor pages removed in 27320f5f). The real source is `run_eval_pipeline_job` (`worker.py:90-381`), whose only entry point is the evaluation commit (`evaluation/service.py:1159-1240`).
- **Label-0 annotations block completion.** The review page and queue show only `predicted_label == 1` (`review_service.py:209`, `:309`), but completion counts unreviewed annotations of every label (`review_service.py:27-37`):
  - a patient with a label-0 annotation therefore never reaches REVIEWED;
  - committing twice gives each patient a second annotation, because the worker does not deduplicate (`worker.py:278-292`), so a positive-then-negative patient is stuck in REVIEWING;
  - a failed bulk prediction is saved with `predicted_label` NULL (`jobs/prediction.py:131-143`), with the same effect;
  - `/stats` counts label 1 only (`query_service.py:79`), so a project whose annotations are all label 0 shows "No annotations yet";
  - per-patient stats count every label (`review_service.py:446-453`).
- **The pipeline drops the LLM's event date and the evaluator's verdict.** In the evaluation, the LLM finds an event date for each patient (`patient_results.event_date`), and the evaluator can confirm it or override it (`reviewer_date_override`). Neither reaches the annotation: both `Annotation(...)` constructors leave `event_date` unset and `review_status` UNREVIEWED (`worker.py:278-292`, `:353-366`). So annotators re-review patients the evaluator already judged, starting from a blank date. Live 2026-10-05: 5 results with dates, then 5 annotations with `event_date` NULL; a result judged `correct` with an override still came out unreviewed. Whether a sample-phase verdict should pre-fill the annotation is a product decision. The dropped LLM date is a defect either way.
- **Reopen wipes decisions.** `reopen_patient` resets `review_status`, `reviewed_by`, `reviewed_at` and `event_date` on every annotation of the patient (`review_service.py:514-522`). The docstring says "Preserves annotation decisions" (`router.py:261`), and the confirm text says "Existing decisions are preserved" (`PatientDetailPage.tsx:186`). Reopen also leaves `locked_by` set, so only the previous lock holder can claim the patient again (`review_service.py:220`). The audit log keeps the only trace: `annotation_reviewed` and `event_date_set` rows, the latter with the date (`review_service.py:145-155`), readable through `GET /projects/{project}/patients/<uuid>/activity` by admins and annotators (`admin-audit.md`).
- **Locks never expire.** `locked_at` is written (`review_service.py:248`) but nothing reads it. Only the holder can unlock, and anyone else's unlock is a silent no-op (`review_service.py:358-387`). The beacon unlock runs in a React effect cleanup (`AnnotationsPage.tsx:835-845`), which fires on in-app navigation or a patient change, but not on tab close, reload or crash. It also fails once the access token has expired. In those cases the patient stays locked until the same user comes back. No admin control clears it. Completing a patient does not clear the lock either (`review_service.py:39-48`).
- **Refetching re-locks.** `GET /patient/next` both reads and locks, and react-query refetches it on window focus (`App.tsx:23`, `new QueryClient()` with the defaults; `AnnotationsPage.tsx:508-518`). Every refocus re-runs the claim and writes another PATIENT_LOCKED audit row (`review_service.py:254-257`).
- **No lock or status check on review.** `review_annotation` does not check `review_status` or the lock holder (`review_service.py:51-73`). Any admin or annotator can review any annotation by ID, and re-reviewing overwrites `reviewed_by`. The "No Event" button is disabled for reviewed items (`AnnotationsPage.tsx:1178-1181`), but key A is not (`:720-723`).
- **Shortcuts ignore modifier keys.** `e.key.toLowerCase()` is matched without checking Ctrl or Meta (`AnnotationsPage.tsx:783`). So Cmd/Ctrl+A submits "No Event", and Ctrl/Cmd+D deletes the event date. Only inputs and textareas are excluded (`:777-781`).
- **The event chip can show the day before.** The date is sent as `YYYY-MM-DDT00:00:00Z` (`AnnotationsPage.tsx:729`), and `formatDate` renders it in local time (`:161-168`). West of UTC the "Event:" chip shows the previous day.
- **Skip-after-event barely applies to pipeline annotations.** The pipeline writes one annotation per patient, so the event-date review completes the patient and `skipped_count` is 0. Skips need several annotations per patient, which only bulk predictions create. The flag comes from the project setting "Skip annotations after event date" (`ProjectOverview.tsx:381-386`) or from any active NLP query with `skip_after_event` (`review_service.py:82-100`). The NLP query flag defaults to True (`nlp/schemas.py:10-15`).
- **Delete-event-date reverts every skip for the patient**, not only the skips that this event date caused (`review_service.py:408-416`). A REVIEWED patient goes back to REVIEWING (`:424-428`).
- **No Skip button.** `POST /{id}/skip` exists (`router.py:370`), but the page has no control for it, and the header counts only `reviewed` (`AnnotationsPage.tsx:1500-1510`). Overview counts reviewed + skipped (`ProjectOverview.tsx:496`).
- **The commit threshold is ignored.** `commit_session` stores `confidence_threshold` (`evaluation/service.py:1110-1111`), but the worker labels on `classification.label` alone (`worker.py:285`).
- **Sample-copied annotations point at the wrong note.** For patients carried over from the sample run, `note_id` is the patient's first note by date, not the first matched note (`worker.py:331`). Their keyword text includes negated matches (`:340`), exclude queries are not applied (`:336`), and the reviewer's sample judgment is not carried over (they start `unreviewed`, `:362`).
- **Bulk predictions find nothing after a commit.** The "already annotated" check is `Sentence.id NOT IN (select sentence_id from annotations)` (`prediction_service.py:49-63`, `:114-124`, `jobs/prediction.py:79-92`). Pipeline annotations have `sentence_id` NULL, and SQL `NOT IN` with a NULL in the list matches no rows, so the run and the estimate return 0 sentences. The estimate also skips the `Note.deleted_at` filter (`prediction_service.py:120-124`).
- **Bulk prediction jobs.** There is no guard against concurrent jobs (`prediction_service.py:157-236`), so two runs can annotate the same sentences. A cancel during the last patient is overwritten with COMPLETED (`jobs/prediction.py:107-116` vs `:157-160`). With the fake LLM, `LLMPredictor` prompts never match the fake's excerpt format, so every bulk prediction is label 0, score 0.15 (`predictors/llm.py:39-58` vs `verify-cedars/stack/fake_llm.py:39-42`, `:78-84`).
- **NLP reprocess deletes reviewed annotations.** `POST /nlp/reprocess` runs `DELETE FROM annotations WHERE project_id` (`nlp/service.py:403-406`), pipeline annotations and decisions included, with no confirmation. See [predictors-nlp.md](predictors-nlp.md).
- **Statuses that never occur.** `NLP_PROCESSING` is never set anywhere. `NLP_COMPLETE` is set only by NLP reprocess (`nlp/service.py:408-412`). The Patients filter still offers both (`PatientsPage.tsx:38-41`).
- **Accessibility gaps.** The note-pager icon buttons have no accessible name (`AnnotationsPage.tsx:1280-1300`), so use `nth` or css. The overlay close button has none either (`:370-375`). Use the "Note i / n" text to assert position.
- **eslint `set-state-in-effect`** fires at `AnnotationsPage.tsx:574`, `:584` and `:770`: the effects reset the note index, the current index and the event-date default.
- **Matched-notes needs `annotation_id`.** Without it the call returns 422 (driven). It prefers `SearchMatch` rows for the session and falls back to scanning the annotations (`query_service.py:158-340`).
- **Dates display one day early west of UTC.** `formatDate` parses the stored date as UTC and prints it in the browser's zone (`AnnotationsPage.tsx:161-168`), both for the "Event:" label (`:1092`) and for note dates (`:1305`, `:1350`, `:1384`). A stored `2018-08-06` shows as Aug 5. On this page the defect is confirmed from source only. The identical code was seen live on the evaluation review card (`evaluation-run.md` Gotchas) and on patient note dates (`patients.md`).
