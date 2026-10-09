# Projects

Last verified: cef611321063 on 2026-10-05 (source + live read-only)

A project is the tenant boundary. Patients, notes, sessions, annotations and audit entries all belong to one project, and every project route checks the caller's per-project role (admin, annotator or viewer). Every user sees the "Projects" list and the project Overview. Admins also create projects and change the per-project LLM settings under "Project settings". Membership and delete exist only in the API. Overall: **beta**. Listing, creating and settings work, and the stored API key is never returned by the project API. But it has a known security defect, tracked privately (not in this public repo). The settings panel shows "Save" to viewers and annotators, and the API then rejects it. The overview progress bar multiplies an already-0-100 value by 100.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| projects-list | `GET /projects`: non-deleted projects the caller is a member of, each with the caller's `role`. Cards show name, role badge, "Created <date>" | stable | UI+API | d8a885d5 | 2026-10-05 | `backend/app/projects/router.py:71-78`, `projects/service.py:47-59`, `frontend/src/projects/ProjectListPage.tsx:69-135`, `tests/test_projects_api.py::test_list_projects_returns_only_user_projects`. Live: each seeded role sees 1 project with its own role |
| projects-create | `POST /projects` (201). The creator becomes the project admin. "New project" opens the form; "Create project" returns to the list | beta (stable pending live) | UI+API | c7cf4c74 | not driven (form only) | `router.py:54-68`, `service.py:13-44`, `frontend/src/projects/CreateProjectPage.tsx:70-80`, `test_projects_api.py::test_create_project`, `::test_create_project_user_is_admin_member`, `::test_create_project_requires_auth` |
| projects-llm-presets | Provider list (OpenAI, Anthropic, vLLM, Ollama (local), AWS Bedrock) with known-good model presets plus "Custom model ID…". Bedrock disables API base and key and warns on unprefixed model IDs | beta | UI | c7cf4c74 | 2026-10-05 | `frontend/src/lib/llmModels.ts:23-29`, `:45-89`, `:123-131`, `CreateProjectPage.tsx:209-214`, `ProjectOverview.tsx:174-189`. No frontend tests |
| projects-settings-view | "Project settings" on Overview expands "LLM configuration" and "Annotation behavior". The "LLM not configured" badge shows when provider or model is empty | beta | UI+API | c7cf4c74 | 2026-10-05 | `ProjectOverview.tsx:238-413`, `router.py:81-92`, `test_projects_api.py::test_get_project_as_member`. Unlabelled controls and a render-loop risk (Gotchas) |
| projects-settings-save | `PUT /projects/{id}` (admin only): name, description, settings, provider, model, api_base, api_key. "Save" and "Cancel" appear once the form is dirty | beta | UI+API | c7cf4c74 | 2026-10-05 (viewer sees Save; Save not clicked) | `router.py:105-118`, `service.py:75-106`, `ProjectOverview.tsx:207-231`, `:390-413`, `test_projects_api.py::test_update_project_as_admin`, `::test_update_project_as_annotator_returns_403`. Role-gating defect |
| projects-api-key | Key is write-only in the project API: responses carry `llm_api_key_set` only. Typing a key sets it, "Clear the stored key" sends `""`, omitting it keeps it | beta | UI+API | cf50d0da | 2026-10-05 (`llm_api_key_set` only) | `router.py:45`, `schemas.py:36-37`, `service.py:80`, `:98-99`, `ProjectOverview.tsx:218-224`, `:340-363`, `test_projects_api.py::test_llm_api_key_stored_but_never_echoed`, `::test_llm_api_key_preserved_when_update_omits_it`. Known security defect (tracked privately) |
| projects-overview-stats | `GET /projects/{id}/stats` feeds the cards "Patients", "Notes", "Target sentences", "Annotations", "Latest job" and "Annotator activity", polled every 10 s | beta | UI+API | b9504201 | 2026-10-05 | `router.py:95-102`, `projects/stats.py:13-154`, `ProjectOverview.tsx:424-428`, `:512-620`, `tests/test_project_stats_api.py::test_project_stats_empty`, `::test_project_stats_with_data`. Progress bug |
| projects-workflow-stepper | Overview "Workflow" list: Data, Evaluation, Annotations, Export, each with "View" (done) or "Get started" | beta | UI | b9504201 | 2026-10-05 | `ProjectOverview.tsx:52-80`, `:465-490`, `:622-683`. No tests |
| projects-nonmember-access | A user with no membership gets 403 "Insufficient permissions" on every project route. The UI shows "Failed to load project: Insufficient permissions" and "Back to projects" | beta | UI+API | b4a5e529 | 2026-10-05 | `backend/app/dependencies.py:50-55`, `frontend/src/projects/ProjectLayout.tsx:30-39`, `test_projects_api.py::test_get_project_as_non_member_returns_403`, `::test_non_member_cannot_access_project`. The message takes about 7 s to appear |
| projects-nav | Project sidebar: "All projects", "Overview", "Data", "Patients", "Evaluation", "Jobs", "Annotations", "Export". The same links for every role | beta | UI | 8197dee8 | 2026-10-05 | `frontend/src/components/AppSidebar.tsx:18-26`, `:85-91`. Role-blind |
| projects-workflow-breadcrumb | "Step N of 4" bar with previous and next links (nav "Workflow steps") on Data, Patients, Annotations and Export | beta | UI | a5b72355 | 2026-10-05 | `frontend/src/components/WorkflowBreadcrumb.tsx:4-9`, `:29-51`, used at `DataPage.tsx:410`, `PatientsPage.tsx:100`, `PatientDetailPage.tsx:195`, `AnnotationsPage.tsx:1493`, `ExportPage.tsx:91`. No tests |
| projects-members-list | `GET /projects/{id}/members`: user_id, email, name, role. Any member may call it | api-only | API | b4a5e529 | 2026-10-05 | `router.py:168-184`, `service.py:184-195`, `test_projects_api.py::test_list_members`. Live: viewer sees 3 members. No page calls it |
| projects-members-add | `POST /projects/{id}/members` `{email, role}` (admin, 201). Unknown email returns 404 "User not found" | api-only | API | b4a5e529 | not driven | `router.py:137-165`, `service.py:154-181`, `schemas.py:49-51`, `test_projects_api.py::test_add_member`, `::test_add_member_nonexistent_email_returns_404`. 500 on a bad role |
| projects-members-remove | `DELETE /projects/{id}/members/{user_id}` (admin, 204) | api-only | API | b4a5e529 | not driven | `router.py:187-201`, `service.py:198-210`, `test_projects_api.py::test_remove_member`. No last-admin guard |
| projects-delete | `DELETE /projects/{id}` (admin, 204): soft delete. The project leaves every list and `GET` returns 404 | api-only | API | b4a5e529 | not driven | `router.py:121-131`, `service.py:109-119`, `test_projects_api.py::test_delete_project_soft_deletes`. No UI. Child routes still answer (Gotchas) |

Why the grades:
- **projects-list is `stable`.** It is tested, driven live for all three roles and has no known defect.
- **projects-create** would qualify for `stable`, but the create form was not submitted in this read-only pass.
- **The settings rows are capped at `beta`.** The role-gating defect, a security defect tracked privately and the missing frontend tests keep them there.
- **Membership and delete are `api-only`.** Nothing in `frontend/src` calls `/members` or `DELETE /projects`. Adding a teammate needs an API call.

## How to get to it (user POV)

1. Sign in. The app opens "Projects".
2. Each card shows the project name, your role badge and "Created <date>". With no projects you see "No projects yet" and "Create your first project to get started."
3. To create one, click "New project" and fill in "Project name" and "Description". Pick "Provider" and "Model" (or "Custom model ID…"), then "API base URL (optional)" and "API key (optional)". Click "Create project". You return to "Projects".
4. Click a project card. The Overview opens with "Project settings", the stat cards, "Latest job" and "Workflow".
5. Click "Project settings" to see "LLM configuration" (Provider, Model, API base, API key) and "Annotation behavior" ("Skip annotations after event date"). Change anything and "Save" and "Cancel" appear.
6. The sidebar moves between pages. "All projects" goes back to the list. Data, Patients, Annotations and Export also show the "Step N of 4" bar at the top.
7. Adding members and deleting a project have no UI. A project admin uses the API (see below).

## Driving it with control-cedars

Preconditions: the baseline. Bullets marked *mutation pass* change data. List them, but run them only in the mutation pass.

- **projects-list**: each role lists its projects → `$CC api GET /projects --as viewer` → 200, 1 item, `"role": "viewer"`, `"llm_api_key_set": false`, no `llm_api_key` field. Repeat `--as admin` and `--as annotator`. UI: `$CC browser snapshot /projects --as viewer --save projects-list-viewer --wait-text "Created"` → link "New project", the project card, text "viewer".
- **projects-create** (form, no submit): presets and the Bedrock rules →
  ```
  $CC browser run - --as admin --save projects-create-presets <<'EOF'
  [{"goto":"/projects/new"},
   {"expect_text":"gpt-4o-mini — Fast and inexpensive"},
   {"select":{"label":"Provider"},"value":"AWS Bedrock"},
   {"expect_text":"Bedrock needs no endpoint or API key"},
   {"expect":{"label":"API base URL (optional)"},"state":"disabled"},
   {"expect":{"label":"API key (optional)"},"state":"disabled"},
   {"expect_text":"Fastest and cheapest — good default"},
   {"select":{"label":"Model"},"value":"Custom model ID…"},
   {"fill":{"placeholder":"us.anthropic.claude-haiku-4-5-20251001-v1:0"},"value":"anthropic.claude-sonnet-5"},
   {"expect_text":"This ID will likely fail unless it is prefixed with a region"},
   {"screenshot":"bedrock-warning"},
   {"select":{"label":"Provider"},"value":"vLLM"},
   {"expect":{"label":"Model"},"state":"visible"},
   {"expect":{"label":"API base URL (optional)"},"state":"enabled"},
   {"expect_no_text":"Bedrock needs no endpoint"},
   {"screenshot":"vllm-free-text"}]
  EOF
  ```
  → PASS, 16 steps (2026-10-05). This also drives **projects-llm-presets**. The custom model input has no label, so it is found by placeholder.
- **projects-create** (*mutation pass*): add `{"fill":{"label":"Project name"},"value":"verify-create"}` and `{"click":{"role":"button","name":"Create project"}}` → `expect_url "/projects$"`, `expect_text "verify-create"`. Also run `$CC api POST /projects --as viewer --body '{"name":"verify-no-llm"}' --save projects-create-no-llm` (any signed-in user may create a project). Then `$CC browser snapshot /projects/<new id> --as viewer` checks the render-loop risk (Gotchas).
- **projects-settings-view**: viewer opens the panel →
  ```
  $CC browser run - --as viewer --save projects-settings-open-viewer <<'EOF'
  [{"goto":"/projects/{project}"},
   {"click":{"role":"button","name":"Project settings"}},
   {"expect_text":"LLM configuration"},
   {"expect_text":"Annotation behavior"},
   {"expect_no_text":"Save"},
   {"snapshot":"settings-open"},
   {"screenshot":"settings-open"}]
  EOF
  ```
  → PASS. The snapshot shows an unnamed Provider combobox ("vLLM"), and textboxes named only by placeholder: "llama3" (model, value `fake-clinical`), "http://localhost:11434" (API base) and "sk-…" (key).
- **projects-settings-save** (role gating, UI): viewer makes the form dirty →
  ```
  $CC browser run - --as viewer --save projects-settings-viewer-dirty <<'EOF'
  [{"goto":"/projects/{project}"},
   {"click":{"role":"button","name":"Project settings"}},
   {"expect_text":"LLM configuration"},
   {"check":{"role":"checkbox","name":"Skip annotations after event date"}},
   {"expect":{"role":"button","name":"Save","exact":true}},
   {"expect":{"role":"button","name":"Cancel"}},
   {"screenshot":"save-shown"},
   {"click":{"role":"button","name":"Cancel"}},
   {"expect":{"role":"button","name":"Save","exact":true},"state":"hidden"}]
  EOF
  ```
  → PASS, which confirms the defect: "Save" is offered to a viewer. Save was not clicked.
- **projects-settings-save** (role gating, API, *mutation pass*): → `$CC api PUT /projects/{project} --as viewer --body '{"description":"x"}' --expect 403` → "Insufficient permissions". Same `--as annotator`. Then `--as admin --body '{"settings":{"skip_after_event_date":false}}'` → 200.
- **projects-api-key**: → `$CC api GET /projects/{project} --as viewer --save projects-get-viewer` → `"llm_api_key_set": false`, no `llm_api_key` key.
- **projects-overview-stats**: → `$CC api GET /projects/{project}/stats --as viewer` → `patients.total 5`, `notes.total 103`, `jobs.latest.job_type "ingestion"`, `status "completed"`, `progress 100`. UI: `$CC browser snapshot /projects/{project} --as viewer --save projects-overview-viewer --wait-text "Workflow" --full-page` → "Latest job" reads "ingestion completed". The progress bug needs a running job, so it is SKIP until the mutation pass. Start an ingestion and watch for "10000% complete".
- **projects-workflow-stepper**: in the same overview snapshot → list "Workflow" with links "View" (Data, done) and "Get started".
- **projects-nonmember-access** and unknown routes →
  ```
  $CC browser run - --as viewer --save projects-nonmember <<'EOF'
  [{"goto":"/projects/00000000-0000-0000-0000-000000000000"},
   {"expect_text":"Failed to load project: Insufficient permissions","timeout":30},
   {"expect":{"role":"link","name":"Back to projects"}},
   {"goto":"/admin"},
   {"wait":2},
   {"snapshot":"unknown-route"},
   {"screenshot":"unknown-route"}]
  EOF
  ```
  → PASS. `api_errors` lists 4 × 403 (react-query retries). The `/admin` snapshot is empty because there is no catch-all route. API: `$CC api GET /projects/00000000-0000-0000-0000-000000000000 --as viewer --expect 403` → "Insufficient permissions".
- **projects-nav**: in the overview snapshot → sidebar links "All projects", "Overview", "Data", "Patients", "Evaluation", "Jobs", "Annotations", "Export" for the viewer. Annotator and admin see the same links.
- **projects-workflow-breadcrumb** →
  ```
  $CC browser run - --as viewer --save projects-breadcrumb <<'EOF'
  [{"goto":"/projects/{project}/data"},
   {"expect":{"role":"navigation","name":"Workflow steps"}},
   {"expect_text":"Step 1 of 4"},
   {"click":{"role":"link","name":"Evaluation","within":{"role":"navigation","name":"Workflow steps"}}},
   {"expect_url":"/evaluation$"},
   {"wait":1},
   {"expect":{"role":"navigation","name":"Workflow steps"},"state":"hidden"},
   {"goto":"/projects/{project}/patients"},
   {"expect_text":"Step 1 of 4"},
   {"goto":"/projects/{project}/export"},
   {"expect_text":"Step 4 of 4"},
   {"click":{"role":"link","name":"Annotations","within":{"role":"navigation","name":"Workflow steps"}}},
   {"expect_url":"/annotations$"},
   {"expect_text":"Step 3 of 4"}]
  EOF
  ```
  → PASS, 14 steps. Evaluation, the step-2 page, has no breadcrumb.
- **projects-members-list**: → `$CC api GET /projects/{project}/members --as viewer` → 3 items with roles admin, annotator, viewer.
- **projects-members-add** (*mutation pass*): → `$CC api POST /projects/{project}/members --as viewer --body '{"email":"verify-annotator@example.com","role":"viewer"}' --expect 403`. Then as admin with `"role":"owner"` → today a 500, which is the defect. As admin with an existing member and a new role → 201, but the old role is kept.
- **projects-members-remove** (*mutation pass*): → `$CC api DELETE /projects/{project}/members/<user_id> --as annotator --expect 403`. Get `<user_id>` from `GET /members`.
- **projects-delete** (role gating, listed only, do not run outside the mutation pass): → `$CC api DELETE /projects/{project} --as viewer --expect 403` → "Insufficient permissions". `--as annotator --expect 403` likewise. An admin DELETE returns 204 and destroys the seeded project for everyone, so only run it on a throwaway project.

## Gotchas

- **Known security defects** affect `projects-api-key` and `projects-settings-save`. Details are tracked privately, not in this public repo.
- **"Save" is shown to viewers and annotators.** The panel has no role check (`ProjectOverview.tsx:390-413`), but `PUT` needs admin (`router.py:109`). A viewer who saves sees "Insufficient permissions" under the form. Nothing in the frontend reads `project.role` except the list badge, so every admin-only control is shown to every role.
- **Running jobs show up to 10000%.** `progress` is already 0-100 (`backend/app/jobs/ingestion.py:118-122`, `jobs/nlp.py:56`, `jobs/prediction.py:152`). The Overview multiplies it by 100 (`ProjectOverview.tsx:573`, `:575`). It only shows while `status == "running"`, so a completed job looks fine.
- **Likely render loop on a project with no provider and no model.** `ProjectOverview.tsx:203-205` calls `syncFromProject` (several `setState` calls) during render whenever provider and model are both `""`. A project with both fields null keeps them `""`, so React should throw "Too many re-renders" and blank the Overview. The UI create form always sends a provider and model, but `POST /projects` with just a name does not. This is source-only. Check it in the mutation pass.
- **Settings controls have no accessible names.** The Provider, Model, API base and API key `<Label>`s have no `htmlFor` (`ProjectOverview.tsx:268`, `:281`, `:319`, `:334`). Snapshots show an unnamed combobox and textboxes named by placeholder. Use `{"role":"combobox"}` with `nth`, or the placeholders. The create form's labels do work. Only its "Custom model ID…" input has no label (`CreateProjectPage.tsx:161-176`).
- **Changing provider resets the model and can clear the key.** `onProviderChange` picks the new provider's default model. For Bedrock or Ollama it also sets "clear key" (`ProjectOverview.tsx:174-189`). Saving after an accidental provider switch deletes the stored key.
- **The typed key stays in the form after saving.** `onSuccess` only invalidates the query and clears `dirty` (`ProjectOverview.tsx:227-230`). `apiKey` and `clearApiKey` keep their values, so the next save re-sends them.
- **`settings` is replaced, not merged.** `update_project` assigns the whole dict (`service.py:101`). The UI spreads the existing settings first (`ProjectOverview.tsx:216`), but an API caller sending `{"settings":{"x":1}}` wipes every other setting.
- **Members API traps.** An invalid role makes `ProjectRole(role)` raise, which is a 500 (`service.py:176`, `schemas.py:51` is a plain `str`). Re-adding an existing member returns 201 with the old role unchanged (`service.py:169-171`). There is no "change role" endpoint, so a role change means remove and re-add. `remove_member` has no last-admin guard, so an admin can remove themselves and orphan the project (`service.py:198-210`).
- **Soft delete is incomplete.** `get_project` filters `deleted_at` (`service.py:62-72`), but `require_project_role` only checks membership (`dependencies.py:50`). `list_members` (`service.py:184-195`) and `get_project_stats` (`projects/stats.py:13-154`) never check the project, so `/members` and `/stats` still answer 200 for a deleted project. The same is likely true for other child routes.
- **`/stats` for a project id that does not exist** returns zeros to a platform admin, not 404 (`stats.py:13-154`).
- **"Latest job" covers BackgroundJob only** (ingestion, NLP, prediction). Pipeline runs and evaluation sessions never appear there (`stats.py:97-118`, `:140-153`).
- **Platform admins are second-class in the list.** `GET /projects` joins on membership (`service.py:52-57`), so a platform admin sees only projects they belong to, though they can open any project by URL. For a non-member admin, `role` is null (`router.py:91-92`).
- **Create returns to the list, not the new project** (`CreateProjectPage.tsx:73-76`). `CreateProjectRequest.name` has no minimum length (`schemas.py:7`), so the API accepts `""`. The form marks the field required.
- **Errors take about 7 seconds.** The default react-query retries mean "Failed to load project" appears only after 4 requests (`frontend/src/App.tsx:23`).
- **Breadcrumb gaps.** There are only 4 steps (`WorkflowBreadcrumb.tsx:4-9`). Patients and patient detail pass `currentStep="data"`, so they read "Step 1 of 4: Data". The Evaluation (step 2), Jobs and Overview pages render no breadcrumb.
- **The `"owner"` badge case is dead code** (`ProjectListPage.tsx:25`). `ProjectRole` has only admin, annotator and viewer (`projects/models.py:13-18`).
