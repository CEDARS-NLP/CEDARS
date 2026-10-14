# Evaluation setup

Last verified: db8175b73584 on 2026-10-13 (source + targeted local tests; uncommitted implementation, not a deployment)

Evaluation now opens a session list with "Create evaluation session". New and cloned sessions use `workflow_version=2`: save queries first, optionally preview the sample, then choose "Run on all patients" (keyword-only) or "Define an event" (LLM). Project admins manage revisions and runs; annotators may judge successful LLM sample results; viewers read history. The UI is under `/projects/:id/evaluation`. Overall: beta, with SQLite and frontend evidence but no PostgreSQL or live browser proof for this implementation. Existing version-1 sessions retain the five-step renderer and legacy execution; stable row IDs below are not current step numbers. The October 5 AWS snapshot does not establish deployment of these uncommitted changes.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| eval-session-list | Session list is the sole entry; no standalone search/LLM mode cards or NlpQueriesSection rendering | beta | UI+API | uncommitted | not driven (legacy list: 2026-10-05) | `frontend/src/projects/evaluation/EvaluationListPage.tsx`, `EvaluationListPage.test.tsx`, `backend/app/evaluation/router.py` |
| eval-session-create | "Create evaluation session" creates a version-2 draft; one active session per project; admin controls are gated | beta | UI+API | uncommitted | not driven (legacy create: 2026-10-05) | `backend/app/evaluation/router.py:71`, `frontend/src/projects/evaluation/EvaluationListPage.test.tsx` |
| eval-session-clone | Clone starts version 2 with new session-owned revisions, not another session's revision IDs | beta | UI+API | uncommitted | not driven (legacy clone: 2026-10-05) | `backend/app/evaluation/router.py:129`, `backend/app/evaluation/service.py`, `tests/test_query_first_evaluation.py` |
| eval-session-discard | Icon button "Discard session" on DRAFT and REVIEWING cards. No confirmation | beta | UI+API | 3d893213 | 2026-10-05 (UI + API) | `service.py:168-190`, `router.py:114-126`, `tests/test_eval_service.py::TestDiscardSession::test_discard_committed_session_fails` |
| eval-status-machine | Session status coexists with per-attempt queued/running/completed/failed/cancelled state; version-2 locked sessions reject draft mutations | beta | UI+API | uncommitted | not driven (legacy states: 2026-10-05) | `backend/app/evaluation/query_first.py:44`, `query_first_router.py`, `evaluation/models.py:242` |
| eval-step-unlock | Save valid queries before branching; preview is optional; unsaved queries hide run actions; version 1 retains five steps | beta | UI | uncommitted | not driven (legacy steps: 2026-10-05) | `frontend/src/projects/evaluation/QueryFirstSessionPage.tsx:99`, `QueryFirstSessionPage.test.tsx`, `EvaluationSessionPage.test.tsx` |
| eval-step1-event | Optional "Define an event" after queries; "Save event" snapshots the four event fields and project model | beta | UI+API | uncommitted | not driven (legacy event: 2026-10-05) | `QueryFirstSessionPage.tsx:122`, `backend/app/evaluation/query_first.py:130`, `query_first_router.py:86` |
| eval-step2-queries | First section "Search queries": include/exclude rows, "Save queries", compiled expression, global negation checkbox default true | beta | UI+API | uncommitted | not driven (legacy queries: 2026-10-05) | `QueryFirstSessionPage.tsx:170`, `backend/app/evaluation/query_first.py:92`, `tests/test_query_expression.py` |
| eval-step2-suggest | Legacy "Suggest from event definition" remains version-1 only; new query-first editor does not expose suggestion controls | beta | legacy UI+API | 8f2676b6 | 2026-10-05 (legacy only) | `SearchQueriesSection.tsx`, `backend/app/evaluation/router.py:171`, `QueryFirstSessionPage.tsx` |
| eval-step2-execute | "Preview sample" creates a search/sample attempt; LLM sample also searches its saved query automatically | beta | UI+API | uncommitted | not driven (legacy execute: 2026-10-05) | `backend/app/evaluation/query_first_router.py:135`, `query_first.py`, `tests/test_query_first_evaluation.py` |
| eval-step2-match-browser | Selected attempt's "Matched notes": distinct notes, 10/page, highlighted retained hits and named pagination | beta | UI+API | uncommitted | not driven (legacy browser: 2026-10-05) | `frontend/src/projects/evaluation/AttemptReview.tsx:174`, `backend/app/evaluation/query_first_router.py:201`, `AttemptReview.test.tsx` |
| eval-step2-funnel | Version 2 displays selected-attempt metrics and results; old sticky funnel remains version-1 only | beta | UI+API | uncommitted | not driven (legacy funnel: 2026-10-05) | `AttemptReview.tsx:134`, `backend/app/evaluation/query_first.py`, `FunnelBar.tsx` |
| eval-bridge-event-config | Full attempts still create a synthetic EventConfig for the non-null run FK; keyword-only mode needs no LLM config | beta | internal | uncommitted | not driven (legacy bridge: 2026-10-05) | `backend/app/evaluation/query_first.py`, `backend/app/pipeline/models.py`, `tests/test_query_first_evaluation.py` |
| eval-query-revisions | Immutable session-owned combined SearchQuery per save; structured rows, syntax version and negation setting; draft stays inactive | beta | UI+API | uncommitted | not driven | `backend/app/evaluation/query_first.py:92`, `backend/app/nlp/models.py`, `tests/test_query_first_evaluation.py` |
| eval-prompt-revisions | Immutable event/template/version/provider/model/API-base/non-secret settings snapshot; runtime credentials must match provider and endpoint | beta | UI+API | uncommitted | not driven | `backend/app/evaluation/query_first.py:130`, `:277`, `evaluation/models.py:218`, `tests/test_query_first_evaluation.py` |
| eval-attempt-history | "Selected attempt" scopes query/prompt display, matches, results, judgments and metrics; draft edits retain prior attempts | beta | UI+API | uncommitted | not driven | `QueryFirstSessionPage.tsx:143`, `AttemptReview.tsx:21`, `evaluation/models.py:242`, `tests/test_query_first_evaluation.py` |
| eval-query-activation | Only keyword-only full run or selected LLM attempt commit activates that saved query; project has at most one active undeleted query | beta | UI+API | uncommitted | not driven | `backend/app/evaluation/query_first.py`, `backend/app/nlp/models.py`, `tests/test_query_first_evaluation.py` |

Why the grades:
- **October 13 session final evidence:** native main backend full suite 500 passed, 65.82% coverage (floor 60%), 17 legacy enum serializer warnings; scratch SQLite query migration tests 13 passed. Native ruff passed; mypy ratchet 422 existing vs baseline 497 unchanged, 0 new errors. Earlier query-first/expression slice 58 passed and combined SQLite slice 102 passed. Skill CLI frontend PASS: all 4 npm checks, 57 tests, 10 prior warnings and bundle advisory. The prescribed backend CLI lane remains blocked by missing Windows `python3`; see README for commands, frontend log and verification limits. No new row is stable or live-proven; no CI-green claim.
- **Legacy evidence below is historical only.** Its role, parser, unlock and destructive-edit findings do not describe the version-2 implementation. Legacy source/drives were not re-driven October 13.
- **Driven live on 2026-10-05** on an isolated instance with the fake LLM.
  - Browser drives below, each exit 0: steps 1-2, `eval-locks` and `eval-discard`. Each ran on a fresh `seed --project-name …`.
  - Over the API: create (and its 409), clone, discard, and every status change through to COMPLETED, including the `run-llm` bounce from COMPLETED back to REVIEWING.
  - One commit made one EventConfig and one PipelineRun.
  - Not driven: the suggest failure modes, and the match-browser count defect.
- **Role gating** is a defect on every UI row. The list shows "New session" enabled to viewers (seen live). The session page shows the step 1 and step 2 editors to annotators and viewers, and every save, suggest and run returns 403 for them.
- **eval-step2-suggest** has no test at all, and the fake LLM is its only live check.
- **eval-step2-match-browser** reports sentence matches as "notes" and counts patients on the current page only.
- **eval-step2-funnel** shows a third stage, but `llm_positive` and `estimated_cost` are never populated (`service.py:405-416`). That part is a stub; the first two stages work.
- **eval-status-machine** can be pushed back to REVIEWING from any state by `run-llm` (see `evaluation-run.md`, Gotchas).
- **Tests.** All the tests named here pass locally on SQLite and on Postgres at cef611321063 (382/382 on each). CI has never run them green; see README "Test evidence". No eval test checks a 403.

## How to get to it (user POV)

Current version 2: open "Evaluation", select "Create evaluation session", enter include/exclude rows, leave or change "Exclude negated keywords", and select "Save queries". After a valid save, use "Preview sample", "Run on all patients", or "Define an event". The latter exposes the event fields and "Save event", then "Run LLM sample". Use "Attempt history" / "Selected attempt" to inspect retained revisions and results. Admin actions are disabled or hidden for non-admins; annotators can review, viewers cannot judge. Locked sessions show history without draft edits.

### Legacy version-1 navigation (October 5)

1. Log in. On "Projects", open the project.
2. Click sidebar "Evaluation" (every role sees it). The project Overview's "Evaluation" step ("Configure search, LLM, and evaluate") links here too once data exists.
3. The list shows heading "Evaluation sessions". With no sessions it reads "No sessions yet. Start one to define an event and try it on a sample."
4. Click "New session". The page opens on the new session with heading "Untitled session" and badge "Draft".
5. Step 1 "Define the event" is open. Fill "Event name" (placeholder "Pulmonary embolism"), "What happened to the patient", "Counts as the event" and optionally "Does not count". Click "Save and continue".
6. Step 2 "Find the notes worth reading" opens. Click "Suggest from event definition", then "Add all", or type queries after "Add query". Each row has a select "Include"/"Exclude", the query text, a chevron "Show matched notes", and a remove button.
7. Click "Save and run search". The line "Last search matched N patients in the sample." appears and the bar at the top updates: "N patients in the sample", "M matched the search (X%)".
8. Click a chevron to browse matched notes, "N notes from M patients", "Page X of Y".
9. Back on the list, each card has "Clone to new session" (not on discarded cards) and "Discard session" (draft and in-review only).

## Driving it with control-cedars

### Version-2 drives (not driven)

Preconditions: README baseline on a migrated isolated stack; admin for writes. The CLI adds `/api/v1` to these API paths. Capture IDs from responses, not from guessed latest rows:

```bash
SID=$($CC api POST /projects/{project}/evaluation/sessions --as admin --body '{"search_queries":[]}' --expect 201 --field id)
B=/projects/{project}/evaluation/sessions/$SID/v2
Q=$($CC api PUT $B/queries --as admin --body '{"search_queries":[{"query":"DVT","type":"include"},{"query":"thromb*","type":"include"},{"query":"suspected","type":"exclude"},{"query":"family history","type":"exclude"}],"exclude_negated":true}' --expect 200 --field id)
```

- **eval-session-list / eval-session-create / eval-step-unlock**: `$CC browser snapshot /projects/{project}/evaluation --as admin` shows "Create evaluation session" and no mode cards. New session shows "Search queries" before event fields; run buttons appear only after valid save. `$CC api GET /projects/{project}/evaluation/sessions --as viewer` returns 200 and the new session has `workflow_version: 2`.
- **eval-step2-queries / eval-query-revisions**: `$CC api GET $B/state --as viewer` returns `query_revision.id=$Q`, revision 1, `exclude_negated:true`, source rows and a canonical OR/include AND NOT OR/exclude expression. Read-only `$CC db query "select is_active, syntax_version from search_queries where id='$Q'"` returns false/2. Blank, malformed or exclude-only query saves return 422; a second valid save makes revision 2 without changing revision 1.
- **eval-step2-execute / eval-step2-match-browser / eval-step2-funnel / eval-attempt-history**: `A=$($CC api POST $B/preview --as admin --body "{\"query_id\":\"$Q\"}" --expect 200 --field id)` then `$CC api GET "$B/attempts/$A/matches?page=1&page_size=10" --as viewer` returns note-based pagination; `$CC api GET $B/attempts/$A --as viewer` contains matches, results and metrics. A zero-match completed preview is valid, not "not searched". UI select "Selected attempt" and check "Matched notes", "Metrics", and named pager buttons.
- **eval-step1-event / eval-prompt-revisions**: `$CC api PUT $B/prompt --as admin --body '{"event_name":"DVT","event_description":"Confirmed deep vein thrombosis","include_criteria":"Confirmed diagnosis","exclude_criteria":"Rule-out only"}' --expect 200` returns a prompt revision with project provider/model. Save its `id` as `$PR` for the run drives. Changing project model then saving creates another revision; the old model remains on the old revision. Provider/endpoint mismatch at execution is guarded; API keys are not stored in prompt revisions.
- **eval-query-activation / eval-bridge-event-config**: follow `eval-keyword-only-run` or `eval-attempt-commit` in [evaluation-run.md](evaluation-run.md). Save, preview and LLM sample must leave the prior active query unchanged; the full action activates its selected query, not the latest draft. Read-only `$CC db query "select count(*) from search_queries where project_id='{project}' and is_active and deleted_at is null"` must be at most 1; PostgreSQL concurrency proof is pending.
- **eval-session-clone / eval-session-discard / eval-status-machine**: after discarding a draft (`DELETE /projects/{project}/evaluation/sessions/$SID`, admin, 200), `POST /projects/{project}/evaluation/sessions/$SID/clone` returns 201, version 2 and new owned revision IDs. `PUT $B/queries` on the discarded source returns 409. Version-2 calls on a version-1 session return 409; legacy mutation/execution endpoints on version 2 return 409.
- **Role cases**: query/prompt saves, preview, run-all, run-llm and commit require admin (platform admins bypass project checks); repeat a valid write `--as annotator --expect 403` and `--as viewer --expect 403`. State, attempt, matches and results accept viewer. Judgment accepts admin/annotator only; exact drive in [evaluation-run.md](evaluation-run.md).

### Legacy version-1 drives (October 5 evidence only)

The following commands and expected counts require an existing version-1 session. Their create/clone commands now create version 2, so they are historical transcripts, not a runnable fresh-project setup. Use the version-2 section above for current entry and API contracts.

Preconditions: the baseline, with `$CC llm mode normal` and no DRAFT, REVIEWING or COMMITTED session in the project (`seed` gives a fresh project with none). Capture the newest session id after a session exists:

```bash
SID=$($CC db query "select id from evaluation_sessions_v2 where project_id = (select id from projects order by created_at desc limit 1) order by created_at desc limit 1" --csv 2>/dev/null | tail -1)
```

Expected numbers on the seeded data (5 patients, 103 notes, queries `DVT` and `thromb*`): 4 patients and 13 notes match, `filter_percent` 87.4. Patient `1111111111` only mentions DVT negated, so it does not match.

- **eval-session-list**: read as each role → `$CC api GET /projects/{project}/evaluation/sessions --as viewer --save eval-list` → HTTP 200 `[]` on a fresh seed (driven 2026-10-05 as admin, annotator and viewer). `--as anon --expect 401` → `{"detail":"Not authenticated"}` (driven). UI: `$CC browser snapshot /projects/{project}/evaluation --as viewer --wait-text 'Evaluation sessions' --save eval-list-ui` → heading "Evaluation sessions" and the empty-state text (driven). The snapshot also shows button "New session" enabled for a viewer, which is the role-gating defect.
- **eval-session-create** and **eval-step1-event** and **eval-step2-suggest** and **eval-step2-execute** and **eval-step2-match-browser** and **eval-step2-funnel**: steps 1 and 2 as admin →
  ```
  $CC browser run - --as admin --save eval-steps-1-2 --timeout 30 <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"role":"button","name":"New session","exact":true}},
   {"expect_url":"/evaluation/[0-9a-f-]{36}$"},
   {"expect":{"role":"heading","name":"Untitled session"}},
   {"expect_text":"Draft","exact":true},
   {"fill":{"label":"Event name"},"value":"Deep vein thrombosis"},
   {"fill":{"label":"What happened to the patient"},"value":"A confirmed DVT or thrombosis during follow-up."},
   {"fill":{"label":"Counts as the event"},"value":"DVT on Doppler, or thrombosis named as an active diagnosis."},
   {"click":{"role":"button","name":"Save and continue"}},
   {"expect":{"role":"heading","name":"Deep vein thrombosis"}},
   {"click":{"role":"button","name":"Suggest from event definition"}},
   {"expect_text":"Suggested for"},
   {"click":{"role":"button","name":"Add all"}},
   {"expect":{"label":"Query 2"}},
   {"click":{"role":"button","name":"Save and run search"}},
   {"expect_text":"Last search matched 4 patients in the sample.","timeout":60},
   {"expect_text":"matched the search (80%)"},
   {"expect_text":"not classified yet"},
   {"click":{"role":"button","name":"Show matched notes","nth":0}},
   {"expect_text":"7 notes from 4 patients"},
   {"screenshot":"searched"}]
  EOF
  ```
  → exit 0. Then `$CC llm calls` → `suggest/normal=1` and no classify calls. Confirm the stored state: `$CC api GET "/projects/{project}/evaluation/sessions/$SID/funnel" --as viewer` → `"sample_patients":5,"sample_notes":103,"matched_patients":4,"matched_notes":13,"filter_percent":87.4`, `"llm_positive":null`. `$CC api GET "/projects/{project}/evaluation/sessions/$SID" --as viewer` → `"status":"draft"`, `"search_queries":[{"query":"DVT","type":"include"},{"query":"thromb*","type":"include"}]`.
- **eval-step2-match-browser** count defect: `$CC api GET "/projects/{project}/evaluation/sessions/$SID/queries/1/matches?page=1&page_size=10" --as viewer` → `"total_notes":11,"total_pages":2`, although `thromb*` matches 9 notes. `total_patients` counts only the 10 rows on that page.
- **eval-session-create** blocking and gating: with the draft above, `$CC api POST /projects/{project}/evaluation/sessions --as admin --body '{"search_queries":[]}' --expect 409` → `Cannot create session: project already has a draft session`. `--as viewer` and `--as annotator` with `--expect 403` → `{"detail":"Insufficient permissions"}`.
- **eval-step2-queries** gating: `$CC api PUT "/projects/{project}/evaluation/sessions/$SID/queries" --as annotator --body '{"search_queries":[{"query":"DVT"}]}' --expect 403`, and the same for `PUT .../event-config` (body `{"event_name":"x","event_description":"","include_criteria":""}`), `POST .../queries/execute` and `POST .../queries/suggest` (body `{"description":"x"}`) → 403. UI defect: `$CC browser snapshot "/projects/{project}/evaluation/$SID" --as annotator --wait-text 'Find the notes worth reading' --save eval-session-annotator` → the step 1 form with "Save and continue" is visible to an annotator.
- **eval-step2-suggest** failures: `$CC llm mode empty`, then `$CC api POST "/projects/{project}/evaluation/sessions/$SID/queries/suggest" --as admin --body '{"description":"Deep vein thrombosis"}' --expect 502` → `{"detail":"Expected JSON array of query suggestions"}`. `$CC llm mode fail` and the same call → 502 `Query suggestion failed: ...` (the LiteLLM error text). In the UI both show as a red box under the step 2 buttons. `$CC llm mode normal` afterwards. With no LLM provider on the project the call returns 400 `Project LLM configuration is required. Set it in project settings.`
- **eval-step-unlock**: on a new draft →
  ```
  $CC browser run - --as admin --save eval-locks <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"role":"button","name":"New session","exact":true}},
   {"expect":{"label":"Event name"}},
   {"expect":{"role":"button","name":"Find the notes worth reading"},"state":"disabled"},
   {"expect_text":"Define the event first — queries are built from it."},
   {"expect":{"role":"button","name":"Test the model on a sample"},"state":"disabled"},
   {"expect":{"role":"button","name":"Check the model against yourself"},"state":"disabled"},
   {"expect":{"role":"button","name":"Run it on everyone"},"state":"disabled"}]
  EOF
  ```
  → exit 0. After the steps 1-2 run, step 3 is enabled and steps 4 and 5 stay disabled until a sample run finishes.
- **eval-session-discard**: on a draft →
  ```
  $CC browser run - --as admin --save eval-discard <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"role":"button","name":"Discard session","nth":0}},
   {"expect_text":"Discarded","exact":true},
   {"expect":{"role":"button","name":"New session","exact":true},"state":"enabled"}]
  EOF
  ```
  → exit 0. `$CC db query "select status from evaluation_sessions_v2 where id = '$SID'"` → `discarded`. A committed session gives `$CC api DELETE "/projects/{project}/evaluation/sessions/$SID" --as admin --expect 409` → `Cannot discard session in committed status; ...`.
- **eval-session-clone**: needs a discarded or completed source and no active session. `$CC api POST "/projects/{project}/evaluation/sessions/$SID/clone" --as admin --expect 201 --save eval-clone` → new `"status":"draft"`, same `event_name` and `search_queries`, `"cloned_from_id"` = `$SID`, `"sample_size":5`. In the UI, the card icon "Clone to new session" does the same and opens the new session. Discarded cards have no clone icon, so a discarded session can only be cloned through the API.
- **eval-status-machine**: after each step of the full drive in `evaluation-run.md` → `$CC db query "select status, metrics->>'llm_status' from evaluation_sessions_v2 where id = '$SID'"` → `draft` after steps 1-2, `reviewing / completed` after step 3, `committed` straight after commit, `completed` once the worker finishes.
- **eval-bridge-event-config**: after a commit → `$CC db query "select count(*), bool_and(is_committed) from event_configs where project_id = (select id from projects order by created_at desc limit 1)"` → `1 | t`. Each "Re-run pipeline" adds one more row. `$CC db query "select run_type, status, total_patients from pipeline_runs where project_id = (select id from projects order by created_at desc limit 1)"` → `full | completed | 5`.

## Gotchas

Version-2 limits: PostgreSQL migration/locking, full-stack worker/dispatch recovery, browser desktop/mobile and AWS/DEV proof remain pending. `doctor` on instance `query-first-20261013` was blocked by missing `docker` (`WinError 2`); no live checks followed. Include rows OR together; exclude rows veto matching sentences, not entire notes/patients. Clinical negation is a separate default-true setting, with the existing detector's limitations (see [predictors-nlp.md](predictors-nlp.md)). Full qualifying note text can still contain excluded sentences: selection is not redaction.

### Legacy findings (not assertions about all current rows)

- **"New session" also matches "Clone to new session".** Role names match as case-insensitive substrings, so once a completed session exists, `{"role":"button","name":"New session"}` finds 2 elements and the click fails in strict mode. The drives above use `"exact":true`. A fresh project hides this because it has no clone icons.
- **Admin controls render for every role.** "New session" checks only for an active or committed session (`EvaluationListPage.tsx:71-77`). Clone and discard icons, the step 1 form and the step 2 editor have no role check (`EventDefinitionSection.tsx:43`, `SearchQueriesSection.tsx:62`). The API requires admin (`router.py:71-299`). The list page has no error UI for these mutations, so a viewer's click does nothing visible.
- **A locked session can still be edited through the API.** `update_queries` and `update_llm_config` have no status check (`service.py:193-242`). `execute_search_queries` has none either (`service.py:248`). The UI hides the editors once the session is committed, completed or discarded (`EvaluationSessionPage.tsx:87`).
- **`eval-session-clone` has a known security defect.** Details are tracked privately, not in this public repo.
- **Sampling includes soft-deleted patients.** `create_session` selects `Patient.project_id` only (`service.py:115-121`). The full run counts non-deleted patients (`service.py:1159-1240`).
- **The sample search and the full-run search disagree.** The sample stores only sentences where `is_target and not is_negated` and runs only `type == "include"` queries (`service.py:286`, `:299`). The full run treats any type other than "exclude" as include, counts a note when `is_target or matched_tokens` (so negated mentions count), and drops notes that match an exclude query (`worker.py:144-149`, `:215`, `:221-228`). So the full run can match patients the sample said had no match. The step 2 notice says exclude queries "do not yet narrow the search" (`SearchQueriesSection.tsx:316-322`), which is true for the sample only.
- **The query syntax help is misleading.** "!suspected — drops negated mentions" (`SearchQueriesSection.tsx:261`). In the engine `!term` vetoes the sentence, and negation is detected separately (`backend/app/nlp/engine.py:218-222`). See `predictors-nlp.md` for AND, OR and phrase handling.
- **Match browser counts.** `total_notes` is the number of matched sentence rows, not notes (`service.py:435-441`). `total_patients` is the distinct patients on the current page (`router.py:262-264`). Rows have no ORDER BY (`service.py:444-452`) and fetch each note one by one (`:459-462`). `note_date` and `note_type` are always null (`router.py:254-255`).
- **The match response mislabels queries after an exclude.** The service uses the full-list index (`service.py:286`), but the router looks the query text up among include queries only (`router.py:233-235`).
- **Suggest output is not validated.** `type` is passed through whatever the model returns (`query_suggest.py:80-86`). A suggestion with `"type":"maybe"` is saved, and the sample then ignores it while the full run treats it as include.
- **Funnel third stage never fills.** `get_funnel_stats` never returns `llm_positive` or `estimated_cost` (`service.py:405-416`), so the bar always reads "— not classified yet" and the cost line never shows (`FunnelBar.tsx:44-54`). Step 3's "Estimated cost" is always "—" (`SampleRunSection.tsx:77-92`).
- **Step 1 keeps step 2 open.** After "Save and continue" the page pins `openStep` to 2 (`EvaluationSessionPage.tsx:160`), so later steps never auto-open. Drives must click each step header. While step 2 is locked, its header text contains "Define the event", so `{"role":"button","name":"Define the event"}` matches two buttons and a strict click fails.
- **Editing queries on a reviewed session relocks steps 3 to 5.** `update_queries` deletes the search matches (`tests/test_eval_service.py::TestUpdateQueries::test_update_queries_clears_matches`). `searched` then becomes false (`EvaluationSessionPage.tsx:91`), while the old patient results stay.
- **Unnamed and title-only controls.** The preview chevron and "Remove query N" are icon buttons named by `title` or `aria-label` (`SearchQueriesSection.tsx:176-204`). The match browser pager buttons have no name (`NotePreviewList.tsx:88-106`); use `{"css":"..."}` or `nth`. List cards are clickable divs, not links (`EvaluationListPage.tsx:98-104`); click the event name with `{"text":"...","nth":0}`.
- **A missing session spins forever.** `/projects/{project}/evaluation/<unknown id>` shows "Loading session…" with a 404 in the background (`EvaluationSessionPage.tsx:82-84`). Driven 2026-10-05 with the zero UUID; the API returns 404 `Session not found`.
- **"Clone it to start again" has no button.** A discarded session's step 5 says so (`EvaluationSessionPage.tsx:290-292`), but the page has no clone control and the list hides it for discarded cards (`EvaluationListPage.tsx:118`).
- **Every commit and re-run creates a new `EventConfig`.** `_get_or_create_event_config_for_session` never reuses one (`service.py:1127-1156`). These configs show up wherever event configs are listed (see `jobs.md`).
- **Standalone NLP UI removed from current entry.** `NlpQueriesSection.tsx` still exists, but the new `EvaluationListPage.tsx` no longer imports/renders it. The previous list did render it; "always orphaned" was inaccurate. Legacy `/nlp/*` APIs remain; new sessions use revision-owned `/v2/*` calls.
