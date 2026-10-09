---
name: verify-cedars
description: Use when verifying a CEDARS v2 change end to end, before or after deploying to the AWS ECS dev environment, when reproducing a DEV-only bug locally, when checking that CI, migrations or Terraform still pass, or when asked to test, smoke-test, QA or prove a CEDARS feature works.
---

# Verify CEDARS

All verification goes through one CLI, `control-cedars`, in this directory. It runs a local copy of the `infra/cedars-v2` ECS deployment and gives a command for every check we use: CI, migrations, Terraform, API, browser, AWS status and Bedrock.

```bash
CC=.claude/skills/verify-cedars/control-cedars   # from the repo root; uv runs it, no install step
$CC --help ; $CC <command> --help                # every command has examples
```

**Core rule:** if `control-cedars` can run a check, run it that way. Use `$CC api`, `$CC browser` and `$CC db query` instead of a raw `curl`, `docker compose` or `psql`. Never verify with `docker-compose.v2.yml` (one backend, no ALB rules, an unpullable MinIO image). Commands echo what they run (`+` lines). Exit codes: 0 pass, 1 check failed, 2 usage or precondition error (the message says how to fix it).

## What it mirrors

| AWS (infra/cedars-v2) | Parity stack |
|---|---|
| ECS backend ×2 (1024/2048), worker ×1 (2048/4096), frontend ×2 (256/512), Fargate X86_64 | same replicas and limits; images `docker build --platform linux/amd64` |
| One-off migrate task, `alembic upgrade head` | `migrate` service; app services wait for it to exit 0. ECS gates nothing: the order is up to whoever deploys (see AWS parity) |
| Internal ALB: `/api/*`, `/ws/*` → backend (sticky 3600s), rest → frontend, idle 300s | nginx `alb` with the same rules, AWSALB cookie, timeouts |
| ecs.tf env + secrets | identical `CEDARS_*` names and values; DSN shape `postgresql+asyncpg://cedars:…@…:5432/cedars` |
| Aurora PG 16.11 / ElastiCache 7.1 | postgres 16.11 / redis 7.0.15 (no OSS 7.1) |
| S3 bucket via task role | empty `CEDARS_S3_ENDPOINT`/keys, default credential chain pointed at MinIO; bucket pre-created like Terraform |
| Bedrock | `fake-llm` (OpenAI-compatible, deterministic, free); real Bedrock only via `bedrock probe` |

`$CC parity check` diffs the compose file and ALB config against the Terraform and exits 1 on drift. Run it after editing either side.

## Launch

```bash
$CC doctor                       # tools, amd64 emulation, port, other sessions' containers (leave those alone)
$CC stack up                     # working tree → amd64 images → up → migrate exit 0 → ALB health 200 ×2 → worker heartbeat
$CC stack up --ref c7cf4c74      # any git ref, built in a detached worktree (e.g. a previous release)
$CC seed                         # 3 synthetic users, a project on the fake LLM, sample CSV ingested (5 patients / 103 notes)
```

**Name your instance** before anything that mutates: `export CEDARS_VERIFY_INSTANCE=<task>` (or `--instance`). The default instance is the repo folder name, so every session in this checkout shares it. If `doctor` shows your instance UP and you did not start it, another session did: pick another name. Never `stack down` a stack you did not start.

`--platform native` builds arm64 (faster on Apple silicon; Fargate is amd64, so say so in the report). `--no-egress` cuts internet access to expose hidden dependencies. Working-tree images are tagged by commit plus a hash of uncommitted changes, and include other sessions' uncommitted edits to this checkout. `--ref` builds a clean detached worktree.

## Drive

| Need | Command |
|---|---|
| Call the API as a role | `$CC api GET /projects/{project}/data/patients --as viewer` (`--body`, `--file`, `--form`, `--expect 403`, `--save NAME`) |
| Drive the UI | `$CC browser run - --as admin --save NAME <<'EOF' [ {"goto":…}, {"click":{"role":"button","name":…}}, {"expect_text":…} ] EOF` |
| Capture an id; wait for async work | `S=$($CC api POST … --field id)`; `$CC api GET …/sessions/$S --until metrics.llm_status=completed` (`PATH!=VALUE`, `[*]` for every list item; exit 1 on `--timeout`). Never `sleep` and hope |
| Learn labels and locators | `$CC browser snapshot /projects/{project}/evaluation --as admin` |
| WebSocket like a browser | `$CC ws /ws/projects/{project}/jobs/<id> --seconds 5` |
| Inspect state (read-only) | `$CC db query "select status, count(*) from patients where project_id='{project}' group by 1"` (scope to the project: other seeds share the DB) |
| Logs | `$CC stack logs worker backend --since 10m --grep 'Traceback|ERROR'` (Python regex; exit 1 if no match) |
| Kill and restart a task | `$CC stack restart worker` (orphan recovery covers pipeline runs only; sample runs are not recovered) |
| Inject LLM failures | `$CC llm mode empty\|fail\|garbage\|slow\|normal`; count calls with `$CC llm calls` |

For what to drive per feature, with exact steps, read the cedars-feature-map skill (`.claude/skills/cedars-feature-map/features/`).

`db query` is read-only (`default_transaction_read_only`); do not get around it with `docker exec … psql`. Find the UI or API path. If only SQL reaches or leaves a state, that is a finding. CLAUDE.md allows a data fix only after the user says yes to the exact statement.

## CI parity

| CI / practice | Command |
|---|---|
| ci.yml backend-sqlite + static: `uv sync --extra dev`, ruff, mypy ratchet, pytest --cov (floor in `pyproject.toml`) | `$CC test backend` |
| ci.yml backend-postgres job: postgres:16-alpine, `CEDARS_TEST_POSTGRES=1` | `$CC test backend --postgres` |
| ci.yml frontend + static jobs | `$CC test frontend`: typecheck, lint (warning count ratcheted), vitest, build |
| Backend (both) + frontend | `$CC test all` |
| What real CI said (read-only `gh`): failed jobs, steps, tests, flaky candidates | `$CC ci status [--limit 10]` |
| Migrations: single head, downgrade/upgrade round trip, models vs migrations drift | `$CC migrate check` (scratch DB) / `$CC migrate status` |
| Whole static lane (ruff, mypy ratchet, tsc, eslint, terraform fmt, parity) in one quiet pass | `scripts/check` |
| Migration ratchet CI uses (single head, round trip, drift may not grow) on an empty Postgres | `CEDARS_DATABASE_URL=… scripts/migration_check.sh` (`migrate check` is stricter: it fails on the known drift) |
| Test-removal guard, dependency audit ratchet | `scripts/check_test_removal.py origin/main`, `scripts/audit_ratchet.py` |
| Terraform | `$CC infra validate`: fmt -check, init -backend=false, validate. Never plan or apply. |

Add `--ref REF` to `test` to test a commit other than the working tree. `migrate check` and `migrate status` have no `--ref`: they use the running stack's image, so `stack up --ref REF` first. `test` runs every step even after a failure and marks the ones real CI never reaches (Lint fails, so CI never runs pytest). Backend CI has never been green on this branch: report "suite passes locally" and "CI is red, because of X" as separate facts.

## AWS parity

| Question | Command |
|---|---|
| What does DEV run? Which commits and migration files on HEAD are not in DEV's image? | `$CC aws status` (read-only describe/list calls; profile `saml`). It diffs git against the deployed SHA; it cannot read Aurora's `alembic_version`, so it cannot prove the migrate task ran |
| Will the deploy runbook work: old tasks serving while the new migration runs, then the roll? | `$CC deploy rehearse --from aws` (or `--from <sha>`) |
| Does real Bedrock classify correctly from this commit's amd64 image? | `$CC bedrock probe --yes-cost`. **Ask the user first** (paid calls); `--image` an older build to show the bug reproduces. It runs locally with your credentials: it proves the model and the code path, not DEV's task role or network. Never report it as "Bedrock works on DEV" |

Before any deploy discussion, run `aws status`; if DEV already runs HEAD, a redeploy changes nothing. Rolling the worker drops any in-flight sample run (the session shows "Classifying" until a 15-minute stall restart). The written runbook (`infra/cedars-v2/README.md`) rolls the services in step 2 and migrates in step 3, so new code meets the old schema. The order that worked on DEV, and the one `deploy rehearse` replays, is migrate, then `update-service --force-new-deployment`. Say which order a deploy plan uses.

If `aws status` says credentials expired, ask the user to log in again (suggest `! aws sso login --profile saml` or their SAML login). Do not copy credentials into files.

**Things local cannot reproduce.** List them in every report: the IAM task role and Bedrock grants, SSE-KMS and the TLS-only bucket policy, real ALB health checks and deregistration, Aurora Serverless scaling and the reader, ElastiCache 7.1, VPC egress, the GuardDuty sidecar, native amd64, Terraform Cloud, Secrets Manager and CloudWatch, the rolling overlap (ECS runs old and new tasks side by side at 100/200%), image provenance (a rebuild pulls floating base images again, so the push is not byte-identical to what you verified), and the CI host (ubuntu x86_64).

## Before a deploy

```bash
export CEDARS_VERIFY_INSTANCE=predeploy-<sha8>; REF=<sha>
$CC doctor; $CC aws status; $CC ci status             # read-only (ci status exits 1 while CI is red). DEV already on $REF? Stop and say so
$CC parity check && $CC infra validate                 # local, read-only
$CC test all --ref $REF                                # CI parity on a clean checkout
$CC stack up --ref $REF && $CC seed && $CC migrate status && $CC migrate check
# drive the change (feature-map "Driving it" bullets), then the multi-surface journeys
CEDARS_VERIFY_INSTANCE=predeploy-<sha8>-rehearse $CC deploy rehearse --from aws --to $REF
```

Build with `--ref`: `backend/.dockerignore` excludes five patterns, so a working-tree build (and the runbook's `docker build ../../backend`) copies whatever lies in `backend/` into the image. `$CC stack status --json` names the images you verified (`images.backend`, `images.frontend`); push those, not a rebuild, and keep them until the push (no `cleanup --images`). All of this is local. The push, the migrate task and the roll each need their own go-ahead.

## Never without asking

Never do any of these without the user's explicit go-ahead:
- push images, `update-service` or `run-task`;
- `terraform plan` or `apply` against the real workspace;
- `bedrock probe`;
- any SQL write;
- commits;
- any write against DEV's app through its API or UI, such as creating sessions or running classifications. DEV holds real users' projects and Bedrock costs money. `control-cedars` never targets DEV's app, so don't point `curl` or a browser at it.

A go-ahead counts only if it names the action ("run the Bedrock probe", "redeploy the worker"). "Do whatever you need" names nothing: ask, listing the exact actions. Approval for one action does not carry over to the next. `--yes-cost` is a flag you pass yourself: it records that the user agreed, it does not ask them. Use synthetic data only; the sample CSV and `@example.com` users are synthetic. The repo is public, so keep account IDs, ARNs and internal hostnames out of files and reports. `aws status` redacts them.

## Evidence

`$CC evidence dir` is `/tmp/cedars-verify/<instance>/evidence/`. It holds test logs, screenshots, ARIA snapshots, `api --save` captures, `fake-llm-calls.jsonl`, and the rehearsal and probe JSON. It survives `cleanup`. Cite these paths in the report.

## Cleanup

```bash
$CC cleanup            # compose down -v, CI postgres, ref worktrees, cookie jars; verifies nothing is left; keeps evidence
$CC cleanup --images   # also removes images this instance built
```

Run cleanup after every session, including failed ones, unless the user is keeping the instance (then say it is up and give its cleanup command). It is idempotent and touches only `cedars-verify-<instance>`. `--images` keeps any image another instance still records (`kept image …`): clean each instance, then re-run the one that kept images. `stack down` without `--keep-volumes` forgets `last_seed`, so re-`seed` before using `{project}`.

## Report shape

1. **Verdict**: PASS / FAIL / PARTIAL, with the commit, platform and instance.
2. **Checks**: a table of check | command | result | evidence path.
3. **AWS differences**: the cannot-reproduce list, plus anything specific to this change.
4. **Findings**: ranked blocker / should-fix / nit, each with a file:line.
5. **Needs the user**: approvals (Bedrock, deploy), expired credentials, decisions.

## Common mistakes

| Mistake | Instead |
|---|---|
| Writing a plan and calling it verification | Run the commands; report what they printed |
| "Unit tests pass" as proof of an LLM or Bedrock fix | Those tests mock litellm. Drive it with `llm mode empty` locally and `bedrock probe` with approval |
| Building arm64 and claiming Fargate parity | Default `stack up` is amd64; if you used native, say so |
| Using a `create_all`-built DB | The stack schema is Alembic-only, like the migrate task |
| Exporting AWS credentials to `/tmp/*.env` | `bedrock probe` mounts `~/.aws` read-only into one container |
| Fixing data with SQL to get unstuck | Find the UI or API path; report the gap. SQL only with a yes to the exact statement |
| Session stuck at "Classifying" after a worker crash; restarting the worker | Sample runs have no orphan recovery. Once `updated_at` is 15 min old, `$CC api POST …/sessions/$S/run-llm --body '{}'` restarts it ("Restarting stalled sample LLM run"). Every `GET /metrics`, including an open step 4, resets that clock. Or discard the session |
| Redeploying because "DEV looks old" | `aws status` first. If DEV runs HEAD, the image is not the cause. Check for a cached `index.html` (the frontend nginx sends no cache headers, `frontend/nginx.conf:29`) or a wrong URL |
| Forgetting cleanup after a failed run | `$CC cleanup` is always safe |
| `strict mode violation … resolved to 2 elements` in `browser run` | Role names match as case-insensitive substrings ("New session" also matches "Clone to new session"). Add `"exact":true`, or `"nth"` when the duplicates are intended |
| `--from` an old release in `deploy rehearse` and reading the failure as a deploy problem | Check the step. "old release up" failing means that release could not run on ECS either; a baseline NOTE marks endpoints that were already broken before the migration |

## Helpers

- `stack/compose.parity.yml`: the stack. Each service names the AWS resource it mirrors.
- `stack/alb.nginx.conf`: the ALB stand-in, with what is mirrored and what is not.
- `stack/fake_llm.py`: the Bedrock stand-in, its classification rule and failure modes.
- State: `/tmp/cedars-verify/<instance>/state.json`, which holds random secrets, the port, images and `last_seed`.
