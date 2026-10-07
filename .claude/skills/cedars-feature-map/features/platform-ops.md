# Platform ops

Last verified: e954cdaae2f2 on 2026-10-06 (source + local checks; `aws status` rows as of cef61132 on 2026-10-05)

Platform ops is everything an operator touches to run CEDARS v2 rather than use it. That covers the health and metrics endpoints, Settings and the env vars ECS sets, the S3 client, Alembic migrations, the manual ECS deploy runbook, CI, secret scanning, the local dev compose file and the control-cedars parity stack that verifies all of it. There is no UI. Operators use the ALB, Terraform, `aws` and control-cedars. Overall: **beta**. The deployed stack works: DEV runs cef61132 on all three services with healthy targets, and the parity stack reproduces it on amd64. But CI has never passed, `alembic check` is broken, deploys are manual, and S3 is safe only because ECS passes the right empty strings.

## Sub-features

| ID | What it does | Maturity | Surface | Since | Live | Evidence |
|---|---|---|---|---|---|---|
| ops-health | `GET /api/v1/health` returns `{"status":"ok","version":"2.0.0"}`. It is the ALB backend target health check | stable | ALB | bd750af4 | 2026-10-05 | `backend/app/main.py:138-140`, `infra/cedars-v2/alb.tf:31-33`, `tests/test_health.py::test_health_endpoint` |
| ops-metrics | Prometheus `/metrics` on the backend (Instrumentator) | api-only | in-cluster | 76473b27 | 2026-10-05 (ALB serves the SPA instead) | `main.py:104-106`, `tests/test_metrics.py::test_metrics_endpoint_exists`, `alb.tf:110-111`, `prometheus.v2.yml` |
| ops-settings | pydantic-settings with prefix `CEDARS_` and `.env`; ECS sets env and two secrets | beta | config | 22568443 | 2026-10-05 (`parity check` 47/47) | `backend/app/config.py:13-51`, `infra/cedars-v2/ecs.tf:38-54`, `main.tf:15-17` |
| ops-startup-validation | `_validate_settings` refuses an unsafe `SECRET_KEY` unless every CORS origin is localhost; warns on insecure cookies | beta | startup | a5b72355 | not driven | `main.py:44-82`. No test |
| ops-s3 | boto3 client: upload on file upload, download in ingestion, MinIO bucket bootstrap when an endpoint is set | beta | backend | cf2dd65c | 2026-10-05 (seed upload + ingest via default chain) | `backend/app/common/s3.py:13-47`, `connectors/service.py:137-138`, `connectors/file_upload.py:87`, `main.py:21-41`. Tests mock it (`tests/test_connectors_api.py:223`) |
| ops-migrations | 24 Alembic migrations, single head `f8a1c2d3e4b5`, run by the ECS migrate task | beta | migrate task | b41a98a5 | 2026-10-05 | `backend/migrations/env.py:37-43`, `ecs.tf:219-244`, `tests/conftest.py:69-83` (Postgres tests build via Alembic). `migrate status` at head; `migrate check` round-trip passes |
| ops-migrations-drift | `alembic check` / autogenerate compares models to the schema | stub | CLI | 8c8e532e | 2026-10-05 (fails) | `migrations/env.py:22-32` never imports `app.pipeline.models`, so `annotations.pipeline_run_id` → `pipeline_runs` raises NoReferencedTableError |
| ops-ci-backend | `ci.yml`: static, backend SQLite and Postgres 16, migrations ratchet, frontend, full-stack (images, seed, API smoke, Playwright), security, all behind `CI gate` | stub | CI | ecd0de5c | 2026-10-07 (local, per lane) | `.github/workflows/ci.yml`. Every lane's commands pass locally (382 backend tests, 60.9% coverage vs floor 60, 16 vitest tests, e2e `e2e/smoke.json`). No GitHub run yet: the branch is unpushed. Ratchets: mypy 497, eslint 10 warnings, drift 48, vulnerabilities 106 py IDs / 2 npm (by ID). Not gated: `ruff format`, Trivy image scan (backend image has 6 CRITICAL) |
| ops-frontend-checks | `tsc --noEmit`, `eslint src/`, `npm run build`, local only (no CI job) | beta | local | n/a | 2026-10-05 (`test frontend`) | tsc and build pass, eslint 8 errors. No frontend workflow in `.github/workflows/` |
| ops-secret-scan | gitleaks with `.gitleaks.toml`: the default rules plus AWS account IDs, private IPs, internal hostnames and Terraform Cloud org/workspace names. A pre-commit hook, and `secret-scan.yml`, which scans the commits a PR or push adds; a manual run scans all history | beta | CI + pre-commit | e954cdaa | 2026-10-06 (`secrets scan`) | `.gitleaks.toml`, `.pre-commit-config.yaml`, `.github/workflows/secret-scan.yml:37-60`, `control-cedars secrets scan --help` |
| ops-infra-terraform | ECS Fargate stack: backend x2, worker x1, frontend x2, migrate task, ALB, Aurora PG16, ElastiCache, S3, ECR | beta | Terraform | e954cdaa | 2026-10-06 (`infra validate`) | `infra/cedars-v2/ecs.tf`, `alb.tf`, `elasticache.tf:31-34`, `variables.tf:92-96`. The account ID and TFC org/workspace come from workspace variables and the environment, not the repo (`versions.tf`, `variables.tf:11-19`, `iam.tf` locals) |
| ops-deploy-runbook | Manual deploy: build, push to ECR, migrate task, roll the services | beta | operator | e954cdaa | 2026-10-05 (`aws status`: DEV = cef61132) | `infra/cedars-v2/README.md:114-160`. No deploy workflow |
| ops-deploy-rehearsal | `deploy rehearse`: old release plus data, a baseline of what it serves, migrate with the new image, the old release must still serve that baseline, then roll and check the new release | beta | control-cedars | db51c9f1 | 2026-10-05 PASS (64d13687 → cef61132) | `/tmp/cedars-verify/rehearse/evidence/deploy-rehearsal-*.json`, `control-cedars deploy rehearse --help` |
| ops-offline-start | Containers start without internet | beta | runtime | a66c912d | not driven | `backend/Dockerfile:3-8`, `ecs.tf:110`, `:232` (`uv run`); LiteLLM cost-map fetch at import, with a local fallback |
| ops-bedrock-probe | One positive and one negative synthetic excerpt classified through real Bedrock in the amd64 image | beta | control-cedars | untracked | not driven (needs approval) | `backend/app/llm/client.py:119-120` (no `aws_*` kwargs, default chain), `control-cedars bedrock probe --help` |
| ops-parity-stack | control-cedars stack: ALB-style nginx, Postgres 16.11, Redis 7.0, MinIO via default chain, fake LLM, amd64 build | beta | control-cedars | db51c9f1 | 2026-10-06 (`parity check` 47/47) | `.claude/skills/verify-cedars/stack/compose.parity.yml:20-38`, `:131`, `:144-145`, `stack/alb.nginx.conf:57-84` |
| ops-dev-compose | `docker-compose.v2.yml`: db, redis, minio, backend, worker, frontend on :3000, prometheus on :9090 | stub | local | e954cdaa | not driven | `docker-compose.v2.yml:31` (image cannot be pulled); no migrate step |

Why the grades:
- **ops-health is `stable`.** Its consumer is the ALB, not a page. It is tested, driven live, and DEV targets are healthy. It is liveness only: it does not touch Postgres or Redis.
- **ops-ci-backend is `stub`.** The workflow exists but has never given a green signal. The SQLite job stops at ruff (44 × E501; `line-length = 100` in `backend/pyproject.toml:52`), so CI never runs its pytest. On commits in the branch history, the Postgres job failed once, on `test_annotations_api.py::TestPatientReview::test_delete_event_date` (cef61132), which passes locally, so it is likely flaky. Two other names in old CI logs, `test_adjudication_handler.py` and `test_workflow_flow.py`, came from commits a force-push removed and do not exist in `backend/tests`. `ci status` marks those runs `NOT in local history`.
- **ops-migrations-drift is `stub`.** `alembic check` crashes before it compares anything.
- **ops-dev-compose is `stub`.** On a clean machine it cannot start, because the MinIO tag cannot be pulled. Even with MinIO, a fresh volume has no schema, because nothing runs `alembic upgrade head`.
- **ops-settings and ops-s3 are `beta`.** They work on ECS, but only because `ecs.tf:40-42` passes `""` for three settings whose code defaults are MinIO values.
- **ops-secret-scan is `beta`.** The rules catch every planted test value and pass on new commits, but `secret-scan.yml` has not run on GitHub yet. The hook runs only in clones that ran `pre-commit install`. A manual full-history run fails on 45 findings in old commits (see Gotchas).

## How to get to it (user POV)

There is no UI. An operator:
1. Opens `http://<alb>/api/v1/health` (from the VPN) and expects `{"status":"ok","version":"2.0.0"}`.
2. Deploys with the runbook in `infra/cedars-v2/README.md:114-160`, after exporting `TF_CLOUD_ORGANIZATION` and `TF_WORKSPACE` for the CLI. The practised version is: ECR login → `docker build --platform linux/amd64` → push `<sha>` and `latest` → run the migrate task → `aws ecs update-service --force-new-deployment` on backend, worker and frontend → `aws ecs wait services-stable` → check target health and `/api/v1/health`.
3. Checks CI on the GitHub Actions tab ("CI", job "CI gate") or with `control-cedars ci status`.
4. Runs the parity stack locally with control-cedars (below) before deploying.

## Driving it with control-cedars

Preconditions: the baseline (`doctor`, `stack up`, `seed`). `aws status`, `deploy rehearse --from aws` and `bedrock probe` need a live `saml` profile. Without one, mark them SKIP with "AWS credentials expired".

- **ops-parity-stack**: `$CC stack status` → UP, backend x2 healthy, worker running, migrate exited 0, ALB `/api/v1/health` 200, worker heartbeat True, llm mode normal (driven 2026-10-05). `$CC doctor` → tools, amd64 emulation and port all OK.
- **ops-health**: `$CC api GET /api/v1/health --as anon --save ops-health` → 200 `{"status":"ok","version":"2.0.0"}` (driven 2026-10-05).
- **ops-metrics**: `$CC browser snapshot /metrics --as anon --save ops-metrics-alb` → blank page plus `401 GET /api/v1/auth/me` (driven 2026-10-05). The ALB stand-in sends `/metrics` to the frontend, whose SPA has no matching route. SKIP-able for the real metric text: no control-cedars command reaches `backend:8000` directly, and `api GET /metrics` becomes `/api/v1/metrics` → 404.
- **ops-settings**: `$CC parity check` → "47/47 match" (driven 2026-10-05). The NOTE lines: `pines_api_url` and `allow_cloud_llm` are never read; `s3_endpoint`, `s3_access_key` and `s3_secret_key` default to MinIO values; `uv:latest` and `nginx:alpine` float; containers start through `uv run`. `CORS_ORIGINS=http://localhost:5173` and `COOKIE_SECURE=false` on both sides.
- **ops-startup-validation**: SKIP-able, because no command sets a single env var on the stack. Source check only. `$CC stack logs backend --grep 'unsafe default'` → no lines, since the stack injects a random `CEDARS_SECRET_KEY` (`compose.parity.yml:30`).
- **ops-s3**: after `seed` → `$CC db query "select connector_type, status, config->>'s3_key' from data_sources"` → `FILE_UPLOAD | COMPLETED | projects/<pid>/uploads/<uuid>/simulated_patients.csv`, and `$CC db query "select count(*) from notes"` → 103 (driven 2026-10-05). The stack leaves every `CEDARS_S3_*` empty and points boto3 at MinIO through `AWS_ENDPOINT_URL_S3` (`compose.parity.yml:20-38`), so this exercises the native-AWS code path.
- **ops-migrations**: `$CC migrate status` → `alembic current ['f8a1c2d3e4b5'] heads ['f8a1c2d3e4b5'] -> at head` (driven 2026-10-05). `$CC migrate check` (scratch DB) → upgrade, single head, `downgrade -1` and re-upgrade all pass (user run 2026-10-05).
- **ops-migrations-drift**: `$CC migrate check` → the `alembic check` step fails with NoReferencedTableError for `annotations.pipeline_run_id` → `pipeline_runs`, and the command exits 1 (user run 2026-10-05). Once fixed, expect "No new upgrade operations detected", or a list of real drift (see Gotchas).
- **ops-ci-backend**: locally `scripts/check` → ruff, mypy ratchet, tsc, eslint, terraform fmt, parity all `ok`; `$CC test all` → PASS; `CEDARS_DATABASE_URL=… scripts/migration_check.sh` on an empty Postgres → single head, round trip, drift 48/48; full-stack: `$CC stack up`, `seed`, `api`, `browser run e2e/smoke.json --as admin --strict` → PASS (2026-10-07). On GitHub: `$CC ci status` once the branch is pushed.
- **ops-frontend-checks**: `$CC test frontend` → tsc passes, build passes, eslint reports 8 errors, exit 1 (user run 2026-10-05). `--ci` runs `npm ci` first.
- **ops-secret-scan**: `$CC secrets scan` → `PASS, 0 finding(s)` for the commits on HEAD that are not on `origin/feature/v2-platform`, the same range CI scans on a PR (driven 2026-10-06 at e954cdaa). `$CC secrets scan --tree` → scans the files git would commit now, uncommitted edits included. It finds 2, both `msk-internal-hostname` in `.agents/skills/msk-dsm-antd-setup/SKILL.md` (driven 2026-10-06). `$CC secrets scan --all` → 45 findings in history, exit 1 (driven 2026-10-06). Output never contains the matched value. `--json` adds fingerprints, which a `.gitleaksignore` could list. `$CC ci status --workflow secret-scan.yml` reads real CI once the workflow has run.
- **ops-infra-terraform**: `$CC infra validate` → `terraform fmt -check`, `init -backend=false` and `validate` all pass (driven 2026-10-06). It never runs plan or apply.
- **ops-deploy-runbook**: `$CC aws status` → backend, worker and frontend all on cef61132, task definition revision 1, targets healthy, no undeployed commits on HEAD (user run 2026-10-05). It makes describe/list calls only.
- **ops-deploy-rehearsal**: `$CC deploy rehearse --from aws` → reads the deployed SHA, starts that release with data, probes five read endpoints as a baseline, migrates with the working-tree image, re-probes the old release, rolls, then probes the new one. Exit 0 means the migration is backward compatible. While DEV equals HEAD the rehearsal tests only the mechanics. Use `--from <older sha>` to cross a real migration. It needs a fresh DB, so run it on its own instance (`export CEDARS_VERIFY_INSTANCE=rehearse-<date>`). If `doctor` shows that name UP and you did not start it, pick another.
  - 2026-10-05 `--from 64d13687` → PASS, 16 steps. Migrate ran `d1f2a3b4c5e6 -> f8a1c2d3e4b5, add pipeline annotation columns` while the old tasks served. The old release's `GET /data/patients` was already 500 before the migration (`operator does not exist: reviewstatus = character varying`, the drift b41a98a5 fixed). It returned 200 after the migration, and the other four endpoints stayed 200. After the roll all five returned 200 and the 5 patients survived (`deploy-rehearsal-20261005-005636.json` on instance `rehearse`). An earlier attempt, `deploy-rehearsal-20261005-005320.json`, stopped with a JSONDecodeError. That was a control-cedars bug, since fixed: `seed` parsed the old release's 500 response. It says nothing about the deploy.
  - 2026-10-05 `--from cf50d0da` → FAIL at "old release up": `ALB / returned 502: frontend crashed with nginx: [emerg] host not found in upstream "backend"`. That is the ECS crash fixed in cf2dd65c. The parity stack keeps the frontend off the backend's DNS, as on ECS, so releases before cf2dd65c cannot be rehearsed. Choose `--from` at or after cf2dd65c. Evidence: `deploy-rehearsal-cf50d0da-console.log` on instance `rehearse`, the console output only, because this run predates the rehearsal writing its JSON on failure.
- **ops-offline-start**: `$CC stack up --no-egress` → `stack status` shows backend x2 healthy and the worker heartbeat present, and `api GET /api/v1/health` returns 200. A failure points at `uv run` trying to sync (it may need PyPI to build the editable project) or at a slow LiteLLM cost-map fetch. Not driven (`stack up` is outside this read-only pass).
- **ops-bedrock-probe**: only after the user approves the cost → `$CC bedrock probe --yes-cost` → two paid Haiku calls in the amd64 image: the positive excerpt labelled positive with a high score, the negative one labelled negative with a low score. SKIP: needs user approval for Bedrock cost and a live `saml` profile.
- **ops-dev-compose**: SKIP. The verify-cedars skill forbids using `docker-compose.v2.yml` for verification, and its MinIO image cannot be pulled.

## Gotchas

- **Settings that nothing reads.** `allow_cloud_llm` (`config.py:43`, set to `"true"` at `ecs.tf:47`) gates nothing, so no code stops PHI going to a cloud LLM. `pines_api_url` (`config.py:40`) is also unused; PINES reads `config.get("pines_api_url")` from the predictor config (`predictors/pines.py:16`).
- **S3 fails over silently to MinIO.** The code defaults are `http://localhost:9000`, `rootuser` and `rootpassword` (`config.py:33-36`). AWS mode works only because ECS passes all three as `""` (`ecs.tf:40-42`). Dropping one of those lines gives connection errors to localhost or fake static keys, with no startup error. `_ensure_s3_bucket` runs only when an endpoint is set, and swallows errors (`main.py:21-41`).
- **The secret-key guard is bypassed on ECS.** `main.tf:17` falls back to `CORS_ORIGINS=http://localhost:5173` when `app_hostname` is empty, as it is today (HTTP spike). `_validate_settings` then treats the deployment as local and only warns about an unsafe `SECRET_KEY` (`main.py:55-69`). The match is a substring test, so an origin such as `https://localhost.example.org` also counts as local.
- **`alembic check` and autogenerate are broken.** `migrations/env.py:22-32` imports every model module except `app.pipeline.models` (EventConfig, PipelineRun, PatientTask, Evidence). Once that is fixed, expect real drift to show:
  - Legacy tables with no model: `evaluation_sessions`, `evaluation_judgments` and `validated_predictors`. The live schema has 23 data tables (plus `alembic_version`) against 20 `__tablename__` models.
  - A stray enum label: `patienttaskstatus` holds both `no_match` and `NO_MATCH`, because `ec642691720e` added the upper-case label while the model stores `no_match` (`pipeline/models.py:47`).
  - CI runs no `alembic check`.
- **Migrations ship only through the runbook.** The ECS migrate task is run by hand (`README.md:143-149`), and nothing in CI or ECS runs it. The written runbook also re-applies Terraform with new image tags (step 2, `README.md:140-141`), which rolls the services, before migrating (step 3, `:143-149`), although step 3's own comment says "BEFORE the backend serves traffic". New tasks can serve against the old schema. The practised flow migrates first and then forces a new deployment.
- **Images are mutable and unpinned.**
  - Both ECR repositories set `image_tag_mutability = "MUTABLE"` (`ecr.tf:22`, `:35`), so pushing a SHA tag again silently replaces what it pointed at. The base images float too (`python:3.12-slim`, `ghcr.io/astral-sh/uv:latest`, `node:20-alpine`, `nginx:alpine`), so a rebuild of the same commit is not byte-identical to the image you verified. Push the digest you tested, or rebuild and re-verify.
  - `backend_image_tag` and `frontend_image_tag` default to `latest` (`variables.tf:92-102`), and DEV is still on task definition revision 1, so a rollout is "push `latest`, force a new deployment".
  - The runbook's `docker build` lines lack `--platform linux/amd64` (`README.md:142-143`). Fargate has no `runtimePlatform` set and assumes x86_64, so an Apple-silicon build fails at start.
  - Use `${REPO}:latest` with braces; in zsh, `$REPO:latest` drops the `l`.
- **The container start path can drift.** `uv:latest` is copied in unpinned (`backend/Dockerfile:3`), `nginx:alpine` floats (`frontend/Dockerfile:8`), and every command starts with `uv run` (`Dockerfile:8`, `ecs.tf:110`, `:232`). Without `--frozen` or `--no-sync`, `uv run` may sync at start. Two related problems:
  - `--no-dev` is a no-op, because `dev` is an optional extra (`pyproject.toml:39-48`).
  - `COPY . .` (`Dockerfile:6`) plus a `.dockerignore` with five patterns (`backend/.dockerignore`: `__pycache__`, `.venv`, `tests/`, `.pytest_cache`, `*.pyc`) copies everything else in `backend/` into the image. That includes a local `.env`, `.coverage`, `.DS_Store`, and the tracked `backend/test.db` (274 KB, no tables). The runbook builds from the working tree (`docker build ../../backend`), so whatever is lying there ships. Build from a clean checkout (`control-cedars stack up --ref`).
- **Old commits still hold internal values.** e954cdaa removed the account ID, the TFC org and workspace, and the VPN hosts from the tracked files, and the scan gates new commits. But `secrets scan --all` still finds 45 in history, on public branches and PR refs. They are listed by commit privately, not in this public repo. Do not copy values into the map.
- **The secret scan runs on PRs into `main` only once `secret-scan.yml` is on `main`.** GitHub runs a PR's workflows from the merge with its base.
- **No proxy headers.** uvicorn runs without `--proxy-headers` (`Dockerfile:8`), so behind HTTPS the app sees the scheme as `http`.
- **Workers and Redis.**
  - No container has an ECS `healthCheck`, and there is no deployment circuit breaker (`ecs.tf:60-245`). A wedged worker stays "running".
  - Redis TLS is off (`elasticache.tf:31-34`), and `parse_redis_settings` ignores a `rediss://` scheme (`worker.py:32-40`).
  - See `jobs.md` for the one-hour stale heartbeat.
- **Database connections.**
  - The shared engine has no `pool_pre_ping` or `pool_recycle` (`common/database.py:10`), which risks stale connections when Aurora Serverless scales.
  - The job modules each create an engine and never dispose of it (`jobs/ingestion.py:16`, `jobs/nlp.py:20`, `jobs/prediction.py:24`, `jobs/pipeline.py:48`).
  - `init_db` / `create_all` is never called outside tests (`database.py:14-17`).
- **Metrics are not scraped on ECS.** The ALB sends only `/api/*` and `/ws/*` to the backend (`alb.tf:110-111`), so `/metrics` reaches the frontend. The SPA has no `path="*"` route (`frontend/src/App.tsx:116-128`), so the page is blank (driven). Only the dev compose scrapes `backend:8000` (`prometheus.v2.yml`).
- **The health check is liveness only.** It returns 200 with Postgres or Redis down, and `version` is hard-coded `"2.0.0"`, not the git SHA (`main.py:138-140`). Use `aws status` to learn what is deployed.
- **S3 objects are never deleted.** `delete_file` has no callers (`common/s3.py:44-47`), and the bucket is versioned with no lifecycle rule (`infra/cedars-v2/s3.tf:15-20`).
- **The dev compose is not the deployment.**
  - `minio/minio:RELEASE.2024-05-10T01-41-38Z` cannot be pulled (`docker-compose.v2.yml:31`). The parity stack uses `bitnamilegacy/minio:2025.7.23-debian-12-r5`.
  - There is no migrate service, and the dev secret key is fixed.
  - `extra_hosts` comes from `LLM_HOST_{1,2}` and `LLM_HOST_{1,2}_IP` in `.env` (`docker-compose.v2.yml:51-56`, `:76`). Unset, they map unused names to 127.0.0.1. Keep real hosts in `.env` only.
- **What the parity stack cannot reproduce** (verify-cedars SKILL.md):
  - the IAM task role and Bedrock grants
  - SSE-KMS and the TLS-only bucket policy
  - real ALB health checks and deregistration
  - Aurora Serverless scaling and its reader
  - ElastiCache 7.1 (the stack runs 7.0)
  - VPC egress rules
  - native amd64: the stack runs under emulation on Apple silicon
  - Terraform Cloud
  - the AWS-injected `aws-guardduty-agent-*` sidecar that every DEV task carries
  - Secrets Manager injection and CloudWatch logs
  - the rolling overlap: ECS runs old and new tasks side by side (min 100 / max 200, `ecs.tf:170-171`, `:209-210`); the stack swaps them all at once
  - image provenance (floating bases, above) and the CI host (ubuntu x86_64)
- **No deploy CI.** `ci.yml` verifies the images build and the stack runs, but nothing deploys; the ECS runbook in `infra/cedars-v2/README.md` is still manual. CI-created commits need a GitHub App token, since the default `GITHUB_TOKEN` does not trigger checks.
