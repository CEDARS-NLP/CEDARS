# CEDARS v2 feature map

One file per product area. Each file says what exists, how mature it is, how a user reaches it, and how to drive it through `control-cedars` (the verify-cedars CLI, at `.claude/skills/verify-cedars/control-cedars`). Use the map to answer questions without re-reading the whole codebase. Use the source to settle anything the map does not cover or that may have changed.

Scope: the v2 platform only (`backend/`, `frontend/`, `infra/cedars-v2/`). The v1 Flask app (`cedars/`) and PINES service (`PINES/`) appear only where v2 still calls them.

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

"Tests pass" in this map means a local `control-cedars test backend` (SQLite) and `test backend --postgres` run at the file's `Last verified` commit. It does not mean CI is green. `backend-v2.yml` has failed on all 7 runs since it was added (2026-07-06). Two of those ran on commits a force-push later removed, which `ci status` marks `NOT in local history`. On the other 5:
- The SQLite job stops at Lint, 44 × E501, so its pytest step never runs in CI.
- The Postgres job failed once, on `test_annotations_api.py::TestPatientReview::test_delete_event_date` (cef61132). It passes locally, so it is likely flaky.

There is no frontend CI. `control-cedars ci status` shows the current picture; `test frontend` runs tsc, eslint and the build locally.

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

| File | Area | Roles | Overall (2026-10-05) |
|---|---|---|---|
| [auth.md](auth.md) | Register, login, cookies, refresh, platform admin | all | beta |
| [projects.md](projects.md) | Project CRUD, membership, LLM settings, stats | admin, all | beta |
| [data.md](data.md) | File upload, sample dataset, Databricks, ingestion | admin | beta |
| [patients.md](patients.md) | Patient browser, patient detail, notes, reopen | all | beta |
| [evaluation-setup.md](evaluation-setup.md) | Session list, steps 1-2: define event, search queries | admin | beta |
| [evaluation-run.md](evaluation-run.md) | Steps 3-5: sample run, review, metrics, commit, full pipeline | admin, annotator | beta |
| [annotations.md](annotations.md) | Patient-first annotation review, locks, bulk predictions | annotator | beta (bulk predictions api-only) |
| [jobs.md](jobs.md) | Job dashboard, worker status, retries, WebSockets | admin | beta |
| [export.md](export.md) | CSV/JSON export, Databricks export | all | beta (JSON stub, Databricks api-only) |
| [admin-audit.md](admin-audit.md) | Platform admin endpoints, audit log | platform admin | api-only |
| [predictors-nlp.md](predictors-nlp.md) | Predictor configs, PINES, LLM client, spaCy NLP | admin | api-only (PINES stub, LLM client beta) |
| [platform-ops.md](platform-ops.md) | Health, config, deploy, migrations, S3, CI | operators | beta |
| [multi-surface-journeys.md](multi-surface-journeys.md) | End-to-end journeys that cross areas | all | 3 PASS, 2 PARTIAL, 3 FAIL, 2 not driven (2026-10-05) |

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
