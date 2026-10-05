# Patients

Last verified: cef611321063 on 2026-10-05 (source + live read-only)

The Patients area lets a project member browse the patients that ingestion created and read their notes. It also shows the annotation decisions made for each patient. An attending physician uses it for oversight. Every role can read it. The sidebar link "Patients" opens a searchable, filterable table (`/projects/:id/patients`). A row opens the patient detail page (`/projects/:id/patients/:uuid`), which has collapsible notes, the positive annotations under each note, a review-stats line, and a "Re-open for review" button. The button is admin-only in the API but shown to every role.

Overall: beta. Browsing, search, filter and the notes view work live on Postgres. The defects:
- Reopen erases every review decision, although its confirm text says "Existing decisions are preserved".
- Note dates display one day early west of UTC.
- A bad `status` or `limit` returns 500.
- The detail header resolves the patient only if it is among the first 50.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| patients-list | Table with "Patient ID", "Status", "Notes", "Reviewed" (`r/a`) and "Last updated" columns, plus an "N patients" count. Backed by `GET /data/patients` (limit 1..1000, ordered by `updated_at` desc) | beta | UI+API | 3d9432f8 | 2026-10-05 | `connectors/router.py:294-324`, `connectors/service.py:681-755`, `PatientsPage.tsx:81-195`, `tests/test_connectors_api.py::TestPatientSearch::test_patients_response_includes_total` |
| patients-search | "Search by patient ID..." box with a 300 ms debounce. It resets to page 1 and does a case-insensitive substring match on the external ID | beta | UI+API | 90157e29 | 2026-10-05 | `PatientsPage.tsx:73-79`, `:114`, `service.py:692-693`, `TestPatientSearch::test_search_patients_by_ext_id`, `::test_search_patients_case_insensitive` |
| patients-status-filter | Unlabelled select: "All statuses", "New", "NLP processing", "NLP complete", "Reviewing", "Reviewed". Sends `status=<value>` | beta | UI+API | 90157e29 | 2026-10-05 | `PatientsPage.tsx:35-42`, `:120-133`, `service.py:694-695`, `TestPatientSearch::test_filter_patients_by_status` |
| patients-pagination | 20 per page. "Page X of Y", "Previous" and "Next" render only when there are more than 20 patients | beta | UI | 8197dee8 | not driven (the sample has 5 patients) | `PatientsPage.tsx:33`, `:95-96`, `:202-228` |
| patients-row-navigate | Clicking a row opens `/projects/:pid/patients/:uuid`. "Back to patients" returns | beta | UI | 8197dee8 | 2026-10-05 | `PatientsPage.tsx:168-173`, `PatientDetailPage.tsx:198-204`, `App.tsx:122-123` |
| patients-detail-header | h1 shows the external ID with a status badge, "{r} reviewed, {s} skipped, {u} unreviewed of {t} annotations" (only when there are annotations), and "Event: <date>" | beta | UI | cef61132 | 2026-10-05 | `PatientDetailPage.tsx:113-119`, `:205-230` |
| patients-notes-list | "Clinical notes (N)": one collapsible card per note, newest first. The header button reads "<text_id> <date>". Expanding it shows the full text in a `<pre>` | beta | UI | 8197dee8 | 2026-10-05 | `PatientDetailPage.tsx:122-127`, `:244-296`, `service.py:758-777` |
| patients-notes-endpoint | `GET /data/patients/{uuid}/notes?limit=100&offset=0` returns `id, patient_id, text_id, note_date, text, source_ref, created_at` | beta | UI+API | 3d9432f8 | 2026-10-05 | `router.py:327-348`, `TestIngestion::test_ingest_csv_data` (asserts notes at `test_connectors_api.py:171-176`) |
| patients-annotation-cards | Under each note, an "Annotations" block for `predicted_label == 1` rows. It shows the sentence, a review badge, "Prediction: Positive (N% likely)", "Negated", "Event:" and the reasoning | beta | UI+API | cef61132 | not driven (needs a full pipeline run) | `PatientDetailPage.tsx:298-347`, `annotations/router.py:217-228`, `review_service.py:300-312`, `tests/test_annotations_api.py::test_patient_annotations_sorted` |
| patients-review-stats | `GET /annotations/patient/{uuid}/stats` returns `total, unreviewed, reviewed, skipped, current_event_date` | beta | UI+API | 4e484c93 | 2026-10-05 (all zeros) | `annotations/router.py:231-239`, `review_service.py:440-489`, `test_annotations_api.py::test_patient_stats` |
| patients-reopen | "Re-open for review", then `window.confirm`, then `POST /annotations/patient/{uuid}/reopen`. It works only for a REVIEWED patient, sets the patient to REVIEWING, and resets every annotation to unreviewed | beta | UI+API | 4e484c93 | not driven | `PatientDetailPage.tsx:150-165`, `:183-241`, `annotations/router.py:254-265`, `review_service.py:492-531`, `test_annotations_api.py::TestReopenPatient::test_reopen_nonexistent_patient` (404 path only) |
| patients-reopen-role-gating | The API allows admins only (403 for others). The UI shows the button to every role | beta | UI+API | 8197dee8 | 2026-10-05 (viewer sees the button) | `annotations/router.py:259`, `PatientDetailPage.tsx:232` ("admin only (backend enforces, UI always shows for now)") |
| patients-activity | `GET /patients/{uuid}/activity` returns the audit timeline for one patient. Admins and annotators only. No page calls it | api-only | API | 511ec88e | 2026-10-05 | `audit/router.py:46-55`. Covered in `admin-audit.md` |

Why the grades:
- **No row is `stable`.** Each row has an open defect (see Gotchas) or was not driven live.
- **Closest to stable.** patients-search and patients-list are tested and live. Search is held back by unescaped wildcards. The list is held back by the 500 on a bad status.
- **Reopen has almost no tests.** No test drives a successful reopen: `test_full_patient_review_flow` (`test_annotations_api.py:474`) never calls it.
- **Test runs.** The suites pass locally on SQLite and Postgres at cef611321063 (382/382 on each). CI has never run them green (see README "Test evidence").
- **No frontend tests** exist for either page.

## How to get to it (user POV)

1. Log in. On "Projects", open a project.
2. Click "Patients" in the sidebar. The page shows heading "Patients", the subtitle "Search and browse patients. View notes and annotation decisions.", a "Search by patient ID..." box, a status select and "N patients".
3. Type part of an ID to filter, or pick a status. With no matches, the table says "No patients match your filters.". An empty project says "No patients yet.".
4. Click a row. The detail page shows "Back to patients", the external ID as the heading, and a status badge such as "New". When the patient has annotations, the review-stats line appears. The "Re-open for review" button is on the right.
5. Under "Clinical notes (N)", click a note's header ("<text_id> <date>") to expand its text. Positive annotations for that note appear below it under "Annotations".
6. Admins only: on a patient whose status is "Reviewed", click "Re-open for review" and accept the confirm dialog. The patient goes back to "Reviewing" and re-enters the Annotations queue.

## Driving it with control-cedars

Preconditions: the baseline (5 patients `1111111111` to `5555555555`, with 12, 15, 31, 29 and 16 notes respectively, all "New"). There is no `{patient}` expansion. In the UI, click the row by its text. In `api`, get the UUID with `$CC api GET '/projects/{project}/data/patients?search=1111111111' --as viewer` → `items[0].id`. Reopen also needs a REVIEWED patient: commit an evaluation session and run its full pipeline (`evaluation-run.md`), then review every positive annotation for one patient in the Annotations queue (`annotations.md`).

- **patients-list**: → `$CC api GET '/projects/{project}/data/patients' --as viewer --save patients-list-viewer` → 200 `total: 5`, all `status: new`. `note_count` is 16, 29, 31, 15 and 12 for 5555555555, 4444444444, 3333333333, 2222222222 and 1111111111 (that is the `updated_at desc` order today). → `$CC api GET '/projects/{project}/data/patients?limit=0' --as viewer --expect 422` → 422. → `$CC api GET '/projects/{project}/data/patients' --as anon --expect 401` → 401.
- **patients-search**, **patients-status-filter**, **patients-row-navigate**, **patients-notes-list** (all read-only): browse as viewer →
  ```
  $CC browser run - --as viewer --save patients-browse <<'EOF'
  [{"goto":"/projects/{project}/patients"},
   {"expect_text":"5 patients"},
   {"fill":{"placeholder":"Search by patient ID..."},"value":"333"},
   {"expect_text":"1 patient","exact":true},
   {"expect":{"role":"row","name":"3333333333"}},
   {"fill":{"placeholder":"Search by patient ID..."},"value":""},
   {"expect_text":"5 patients"},
   {"select":{"role":"combobox"},"value":"Reviewed"},
   {"expect_text":"No patients match your filters."},
   {"select":{"role":"combobox"},"value":"All statuses"},
   {"click":{"role":"row","name":"1111111111"}},
   {"expect_url":"/patients/[0-9a-f-]{36}$"},
   {"expect":{"role":"heading","name":"1111111111"}},
   {"expect_text":"Clinical notes (12)"},
   {"click":{"role":"button","name":"UNIQUE0000000012"}},
   {"snapshot":"detail"},
   {"screenshot":"detail"},
   {"click":{"role":"link","name":"Back to patients"}},
   {"expect":{"role":"heading","name":"Patients"}}]
  EOF
  ```
  → 19/19 PASS, no API errors (2026-10-05). The expanded note mentions "pulmonary emboli". The API equivalents are `?search=333` → `total: 1`, `?status=new` → 5 and `?status=reviewed` → 0.
- **patients-status-filter** (defect): → `$CC api GET '/projects/{project}/data/patients?status=bogus' --as viewer` → 500 Internal Server Error. It should be 422. FAIL.
- **patients-search** (defect): → `$CC api GET '/projects/{project}/data/patients?search=%25' --as viewer` → `total: 5`, because `%` is passed through as a wildcard.
- **patients-detail-header**: → `$CC browser snapshot '/projects/{project}/patients/<uuid>' --as viewer --wait-text 'Clinical notes'` → heading "1111111111", badge "New", no stats line (0 annotations). With an unknown UUID (`00000000-0000-0000-0000-000000000000`), the page shows the UUID as the heading, "Clinical notes (0)", "No notes found for this patient." and the reopen button. There is no 404 state.
- **patients-notes-endpoint**: → `$CC api GET '/projects/{project}/data/patients/<uuid>/notes' --as viewer --save patient-notes-viewer` → 200 with 12 notes. The first is `UNIQUE0000000012` (`note_date` `2010-01-15T00:00:00Z`) and the last is `UNIQUE0000000011`. An unknown UUID gives 200 `[]`. `?limit=-1` gives 500 (FAIL). `?limit=100000` gives 200.
- **patients-notes-list** (date defect): the snapshot from the run above shows note buttons such as "UNIQUE0000000012 1/14/2010" for the stored `2010-01-15T00:00:00Z`. FAIL, one day early.
- **patients-review-stats**: → `$CC api GET '/projects/{project}/annotations/patient/<uuid>/stats' --as viewer` → 200 with every count 0 on the seeded project.
- **patients-annotation-cards**: after a full pipeline run → `$CC api GET '/projects/{project}/annotations/patient/<uuid>/annotations' --as viewer` → only `predicted_label: 1` rows (`[]` on the seeded project). In the UI, expand the note named by `note_id` and `expect_text` "Prediction: Positive".
- **patients-reopen-role-gating**: → `$CC browser snapshot '/projects/{project}/patients/<uuid>' --as viewer` → `button "Re-open for review"` is present (defect). In the mutation pass, run `$CC api POST '/projects/{project}/annotations/patient/<uuid>/reopen' --as viewer --expect 403` → "Insufficient permissions". Use the same call `--as annotator --expect 403`.
- **patients-reopen** (mutating): → `$CC api POST '/projects/{project}/annotations/patient/<uuid>/reopen' --as admin --expect 404` on a "New" patient → "Patient not found or not in reviewed state". On a REVIEWED patient, the same call without `--expect` returns `{"ok": true}`. Then run `$CC api GET '/projects/{project}/annotations/patient/<uuid>/stats' --as viewer` → `reviewed: 0` and `unreviewed` equal to `total`, which shows the decisions were wiped. Then run `$CC db query "select status, locked_by from patients where id = '<uuid>'"` → `REVIEWING`, with `locked_by` unchanged. Do not drive this through `browser run`. It has no dialog handler, so Playwright dismisses the `window.confirm` and the click does nothing.
- **patients-pagination**: SKIP on the seeded project (5 patients, so no pager). It needs more than 20 patients, for example a CSV with 21 distinct `patient_id` values uploaded through `data.md`'s upload flow. After that, `{"expect_text":"Page 1 of 2"}`, then `{"click":{"role":"button","name":"Next"}}` and `{"expect_text":"Page 2 of 2"}`.
- **patients-activity**: → `$CC api GET '/projects/{project}/patients/<uuid>/activity' --as annotator` → 200 `entries: []`. The same call `--as viewer --expect 403` → 403 (both 2026-10-05).

## Gotchas

**Reopen**
- **Reopen erases decisions.** The confirm text says "Existing decisions are preserved" (`PatientDetailPage.tsx:186`), and the route docstring says "Preserves annotation decisions" (`annotations/router.py:261`). The service sets every annotation of the patient back to unreviewed and clears `reviewed_by`, `reviewed_at` and `event_date` (`review_service.py:514-522`). After reopen, the page does not refetch `patient-annotations` (`PatientDetailPage.tsx:156-163`), so the old "Reviewed" badges stay on screen until reload. There is no `onError`, so a 403 or 404 is silent. Only the audit log keeps the old decisions (`annotation_reviewed`, `event_date_set` with the date). The page does not show it, but `GET /projects/{project}/patients/<uuid>/activity` returns it to admins and annotators (`admin-audit.md`).
- **Reopen keeps the old lock.** It does not clear `locked_by` or `locked_at` (`review_service.py:511-524`). The queue then skips a patient that someone else has locked (`:220`). Only the locking user can unlock (`:364-380`). The Annotations page unlocks with a best-effort `sendBeacon` on unmount (`AnnotationsPage.tsx:834-845`).
- **REVIEWED is hard to reach.** It requires zero unreviewed annotations of any label (`review_service.py:27-48`). The queue and the detail cards show only `predicted_label == 1` (`:209`, `:309`). A patient with a leftover label-0 annotation (for example from a second pipeline run) never becomes REVIEWED, so it can never be reopened.

**Detail page**
- **The header resolves only the first 50 patients.** It fetches `/data/patients?limit=50&offset=0` and searches it on the client (`PatientDetailPage.tsx:113-119`). Patients past the first 50 by `updated_at` show their UUID as the heading and no status badge. An unknown UUID renders a normal page instead of a 404.
- **Notes stop at 100.** The notes query uses the default `limit=100` with no paging (`:122-127`, `router.py:331-332`), and the heading counts what was returned. A patient with 101 notes shows "Clinical notes (100)".
- **Dates display one day early west of UTC.** `note_date` is timestamptz at UTC midnight (`connectors/models.py:122-124`), and the page renders it with `toLocaleDateString()` in the browser's zone (`PatientDetailPage.tsx:280`). The same pattern appears for event dates (`:226`, `:336-337`): a stored `2018-08-06` shows as Aug 5, seen live 2026-10-05 in the evaluation review card, which uses the same code (`evaluation-run.md` Gotchas).
- **The stats line and the cards count different things.** The stats line counts annotations of every label (`review_service.py:446-489`). The cards show only label 1. The list's "Reviewed" column counts `reviewed`, `confirmed`, `rejected` and `skipped` (`service.py:719`), while the detail line counts `reviewed` alone.

**API input handling**
- **A bad `status` returns 500.** `status` is compared with the enum unvalidated (`service.py:694-695`). An unknown value raises during bind and returns 500. Live on Postgres: `?status=bogus` → 500.
- **Search wildcards are not escaped.** Search interpolates the raw term into `ilike` (`service.py:692-693`), so `%` and `_` act as wildcards.
- **Notes paging is unbounded.** The notes `limit` and `offset` have no bounds (`router.py:331-332`): `limit=-1` → 500. The endpoint also does not check that the patient exists (`service.py:758-777`). The response omits note metadata (`schemas.py:62-69`).

**List page**
- **Paging can shuffle rows.** The list orders by `updated_at desc` with no tiebreaker (`service.py:740`), so rows with equal timestamps can move between pages. Locking a patient bumps it to the top.
- **There is no error state.** A failed list query (for example a 403 for a non-member) shows "No patients yet." or "No patients match your filters.", with no count (`PatientsPage.tsx:134-163`).

**Locators for driving**
- **Rows are not links.** They are `<tr onClick>` (`PatientsPage.tsx:168-173`), so a keyboard cannot reach them. Click by `{"role":"row","name":"<ext id>"}`. The row's accessible name is "<ext id> <Status> <notes> <reviewed> <date>", so the name match is a substring match.
- **The status select is unlabelled.** It has no accessible name (`PatientsPage.tsx:120-133`). Use `{"role":"combobox"}`. It is the only combobox on the page.
- **Note headers are buttons** named "<text_id> <M/D/YYYY>" in the browser's zone. Match them by `text_id` alone.
