# CEDARS v2 feature map

One file per product area. Each file says what exists, how mature it is, how a user reaches it, and how to drive it through `control-cedars` (the verify-cedars CLI, at `.claude/skills/verify-cedars/control-cedars`). Use the map to answer questions without re-reading the whole codebase. Use the source to settle anything the map does not cover or that may have changed.

Scope: the v2 platform only (`backend/`, `frontend/`, `infra/cedars-v2/`). The v1 Flask app (`cedars/`) was removed; the PINES service (`PINES/`) appears only where v2 still calls it.

## Maturity rubric

Grade each sub-feature against the highest rung it fully meets. Every grade needs evidence (a file:line, a test name, or a `control-cedars` result).

| Grade | Meaning | Must be true |
|---|---|---|
| `deferred` | Out of scope by decision | Listed under "v2 Deferred Features" in CLAUDE.md, or no code and a doc says later |
| `stub` | Code exists but does not do the job | Endpoint crashes, a UI branch can never render, a field is never populated, or the only caller is dead code |
| `api-only` | Works, but no UI reaches it | Route works when called. Nothing in `frontend/src` calls it from a reachable page |
| `beta` | A user can reach it and the happy path works | Reachable from the UI. A known defect, an untested path, or no Postgres coverage keeps it from `stable` |
| `stable` | Safe to rely on | Reachable from the UI, covered by tests that pass on SQLite **and** Postgres, no open known defect, and driven live in the parity stack (`Live` column has a date) |

Rules:
- Grade what the code does, not what docs or commit messages claim.
- A known defect caps the grade at `beta`, however polished the rest is. Put the defect under Gotchas.
- Source-only review can propose `stable`, but only a live drive confirms it. Until then, write `beta (stable pending live)`.
- Role gating is part of the feature. If the UI shows a control that the API rejects for that role, it is a defect.

## Deployed or not

Maturity describes the code at the commit in each file's `Last verified` line. Whether DEV runs that code is a separate question. Each sub-feature row has an `Since` column (the commit that introduced or last materially changed it). To answer "is this live on DEV?":

1. Run `control-cedars aws status` (read-only). It prints the image SHA each ECS service runs and the commits on HEAD that DEV does not have.
2. If the row's `Since` commit is in that undeployed list, DEV runs the older behaviour.
3. If AWS credentials are expired, say so and fall back to the snapshot below, with its date.

Snapshot (`aws status`, 2026-10-05):
- DEV runs `cef61132` on backend, worker and frontend. Tasks started 2026-09-23, task definition revision 1, all targets healthy.
- Nothing on HEAD is undeployed, so every row graded at `cef611321063` describes what DEV runs.
- Each task also carries an AWS-injected `aws-guardduty-agent-*` sidecar (GuardDuty runtime monitoring). The parity stack has no equivalent.

## Test evidence

"Tests pass" in this map means a local `control-cedars test all` (backend SQLite and Postgres, frontend) run at the file's `Last verified` commit. It does not mean GitHub CI is green: the new `ci.yml` has not run on GitHub yet (branch `chore/watertight-ci`, unpushed). It runs on every PR behind one required-style `CI gate` job. Existing debt is held by ratchets that may only shrink: mypy errors (`backend/.mypy-baseline`), eslint warnings, model/migration drift (`backend/.alembic-drift-baseline`), known vulnerabilities (`scripts/audit-baseline.json`) and the coverage floor. `control-cedars ci status` shows the real GitHub picture; `scripts/check` runs the static lane locally.

### October 13 query-first evidence and limits

The affected setup/run/NLP/annotation/journey rows are implemented-source beta, not plans or stable grades. This update uses the dirty working tree on HEAD `db8175b73584`, not a committed/deployed SHA. Source anchors: `backend/app/evaluation/query_first.py`, `query_first_router.py`, evaluation/NLP/annotation models, `frontend/src/projects/evaluation/QueryFirstSessionPage.tsx` and `AttemptReview.tsx`; additive migration `7c91d2e8f640_query_first_evaluation.py`. Existing sessions default to workflow version 1; new/cloned API sessions use version 2; unknown legacy query ownership is not fabricated.

Final local evidence for the October 13 user session (some logs dated October 14):
- Actual main backend environment, native Windows: from `backend/`, `uv run pytest tests/ --cov=app --cov-report=term:skip-covered -q` -> **500 passed**, **65.82% coverage** (meets the **60%** floor), and **17 legacy enum serializer warnings**. This proves the native full backend test suite, not completion of the prescribed skill CLI lane.
- Query migration tests: **13 passed**, on scratch SQLite only; not PostgreSQL or full migrated-stack parity proof.
- Native main backend static checks: `uv run ruff check app` passed; `uv run python ../scripts/mypy_ratchet.py` reported **422 existing errors vs baseline 497**, baseline unchanged, **0 new type errors**. These manually equivalent remaining checks completed despite the CLI launcher blocker below.
- Combined backend SQLite slice: **102 passed**, using `Push-Location backend; $env:UV_PROJECT_ENVIRONMENT = "$PWD\.venv-test"; uv run --extra dev pytest tests/test_query_expression.py tests/test_query_first_evaluation.py tests/test_eval_models.py tests/test_eval_router.py tests/test_eval_review.py tests/test_eval_integration.py tests/test_nlp_api.py -q; Pop-Location`.
- Query-first + expression subset: **58 passed**. Named coverage includes selected old-pair commit, immutable standalone endpoints, ownership/provider guard, zero-LLM full run, independent cross-run annotations, same-run replay/retry, permissions/cancel/resume/clone, legacy fixtures, additive migration roundtrip, stale claim and worker startup recovery. These are local tests, not PostgreSQL/live migration proof.
- Skill CLI `test frontend`: **PASS**, all **4 npm checks** (typecheck, lint, tests, build), **57 tests passed**, **10 prior warnings** and a bundle advisory. Evidence: `C:/tmp/cedars-verify/query-first-20261013/evidence/test-frontend-wt-db8175b73584-dirty9417e4ba-20261014-002038.log`. This is not live desktop/mobile browser proof.
- Feature-map renderer is the documentation contract check, not application/full-stack verification.
 - Final judgment lifecycle regression: `uv run --extra dev pytest tests/test_query_first_evaluation.py -q` passed all **33 tests**, including 16 new API cases after the full-suite run. Locked sessions and search/full attempts reject judgments; prior completed sample LLM attempts remain reviewable in an editable session. The full suite was not rerun after this final guard.

Not proved: complete prescribed backend CLI lane, PostgreSQL lane/concurrency/migration rehearsal, full migrated-stack parity, live browser/API drives, parity/infra checks or AWS/DEV deployment. The native full backend suite and manually equivalent static checks passed as recorded above, but the skill backend lane remains blocked on Windows by missing `python3` (`WinError 2` launching `python3 ../scripts/mypy_ratchet.py`); no full CLI backend or `test all` PASS is claimed. `doctor` and `parity check` were blocked by missing `docker`; `infra validate` was blocked by missing `terraform`. Browser attempts encountered a local API HTTP 500 and a mocked page stuck loading; they provide no successful live drive or screenshot proof. PostgreSQL and full migrated parity/live verification remain blocked/unverified. These local results do not establish GitHub CI green. All October 5 live dates retained below refer only to their legacy behavior. Pending proof should run on an isolated migrated stack with synthetic data/fake LLM, including exact revision selection, role 403s, zero classifier-call delta, same-run replay, and annotation/export lineage gaps.

## Baseline preconditions for driving

Every "Driving it" section assumes this, unless its own `Preconditions:` line says otherwise:

```bash
export CEDARS_VERIFY_INSTANCE=<task>   # your own instance: the default is shared by every session in this checkout
CC=.claude/skills/verify-cedars/control-cedars
$CC doctor                 # tools, amd64 emulation, port; if your instance is UP and you did not start it, pick another name
$CC stack up               # parity stack, linux/amd64, waits for ALB health
$CC seed                   # verify-{admin,annotator,viewer}@example.com, project on the fake LLM,
                           # sample CSV ingested: 5 patients / 103 notes
```

After `seed`, `{project}` and `{source}` expand in `api`, `ws`, and `browser` paths. Re-run `seed` for a fresh project. Re-ingesting the sample into the same project yields 0 new rows (text_id is unique).

The seeded project uses provider `vllm`, model `fake-clinical`, api_base `http://fake-llm:8080`, so all LLM features run free and deterministically:
- Classification is positive when an excerpt mentions `dvt`, `thromb` or `embol` with no negation cue just before it.
- `control-cedars llm mode fail|empty|garbage|slow` injects failures live. `llm calls` counts calls (your proxy for Bedrock spend).

## Driving conventions

- One labelled bullet per sub-feature: **sub-feature-id**: action → exact command → observable result. The result must be something a check can see: an HTTP status, a JSON field, visible text, a row count.
- Prefer the user's surface. Use `browser run` for UI features, `api` for API-only ones, and `db query` (read-only) only to confirm state the UI does not show.
- Never change data with SQL. `db query` is read-only by design (CLAUDE.md forbids ad-hoc data fixes). If a state can only be reached by editing the DB, that is a finding.
- Locators: prefer role+name (`{"role":"button","name":"Use sample dataset"}`). When the UI has no accessible name, note it under Gotchas and use the documented fallback (`nth`, css).
- Role checks: run the same action `--as viewer` / `--as annotator` with `--expect 403`, or check the UI hides the control.
- Bedrock is never called by default. `control-cedars bedrock probe --yes-cost` runs only after the user agrees to the cost.

## Proof and skip reporting

For each sub-feature you drive, record one line:

```
<sub-feature-id>  PASS|FAIL|SKIP  <evidence path or observed value>  <one-line reason if FAIL/SKIP>
```

Evidence lands in `$($CC evidence dir)`, per instance (`/tmp/cedars-verify/<instance>/evidence/`), and survives `cleanup` but not a reboot. Most live evidence cited on 2026-10-05 is on instance `live`; the journey re-drives are on `journeys`, the deploy rehearsals on `rehearse`. A SKIP needs a reason ("needs Databricks workspace", "needs user approval for Bedrock cost"). Never write PASS for something you only read about.

## Feature entry contract

Every feature file has this shape, in this order:

```markdown
# <Area name>

Last verified: <commit sha12> on <YYYY-MM-DD> (<source | live>)

<One paragraph: what the area is for, which roles use it, where it lives in the UI, overall maturity.>

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| area-thing | ... | beta | UI+API | 8f2676b6 | 2026-10-05 / not driven | `backend/app/x/router.py:42`, `tests/test_x.py::test_y` |

## How to get to it (user POV)

<Numbered steps from login, with on-screen labels in quotes.>

## Driving it with control-cedars

Preconditions: <baseline, plus anything else>

- **area-thing**: <action> → `control-cedars ...` → <observable result>

## Gotchas

- <defects, traps, things that look broken but are by design. Each with a file:line.>
```

IDs are kebab-case, prefixed with the area (`data-`, `eval-`, ...), and stable. Rename only together with every reference in `multi-surface-journeys.md`.

## Index

| File | Area | Roles | Overall (affected rows 2026-10-13; others 2026-10-05) |
|---|---|---|---|
| [auth.md](auth.md) | Register, login, cookies, refresh, platform admin | all | beta |
| [projects.md](projects.md) | Project CRUD, membership, LLM settings, stats | admin, all | beta |
| [data.md](data.md) | File upload, sample dataset, Databricks, ingestion | admin | beta |
| [patients.md](patients.md) | Patient browser, patient detail, notes, reopen | all | beta |
| [evaluation-setup.md](evaluation-setup.md) | Query-first sessions, inactive query/prompt revisions, attempt history; version-1 flow retained | admin, annotator review, viewer read | beta (v2 not live-driven) |
| [evaluation-run.md](evaluation-run.md) | Keyword-only full run, pinned LLM attempts, selected prior commit, attempt recovery | admin, annotator review, viewer read | beta (v2 not live-driven) |
| [annotations.md](annotations.md) | Sentence/run/attempt lineage, independent per-run records; project-wide patient review | admin, annotator | beta (lineage UI/filter gap; bulk predictions api-only) |
| [jobs.md](jobs.md) | Job dashboard, worker status, retries, WebSockets | admin | beta |
| [export.md](export.md) | Project-wide CSV/JSON, no attempt/run export filter; Databricks | admin, viewer | beta (current JSON not driven; Databricks api-only/stub) |
| [admin-audit.md](admin-audit.md) | Platform admin endpoints, audit log | platform admin | api-only |
| [predictors-nlp.md](predictors-nlp.md) | Version-2 Boolean sentence queries, negation, frozen project-model inputs; legacy NLP/predictors | admin, members read | beta query engine; standalone api-only, PINES stub |
| [platform-ops.md](platform-ops.md) | Health, config, deploy, migrations, S3, CI | operators | beta |
| [multi-surface-journeys.md](multi-surface-journeys.md) | Query-only and selected historical attempt journeys; legacy transcripts retained | all | v2 beta/not driven; October 5 outcomes are legacy only |

## Sweep order

Areas build on each other's data. Sweep in this order so each one starts with what it needs:

1. platform-ops (stack healthy, migrations at head)
2. auth
3. projects
4. data
5. patients
6. evaluation-setup
7. evaluation-run
8. jobs
9. annotations
10. export
11. admin-audit
12. predictors-nlp
13. multi-surface-journeys
