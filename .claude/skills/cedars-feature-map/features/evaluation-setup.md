# Evaluation setup

Last verified: cef611321063 on 2026-10-05 (source + live)

An evaluation session is how a project admin defines a clinical event, finds the notes worth reading, and tries the model on a sample before running it on every patient. This file covers the session list, create, clone and discard, the status machine, and steps 1 and 2 of the five-step session page: "Define the event" and "Find the notes worth reading" (queries, LLM suggestions, the search on the sample, the match browser and the funnel). It also covers how steps unlock and the bridge that turns a committed session into a pipeline run. Steps 3 to 5 are in `evaluation-run.md`. Admins drive it. Annotators and viewers can open every page but should only read. The UI lives under sidebar "Evaluation" (`/projects/:id/evaluation`). Overall: beta. The happy path works end to end on the fake LLM, but the UI shows admin controls to every role, the API lets a locked session be edited, and the sample search and the full-run search disagree on negation and exclude queries. DEV runs `cef61132` (`aws status`, 2026-10-05), so everything below is live on DEV. The five-step page came in `8f2676b6`.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| eval-session-list | List page "Evaluation sessions": one card per session with status badge, query count, sample size, judged count and F1 | beta | UI+API | 8f2676b6 | 2026-10-05 (empty list, 3 roles) | `frontend/src/projects/evaluation/EvaluationListPage.tsx:60-160`, `backend/app/evaluation/router.py:93-100`, `tests/test_eval_router.py::TestSessionCRUD::test_list_sessions` |
| eval-session-create | "New session" creates a DRAFT and samples min(100, patients). Blocked while a DRAFT, REVIEWING or COMMITTED session exists | beta | UI+API | 8f2676b6 | 2026-10-05 (UI + API) | `evaluation/service.py:62-140`, `router.py:71-90`, `tests/test_eval_service.py::TestCreateSession::test_create_session_blocks_if_active_exists` |
| eval-session-clone | Icon button "Clone to new session" copies queries and the four event fields into a new DRAFT with a fresh random sample | beta | UI+API | 3d893213 | 2026-10-05 (API) | `service.py:102-113`, `router.py:129-151`, `EvaluationListPage.tsx:118-128`, `tests/test_eval_service.py::TestCreateSession::test_create_session_clones_from_existing` |
| eval-session-discard | Icon button "Discard session" on DRAFT and REVIEWING cards. No confirmation | beta | UI+API | 3d893213 | 2026-10-05 (UI + API) | `service.py:168-190`, `router.py:114-126`, `tests/test_eval_service.py::TestDiscardSession::test_discard_committed_session_fails` |
| eval-status-machine | DRAFT → REVIEWING (sample run ends) → COMMITTED (commit) → COMPLETED (full run ends). DRAFT/REVIEWING → DISCARDED (discard), COMMITTED → DISCARDED (cancel) | beta | API | a5b72355 | 2026-10-05 (API) | `evaluation/models.py:50-96`, `service.py:759-760`, `:1115`, `backend/app/worker.py:368-379`, `tests/test_eval_integration.py::TestUnifiedEvalSessionWorkflow::test_full_workflow` |
| eval-step-unlock | Five step cards. The current step opens by default. Later steps stay locked with a reason until the one before is done | beta | UI | 8f2676b6 | 2026-10-05 (UI) | `EvaluationSessionPage.tsx:86-121`, `StepCard.tsx:40-86`. No frontend tests |
| eval-step1-event | "Define the event": name, description, include and exclude criteria. "Save and continue" opens step 2 | beta | UI+API | 8f2676b6 | 2026-10-05 (UI) | `EventDefinitionSection.tsx:43-166`, `router.py:282-299`, `service.py:219-242`, `tests/test_eval_router.py::TestEventConfig::test_update_event_config` |
| eval-step2-queries | Query rows (type select, text, preview, remove), "Add query", syntax help. Saved by the run button | beta | UI+API | 8f2676b6 | 2026-10-05 (UI + API) | `SearchQueriesSection.tsx:140-233`, `router.py:157-168`, `tests/test_eval_service.py::TestUpdateQueries::test_update_queries_clears_matches` |
| eval-step2-suggest | "Suggest from event definition" asks the project LLM for queries. "Add all", "Dismiss" or per-row "Add" | beta | UI+API | 8f2676b6 | 2026-10-05 (UI, fake LLM) | `query_suggest.py:55-90`, `router.py:171-201`, `SearchQueriesSection.tsx:234-314`. No tests |
| eval-step2-execute | "Save and run search" runs the include queries with spaCy over every note of the sample and stores one row per matched sentence | beta | UI+API | 8f2676b6 | 2026-10-05 (UI + API) | `service.py:248-320`, `router.py:204-215`, `tests/test_eval_service.py::TestExecuteSearchQueries::test_query_index_counts_excluded_queries` |
| eval-step2-match-browser | Chevron "Show matched notes" opens 10 highlighted notes per page for one query | beta | UI+API | 8f2676b6 | 2026-10-05 (UI) | `NotePreviewList.tsx:55-111`, `router.py:218-276`, `service.py:419-490`, `tests/test_eval_service.py::TestGetQueryMatches::test_get_query_matches_pagination` |
| eval-step2-funnel | Sticky bar: sample patients, patients matched (%), and a third stage that always reads "not classified yet" | beta | UI+API | 8f2676b6 | 2026-10-05 (UI) | `FunnelBar.tsx:17-80`, `service.py:326-416`, `schemas.py:70-79`, `tests/test_eval_service.py::TestFunnelStats::test_funnel_stats` |
| eval-bridge-event-config | Commit and re-run create a new synthetic `EventConfig` each time, because `PipelineRun.event_config_id` is NOT NULL | beta | internal | f88d0b99 | 2026-10-05 (via commit) | `service.py:1127-1156`, `:1159-1240`, `backend/app/pipeline/models.py:75`, `:117`. No test (dispatch is mocked in `test_full_workflow`) |

Why the grades:
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
- **Dead code.** `NlpQueriesSection.tsx` is exported but imported nowhere.
