# Watertight CI for CEDARS v2

Date: 2026-10-07. Status: implemented on branch `chore/watertight-ci`, not yet pushed.

## Goal

Any breakage an agent (or human) can introduce is caught before merge, so many agents can work in parallel
on `feature/v2-platform` and `main`. Every check runs the same command locally and in CI.

## Decisions

- Full-stack lane (image builds + `control-cedars` smoke) is **required on every PR**.
- **v1 (`cedars/`, Flask) is dropped from CI.** `.github/workflows/ci.yml` is deleted. Docs deploy moves to a
  `docs.yml` that runs on pushes to `main` only.
- **Playwright e2e is included** in the full-stack lane.
- **No AI review job** in CI. Review stays a local, human-triggered step.

## Workflows

`ci.yml` (new, replaces v1) triggers on every `pull_request` and on pushes to `main` and `feature/v2-platform`.
No path filters, so the gate can never be skipped. Concurrency cancels superseded runs per ref. Every job has a
`timeout-minutes` and `permissions: contents: read`. Actions are pinned to commit SHAs.

| Lane | Contents |
|---|---|
| static | `ruff check`, `ruff format --check`, mypy on `backend/app`, frontend `tsc -b` and eslint, `terraform fmt -check` and `validate` (`infra/cedars-v2`), `control-cedars parity check`, actionlint |
| backend | pytest on SQLite with coverage; pytest on Postgres 16 built from Alembic |
| migrations | upgrade, downgrade, upgrade on empty Postgres; `alembic check` (model/migration drift); exactly one head |
| frontend | `npm ci`, `npm run build`, vitest (scaffold plus one smoke test per route) |
| full-stack | amd64 image builds, `control-cedars stack up`, `migrate status`, HTTP smoke (register, login, create project, health via ALB-style nginx), Playwright e2e on the same stack |
| security | `pip-audit`, `npm audit --audit-level=high`, gitleaks, CodeQL (Python, TS), Trivy on built images; also weekly on a schedule |
| gate | job `CI gate`: needs all lanes, fails if any was failed, cancelled or skipped. The only required status check |

## Guards against agent failure modes

- **Weakened tests:** a coverage floor that can only rise (stored in the repo, changed only on purpose), and a
  check that fails when a PR deletes tests or adds skip/xfail markers without a `ci-allow-test-removal` label.
- **Quiet output:** pytest `-q` with a failure summary, short npm and uv output, so logs stay cheap to read.
- **Local parity:** `scripts/check` runs the static lane locally; `control-cedars test all` and `stack` cover the rest.
- **Parallel isolation:** each full-stack run uses a unique `CEDARS_VERIFY_INSTANCE` and compose project name.
- **CI-created commits:** must use a GitHub App token, since the default `GITHUB_TOKEN` does not trigger checks.

## Repo settings (applied only after the workflows are green, and only with explicit user approval)

Branch protection on `feature/v2-platform` and `main`: require `CI gate`, require up-to-date branch, no direct
pushes, dismiss stale approvals. Dependabot for github-actions, pip, npm and docker. PR template with the
`CLAUDE.md` checklist (feature-map row, migration, skill updates).

## Out of scope

Mutation testing, load testing, merge queue, AI review job, v1 CI.

## Rollout

1. Add workflows on a branch; get them green; fix what they find (mypy errors, audit hits).
2. Add Dependabot, PR template, `scripts/check`.
3. Ask for approval, then enable branch protection.

Changes under `.claude/skills/` need the user's approval first (project rule).

## Open items

- Initial coverage floor: measure the current value, then set it just below.
- Whether `control-cedars` runs on the GitHub runner as-is (needs Docker and amd64); verify during step 1.

## As built: deviations from the draft

- **Ratchets instead of day-one cleanliness.** The repo was not clean, so these fail only when things get worse:
  mypy (`backend/.mypy-baseline`, 497), eslint warnings (`--max-warnings=10`), model/migration drift
  (`backend/.alembic-drift-baseline`, 48 markers), dependency vulnerabilities (`scripts/audit-baseline.json` (IDs),
  106 distinct Python vulnerability IDs and 2 high npm packages, tracked by ID) and coverage (`fail_under = 60`, measured 60.9%). Lower each as the debt is paid down.
- **Ruff:** `E501` is ignored (44 long lines) and `ruff format` is not enforced (44 files would change).
- **Dependency audit** runs on PRs only when a dependency file changed (so a newly published CVE cannot turn every
  open PR red); the weekly workflow audits unconditionally.
- **Trivy image scan not added:** the backend image has 6 CRITICAL findings today (e.g. PyJWT 2.11.0). Add it once they are fixed.
- **CodeQL** runs weekly, not per PR.
- **Playwright e2e** uses `control-cedars browser run e2e/smoke.json`, so no separate Playwright project.
- **Fixed on the way:** `backend/migrations/env.py` did not import `app.pipeline.models`, so autogenerate could not see the pipeline tables.
- **Not verifiable locally:** the GitHub-hosted runner behaviour (Docker/amd64, Playwright browser install, caches). First push is the real test.
