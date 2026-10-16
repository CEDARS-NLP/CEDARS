# Evaluation setup

Last verified: working tree on 2026-10-15 (source; working tree/not committed; local tests only)

An admin starts a session with step 1 "Find the notes worth reading"; step 2 "Define the event" unlocks after a valid query is saved, even with zero sample matches. Local include/exclude rows save as one combined include expression, not constituent project SearchQuery records. Step 1 offers optional "Run on all patients" through existing keyword-only NLP, without an event, provider or model; the retained LLM sample/review/commit path is in `evaluation-run.md`. The sidebar "Evaluation" list (`/projects/:id/evaluation`) is now the evaluation-session list only ("Evaluation sessions"); the former "Run a search query" keyword-NLP mode was removed because a session's "Run on all patients" covers it. Step 1 also has a "Remove negated matches" checkbox (default on); unchecking stores negated matches with `is_negated=true`, counts them in the funnel, sends them to the LLM and annotates them, with strikethrough in previews. Overall: beta. Role mismatches, match-browser counts and LLM workflow defects remain. Source reviewed on 2026-10-15 in the working tree/not committed; changed behavior is not deployed/live verified. The DEV snapshot and live observations from 2026-10-05 are historical only.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| eval-session-list | "Evaluation sessions" list: session cards with status, query count, sample size, judged count and F1. The former "Run a search query" keyword-NLP mode was removed; sessions cover it via "Run on all patients" | beta | UI+API | working tree/not committed | not driven (Docker unavailable) | `frontend/src/projects/evaluation/EvaluationListPage.tsx`, `tests/test_eval_router.py::TestSessionCRUD::test_list_sessions` |
| eval-session-create | "New session" creates a DRAFT and samples min(100, patients). Blocked while a DRAFT, REVIEWING or COMMITTED session exists | beta | UI+API | 8f2676b6 | 2026-10-05 (UI + API) | `evaluation/service.py:62-140`, `router.py:71-90`, `tests/test_eval_service.py::TestCreateSession::test_create_session_blocks_if_active_exists` |
| eval-session-clone | Icon button "Clone to new session" copies queries and the four event fields into a new DRAFT with a fresh random sample | beta | UI+API | 3d893213 | 2026-10-05 (API) | `service.py:102-113`, `router.py:129-151`, `EvaluationListPage.tsx:118-128`, `tests/test_eval_service.py::TestCreateSession::test_create_session_clones_from_existing` |
| eval-session-discard | Icon button "Discard session" on DRAFT and REVIEWING cards. No confirmation | beta | UI+API | 3d893213 | 2026-10-05 (UI + API) | `service.py:168-190`, `router.py:114-126`, `tests/test_eval_service.py::TestDiscardSession::test_discard_committed_session_fails` |
| eval-status-machine | DRAFT → REVIEWING (sample run ends) → COMMITTED (commit) → COMPLETED (full run ends). DRAFT/REVIEWING → DISCARDED (discard), COMMITTED → DISCARDED (cancel) | beta | API | a5b72355 | 2026-10-05 (API) | `evaluation/models.py:50-96`, `service.py:759-760`, `:1115`, `backend/app/worker.py:368-379`, `tests/test_eval_integration.py::TestUnifiedEvalSessionWorkflow::test_full_workflow` |
| eval-step-unlock | Query-first step 1 opens by default; saved query unlocks event step 2 even with zero matches. Step 3 still requires event, sample matches and a fresh search | beta | UI | working tree/not committed | not driven (Docker unavailable) | `EvaluationSessionPage.tsx:80-188`, `EvaluationSessionPage.test.tsx`: "opens the query editor before event definition", "unlocks event entry with a saved query even with zero sample matches" |
| eval-step1-event | Stable legacy ID: now step 2 "Define the event"; name, description, include/exclude criteria. "Save and continue" selects step 3 | beta | UI+API | working tree/not committed | not driven (Docker unavailable) | `EvaluationSessionPage.tsx:164-180`, `service.py:227-265`, `tests/test_eval_router.py::TestEventConfig::test_update_event_config`, `tests/test_eval_router.py::TestQueries::test_locked_query_and_prompt_edits_rejected` |
| eval-step2-queries | Stable legacy ID: now step 1. Editable local rows save/continue/run as one validated combined expression; no constituent SearchQuery records and no activation on save or sample search. "Remove negated matches" checkbox (default on) rides along on save; unchecking keeps negated matches through search, LLM and annotation | beta | UI+API | working tree/not committed | not driven (Docker unavailable) | `SearchQueriesSection.tsx`, `backend/app/evaluation/query_expression.py:6-35`, `tests/test_eval_service.py::test_normalizes_draft_without_creating_search_query_records`, `SearchQueriesSection.test.tsx`: "replaces the row draft with the normalized single query returned by saving", `tests/test_eval_service.py::TestExecuteSearchQueries::test_execute_search_stores_negated_when_kept` |
| eval-step2-suggest | In step 1, "Suggest from event definition" stays disabled until step 2 has an event brief; suggestions become local rows via "Add all" or "Add", then normalize on save | beta | UI+API | working tree/not committed | not driven (Docker unavailable) | `SearchQueriesSection.tsx:152-158`, `:288-366`, `query_suggest.py:55-90`. Suggestion happy path retains only historical fake-LLM evidence |
| eval-step2-execute | In step 1, "Save and run search" / "Run search" evaluates the session's combined expression over sample notes, including sentence-scoped exclusions, independently of the active project query | beta | UI+API | working tree/not committed | not driven (Docker unavailable) | `service.py:310-390`, `tests/test_eval_service.py::test_sample_uses_own_combined_expression_not_active_query`, `::test_query_index_is_zero_after_exclude_normalization` |
| eval-step2-match-browser | "Show matched notes" previews the single saved Query 1 at index 0; pagination/count defects remain | beta | UI+API | working tree/not committed | not driven (Docker unavailable) | `SearchQueriesSection.tsx:249-281`, `tests/test_eval_service.py::test_query_index_is_zero_after_exclude_normalization`, `::test_get_query_matches_pagination` |
| eval-step2-funnel | Sticky bar: sample patients, patients matched (%), and a third stage that always reads "not classified yet" | beta | UI+API | 8f2676b6 | 2026-10-05 (UI) | `FunnelBar.tsx:17-80`, `service.py:326-416`, `schemas.py:70-79`, `tests/test_eval_service.py::TestFunnelStats::test_funnel_stats` |
| eval-bridge-event-config | Commit and re-run create a new synthetic `EventConfig` each time, because `PipelineRun.event_config_id` is NOT NULL | beta | internal | f88d0b99 | 2026-10-05 (via commit) | `service.py:1127-1156`, `:1159-1240`, `backend/app/pipeline/models.py:75`, `:117`. No test (dispatch is mocked in `test_full_workflow`) |

Why the grades:
- **Current local evidence (2026-10-14).** Full backend SQLite suite via uv with the configured `.venv-test` interpreter PASS: 473 tests, 66.19% coverage, two pre-existing enum serialization warnings. `control-cedars test frontend` PASS across typecheck, lint, Vitest and build; the subsequent focused rerun PASS includes 3 EvaluationSessionPage and 15 SearchQueriesSection cases. Standalone uv Playwright with a synthetic API captured 1440x960 desktop and 390x844 mobile screenshots in `C:/tmp/cedars-verify/query-first-20261014/evidence/`: `query-first-desktop.png`, `query-first-mobile.png`, `query-confirmation-desktop.png`, and `query-confirmation-mobile.png`. Desktop query actions, confirmation dialog and cancellation visually PASS. The browser found query saving auto-unmounted step 1 before the dialog appeared; fixed by `onQueriesSaved` pinning step 1 (`EvaluationSessionPage.tsx:155`), with a page regression exercising the actual cache update. Mobile has no document overflow, but inspected screenshots show pre-existing sidebar crowding/clipping (see Gotchas), so mobile visual PASS is not claimed. This synthetic browser evidence is not a live backend, LLM or DEV drive. Mypy ratchet PASS: 425 <= 497; dependency audit PASS against unchanged baseline (106 Python / 2 npm high-critical findings); test-removal guard PASS with no removals or skips. The native backend verifier stopped at missing Windows `python3`; the uv fallback suite and ratchet executed. CI status is blocked by missing `gh`; Docker blocks doctor/parity/Postgres/live, and Terraform blocks infra validation. No live/deployed promotion is claimed for working tree/not committed behavior.
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
- **Historical tests.** The then-existing tests passed locally on SQLite and Postgres at cef611321063 (382/382 each, 2026-10-05). That does not verify the current working tree. Current run-all tests include project-role 403 checks (`tests/test_eval_router.py::test_project_roles_cannot_run_all`).

## How to get to it (user POV)

1. Log in. On "Projects", open the project.
2. Click sidebar "Evaluation" (every role sees it). The project Overview's "Evaluation" step ("Configure search, LLM, and evaluate") links here too once data exists.
3. The list heading is "Evaluation sessions". Session cards are the only content; the former "Run a search query" mode is gone.
4. Select "New session". The new page has heading "Untitled session" and badge "Draft".
5. Step 1 "Find the notes worth reading" opens first. Select "Add query" and fill "Query 1". Include/exclude rows are local until saved; saving replaces them with one combined Query 1. "Remove negated matches" is checked by default; uncheck it to keep sentences like "no evidence of" matches (shown struck through in previews).
6. For keyword-only whole-data review, select "Run on all patients" (see `eval-keyword-only-run` in `evaluation-run.md`). No event or model is needed. For the LLM path, select "Continue to event definition": it saves first and opens step 2 "Define the event" even if no sample notes match.
7. Fill "Event name", "What happened to the patient", "Counts as the event" and optionally "Does not count"; select "Save and continue". Return to "Find the notes worth reading" for optional "Suggest from event definition", then "Add all" or "Add". Select "Save and run search" (dirty) or "Run search" (saved) before testing the model.
8. The sample match count and funnel update. "Show matched notes" previews the single saved Query 1; pagination still reports sentence rows as notes.
9. Back on the list, each card has "Clone to new session" (not on discarded cards) and "Discard session" (draft and in-review only).

## Driving it with control-cedars

Current working-tree drives below are **not driven (Docker unavailable)**. Stable IDs containing step1/step2 keep their historical names, not their current step numbers.

- **eval-session-list**, **eval-step-unlock**, **eval-step2-queries**, **eval-step1-event**, **eval-step2-execute**, **eval-step2-match-browser**: fresh baseline project, query first then event, without activating a project query:
  ```bash
  $CC browser run - --as admin --save eval-query-first <<'EOF'
  [{"goto":"/projects/{project}/evaluation"},
   {"click":{"text":"Test an LLM filter first","exact":true}},
   {"click":{"role":"button","name":"New session","exact":true}},
   {"expect":{"role":"button","name":"Define the event"},"state":"disabled"},
   {"click":{"role":"button","name":"Add query","exact":true}},
   {"fill":{"label":"Query 1","exact":true},"value":"DVT OR thromb*"},
   {"click":{"role":"button","name":"Continue to event definition","exact":true}},
   {"fill":{"label":"Event name"},"value":"Deep vein thrombosis"},
   {"fill":{"label":"What happened to the patient"},"value":"Confirmed DVT or thrombosis."},
   {"fill":{"label":"Counts as the event"},"value":"Active diagnosis or positive Doppler."},
   {"click":{"role":"button","name":"Save and continue","exact":true}},
   {"click":{"role":"button","name":"Find the notes worth reading"}},
   {"expect":{"label":"Query 1","exact":true}},
   {"expect_no_text":"Query 2"},
   {"click":{"role":"button","name":"Run search","exact":true}},
   {"expect_text":"Last search matched 4 patients in the sample.","timeout":60},
   {"click":{"role":"button","name":"Show matched notes","nth":0}},
   {"screenshot":"single-query-preview"}]
  EOF
  SID=$($CC db query "select id from evaluation_sessions_v2 where project_id='{project}' order by created_at desc limit 1" --csv 2>/dev/null | tail -1)
  $CC api GET "/projects/{project}/evaluation/sessions/$SID" --field search_queries
  $CC api GET /projects/{project}/nlp/queries --field '[*].id'
  $CC api GET "/projects/{project}/evaluation/sessions/$SID/queries/0/matches" --field query
  ```
  Expected, not observed live: one saved include item `DVT OR thromb*`, zero project SearchQuery records before whole-data action/final commit, and preview index 0. Zero matches must still permit event entry (the second EvaluationSessionPage test); they do not unlock LLM sampling. The old negative preview-index-1 assertion does not describe normalized drafts.

### Historical drives (2026-10-05, cef611321063)

The commands and exit-0 observations below describe the former event-first UI and multi-row saves. They are retained as historical evidence, not current executable verification. Use the current drive above to prepare the retained LLM steps 3-5; old suggest counts and preview index 1 must not be applied to a normalized Query 1.

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

- **Pre-existing mobile sidebar crowds/clips session content.** At 390x844, inspected synthetic-browser screenshots `C:/tmp/cedars-verify/query-first-20261014/evidence/query-first-mobile.png` and `C:/tmp/cedars-verify/query-first-20261014/evidence/query-confirmation-mobile.png` show crowded/clipped session content despite no document overflow. `frontend/src/components/AppLayout.tsx:6` uses an overflow-hidden horizontal flex layout, renders the sidebar at `:13`, and gives the main content the remaining space at `:14`; `frontend/src/components/AppSidebar.tsx:68` retains fixed `w-56` width with no mobile navigation variant. This is not a mobile visual PASS; shared layout/navigation components were not changed.
- **"New session" also matches "Clone to new session".** Role names match as case-insensitive substrings, so once a completed session exists, `{"role":"button","name":"New session"}` finds 2 elements and the click fails in strict mode. The drives above use `"exact":true`. A fresh project hides this because it has no clone icons.
- **Admin session controls render for every role.** "New session" checks only for an active or committed session (`EvaluationListPage.tsx:71-77`). Clone and discard icons, the step 1 query editor and step 2 event form have no role check (`EventDefinitionSection.tsx:43`, `SearchQueriesSection.tsx:63-75`). The API requires admin. The separate reachable `NlpQueriesSection` has its own admin control check (`NlpQueriesSection.tsx:54`). The list page has no error UI for session mutations, so a viewer's click does nothing visible.
- **Locked edits now fail before mutation.** Query saves, event edits, sample search and run-all accept only DRAFT/REVIEWING, and reject an active sample classification with 409 (`service.py:261-278`, `:326`; `tests/test_eval_router.py::test_locked_query_and_prompt_edits_rejected`). This does not fix the separate `run-llm` or judgment status defects in `evaluation-run.md`.
- **`eval-session-clone` has a known security defect.** Details are tracked privately, not in this public repo.
- **Sampling includes soft-deleted patients.** `create_session` selects `Patient.project_id` only (`service.py:115-121`). The full run counts non-deleted patients (`service.py:1159-1240`).
- **Exclusions are sentence-scoped Boolean conditions, not clinical negation.** Saves OR the includes and AND the negated OR of excludes into one expression (`query_expression.py:25-35`). Both sample search and whole-data keyword NLP consume that expression. The session-level "Remove negated matches" checkbox (default on) controls NegEx behavior end to end: unchecked, negated matches are stored with `is_negated=true`, counted in the funnel, sent to the LLM and annotated, and previews strike them through. `!suspected` excludes sentences mentioning that term; it is not a NegEx toggle.
- **Match browser counts.** `total_notes` is the number of matched sentence rows, not notes (`service.py:435-441`). `total_patients` is the distinct patients on the current page (`router.py:262-264`). Rows have no ORDER BY (`service.py:444-452`) and fetch each note one by one (`:459-462`). `note_date` and `note_type` are always null (`router.py:254-255`).
- **Suggestions are untrusted local drafts.** The suggester passes through model types (`query_suggest.py:80-86`), but save validates include/exclude types, syntax and positive includes before persisting (`query_expression.py:6-35`); malformed suggestions must be corrected rather than silently saved.
- **Funnel third stage never fills.** `get_funnel_stats` never returns `llm_positive` or `estimated_cost` (`service.py:405-416`), so the bar always reads "— not classified yet" and the cost line never shows (`FunnelBar.tsx:44-54`). Step 3's "Estimated cost" is always "—" (`SampleRunSection.tsx:77-92`).
- **Explicit continuation pins the next step.** "Continue to event definition" selects step 2; event "Save and continue" selects step 3 (`EvaluationSessionPage.tsx:158`, `:178`). A subsequent sample run may not auto-open review after that explicit selection; drives should select "Check the model against yourself" once classification finishes.
- **Editing queries on a reviewed session relocks steps 3 to 5.** `update_queries` deletes the search matches (`tests/test_eval_service.py::TestUpdateQueries::test_update_queries_clears_matches`). `searched` then becomes false (`EvaluationSessionPage.tsx:91`), while the old patient results stay.
- **Unnamed and title-only controls.** The preview chevron and "Remove query N" are icon buttons named by `title` or `aria-label` (`SearchQueriesSection.tsx:176-204`). The match browser pager buttons have no name (`NotePreviewList.tsx:88-106`); use `{"css":"..."}` or `nth`. List cards are clickable divs, not links (`EvaluationListPage.tsx:98-104`); click the event name with `{"text":"...","nth":0}`.
- **A missing session spins forever.** `/projects/{project}/evaluation/<unknown id>` shows "Loading session…" with a 404 in the background (`EvaluationSessionPage.tsx:82-84`). Driven 2026-10-05 with the zero UUID; the API returns 404 `Session not found`.
- **"Clone it to start again" has no button.** A discarded session's step 5 says so (`EvaluationSessionPage.tsx:290-292`), but the page has no clone control and the list hides it for discarded cards (`EvaluationListPage.tsx:118`).
- **Every commit and re-run creates a new `EventConfig`.** `_get_or_create_event_config_for_session` never reuses one (`service.py:1127-1156`). These configs show up wherever event configs are listed (see `jobs.md`).
- **Keyword NLP is session-only now.** The "Run a search query" mode and `NlpQueriesSection` were removed from the evaluation list. Session "Run on all patients" is the keyword path; the standalone NLP query CRUD remains API-only (see `predictors-nlp.md`).
