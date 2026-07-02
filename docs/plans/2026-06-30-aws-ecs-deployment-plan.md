# CEDARS v2 — AWS ECS Deployment Plan

**Date:** 2026-06-30
**Author:** deployment recon + plan
**Status:** Draft for review
**Scope:** Infrastructure/deployment only. SSO/ezGroups integration is a separate, parallel workstream (the production blocker) and is NOT covered here.

---

## Decision Summary

| Question | Decision |
|----------|----------|
| Platform | **AWS ECS Fargate** (not Databricks Apps — wrong tool for multi-tenant + SSO + isolation) |
| Account | **`180294205688`** (AWS profile `saml`), `us-east-1` |
| Relationship to `clinical-trials-research` | **Separate, self-contained stack.** CEDARS is a distinct product. Shares only account-level primitives (VPC, Bedrock, ECR registry). No DB/data commingling. |
| Tenant isolation | **Single shared platform, logical (row-level) separation** — already implemented in v2 (membership-filtered projects, per-project roles). |
| LLM provider | **AWS Bedrock** (confirmed working in this account — see recon) |

---

## Account Recon (verified 2026-06-30, profile `saml`)

Identity: `arn:aws:sts::180294205688:assumed-role/mskEngineerUser/SinghR7@mskcc.org`, region `us-east-1`.

**What already exists and is reusable:**

| Resource | Value | Reuse |
|----------|-------|-------|
| VPC | `vpc-0429430969d2ccc0a` (10.7.43.0/24) | ✅ Reuse (shared primitive) |
| Subnets | 4 × **private** `/26`, AZs `1a/1c/1d/1f` | ✅ Reuse for ECS + Aurora + Redis |
| Aurora PostgreSQL | v16.11 (`clinical-trials-research-*`) | ❌ Do NOT share — stand up dedicated CEDARS Aurora |
| ECS | `clinical-trials-research-cluster` | ❌ Separate `cedars-v2` cluster |
| ALB | `clinical-trials-research-alb` (**internal**) | ❌ New internal ALB for CEDARS |
| ECR repos | `clinical-trials-backend/-frontend/-agent-runtime` | ✅ Registry reused; new `cedars-*` repos |
| Bedrock | **Claude Sonnet 4 / 4.5, Haiku 4.5, Opus 4.5** — live invoke confirmed | ✅ Use directly |
| Secrets Manager | `user-clinical-trials-research-*` naming pattern | ✅ Follow pattern: `user-cedars-*` |
| Route53 | private zone `clinical-trials-research.local.` | Need CEDARS internal DNS name |

**Key topology fact:** This is an **internal-only** platform. All subnets are private, the existing ALB is `internal`, DNS is a private `.local` zone. There is **no public internet ingress**. CEDARS will be reachable only from the MSK internal network / VPN. This simplifies SSO (sits behind corporate network) and hardening.

**What does NOT exist (net-new for CEDARS):**
- ❌ **ElastiCache Redis** — none in account. The one true infra gap. Required for ARQ queue.
- ❌ Dedicated CEDARS Aurora, S3 bucket, ECS cluster, ALB, task roles.

---

## Target Architecture

```
                 MSK internal network / VPN
                          │
                 ┌────────▼─────────┐
                 │  internal ALB    │  cedars-v2-alb (ACM internal cert)
                 │  :443            │
                 └───┬──────────┬───┘
          /api,/ws   │          │  / (SPA)
                 ┌───▼───┐  ┌───▼──────┐
                 │backend│  │ frontend │   ECS Fargate services
                 │uvicorn│  │  nginx   │   (cedars-v2 cluster)
                 │ :8000 │  │  :80     │
                 └─┬─┬─┬─┘  └──────────┘
        ┌──────────┘ │ └────────────┐
        │            │              │
   ┌────▼────┐  ┌────▼────┐   ┌─────▼─────┐        ┌──────────┐
   │ Aurora  │  │ Elasti- │   │    S3     │        │ Bedrock  │
   │ Postgres│  │ Cache   │   │  bucket   │        │ (runtime)│
   │  16     │  │ Redis   │   │ user-...  │        │  Claude  │
   └────▲────┘  └────▲────┘   └───────────┘        └────▲─────┘
        │            │                                   │
   ┌────┴────────────┴──────┐                            │
   │   worker (ARQ)         │────────────────────────────┘
   │   ECS Fargate service  │   litellm → provider: bedrock
   └────────────────────────┘
```

Three ECS services from **two images** (backend image runs both `backend` and `worker` with different commands — same `backend/Dockerfile`):

| Service | Image | Command | Count | Ingress |
|---------|-------|---------|-------|---------|
| `cedars-backend` | `cedars-backend` | `uv run uvicorn app.main:app --host 0.0.0.0 --port 8000` | 2 (HA) | ALB `/api`, `/ws` |
| `cedars-worker` | `cedars-backend` | `uv run arq app.worker.WorkerSettings` | 1–N | none |
| `cedars-frontend` | `cedars-frontend` | nginx (default) | 2 (HA) | ALB `/` |

---

## Code / Config Changes Required

**Good news: minimal. The app is already deployment-ready.** Findings from code review:

1. **S3 → native AWS S3: config-only, zero code change.**
   `app/common/s3.py` already omits `endpoint_url` when `s3_endpoint` is empty and falls back to the boto3 default credential chain when access keys are empty. So set:
   ```
   CEDARS_S3_ENDPOINT=""          # empty → real AWS S3
   CEDARS_S3_ACCESS_KEY=""        # empty → use ECS task role (IAM)
   CEDARS_S3_SECRET_KEY=""
   CEDARS_S3_REGION="us-east-1"
   CEDARS_S3_BUCKET="user-cedars-v2-storage"
   ```

2. **LLM → Bedrock: config via predictor/pipeline config.** litellm handles `provider: bedrock` using the task role's AWS creds. Verify `pattern_generator.py` / predictor config passes `provider=bedrock` + a model id (e.g. `bedrock/us.anthropic.claude-sonnet-4-...`). Confirm `allow_cloud_llm=true`. **Action item: confirm litellm picks up task-role creds (no explicit keys).**

3. **Database URL → Aurora:**
   ```
   CEDARS_DATABASE_URL="postgresql+asyncpg://cedars:<pw>@<aurora-writer-endpoint>:5432/cedars"
   ```
   Password from Secrets Manager, injected as ECS secret.

4. **Redis URL → ElastiCache:**
   ```
   CEDARS_REDIS_URL="redis://<elasticache-primary-endpoint>:6379"
   ```

5. **Security hardening (production):**
   ```
   CEDARS_SECRET_KEY=<from Secrets Manager, strong>
   CEDARS_COOKIE_SECURE=true
   CEDARS_CORS_ORIGINS="https://cedars.<internal-domain>"
   ```

6. **Alembic migrations** run against Aurora on deploy (one-off ECS task or backend startup hook — decide; recommend a dedicated migration task, not startup, to avoid races across 2 backend replicas).

**No changes needed to:** worker logic, WebSocket endpoints (ALB supports WS on internal), pipeline, predictors' core code.

---

## Infrastructure (Terraform) — Module Breakdown

Clone patterns from the existing `clinical-trials-research` Terraform (the account uses IaC; check the `stackset-terraform-remote-state-*` / `cf-templates-*` state buckets for the module style). Proposed new modules under `infra/cedars-v2/`:

### 1. `ecr.tf`
- `aws_ecr_repository.cedars_backend`
- `aws_ecr_repository.cedars_frontend`
- Lifecycle policy: keep last 10 images.

### 2. `rds.tf` — dedicated Aurora PostgreSQL
- `aws_rds_cluster` (aurora-postgresql 16.x), writer + 1 reader.
- New DB subnet group across the 4 private subnets (or reuse the existing subnet group's subnets in a CEDARS-owned group).
- `aws_security_group.aurora` — ingress 5432 from backend+worker SGs only.
- Master password → `aws_secretsmanager_secret.cedars_aurora_password` (`user-cedars-v2-aurora-password`).

### 3. `elasticache.tf` — the net-new gap
- `aws_elasticache_replication_group` (Redis 7.x), single node to start (or 1 primary + 1 replica for HA).
- Subnet group + `aws_security_group.redis` — ingress 6379 from backend+worker SGs only.

### 4. `s3.tf`
- `aws_s3_bucket.cedars` (`user-cedars-v2-storage`), versioning on, SSE (aws:kms or SSE-S3), block all public access, TLS-only bucket policy.

### 5. `iam.tf` — task roles (least privilege)
- **Execution role**: ECR pull, CloudWatch Logs, read the injected secrets.
- **Backend/worker task role**:
  - `s3:GetObject/PutObject/DeleteObject/ListBucket` scoped to the CEDARS bucket only.
  - `bedrock:InvokeModel` + `bedrock:InvokeModelWithResponseStream` scoped to the Claude inference-profile ARNs used.
  - (No RDS/Redis IAM — those use SG + password.)

### 6. `ecs.tf`
- `aws_ecs_cluster.cedars_v2`.
- 3 task definitions (backend, worker, frontend) — Fargate, awsvpc.
  - Backend/worker start at 1 vCPU / 2 GB; **worker may need more** for NLP/spaCy + per-patient batching — size after load test.
- 3 `aws_ecs_service`. Backend + frontend register with ALB target groups. Worker has no LB.
- Secrets via `secrets` block (Aurora pw, `SECRET_KEY`); plain config via `environment`.
- `aws_security_group.backend`, `.worker`, `.frontend`.

### 7. `alb.tf` — internal ALB
- `aws_lb` internal, across private subnets.
- HTTPS:443 listener, **internal ACM cert** for the CEDARS internal hostname.
- Listener rules: `/api/*` + `/ws/*` → backend TG (WS/stickiness enabled); `/*` → frontend TG.
- Health checks: backend `GET /api/v1/health` (returns `{"status":"ok"}`), frontend `/`.

### 8. `dns.tf`
- Route53 record in the appropriate internal zone → ALB (e.g. `cedars.<internal-zone>`).

### 9. `observability.tf`
- CloudWatch log groups per service.
- (Optional) Prometheus: the app exposes `/metrics`; decide whether to scrape via an ECS Prometheus task or push to MSK's existing monitoring (the account uses Datadog per `hccp-datadog-*` buckets — consider the Datadog ECS integration instead of standing up Prometheus).

---

## Deployment Pipeline (CI/CD)

Aligns with CLAUDE.md roadmap item "AWS Deployment via CI/CD."

1. **Build** — GitHub Actions (or MSK CI): `docker build` backend + frontend.
2. **Push** — to the two new ECR repos, tagged with git SHA.
3. **Migrate** — run one-off ECS task `alembic upgrade head` against Aurora.
4. **Deploy** — update ECS services to new task-def revision; ECS rolling deploy (min 100% / max 200% for zero-downtime on backend/frontend).
5. **Smoke test** — hit `/api/v1/health` through the ALB.

First deployment can be manual (Terraform apply + `aws ecs update-service`) to validate before wiring full CI.

---

## Sequenced Execution Plan

**Phase 0 — Prereqs / confirmations (before writing IaC)**
- [ ] Confirm access to the account's Terraform state / IaC repo and module conventions.
- [ ] Confirm an internal ACM cert + hostname can be issued for CEDARS.
- [ ] Confirm `bedrock:InvokeModel` can be attached to a CEDARS task role (recon proved the *user* role works; task role is an IAM ask).
- [ ] Confirm litellm uses task-role creds for Bedrock (no static keys) — small spike.
- [ ] **Compliance check**: PHI → Bedrock permitted? (governance, not IAM.)

**Phase 1 — Core infra**
- [ ] ECR repos → build & push first images.
- [ ] Dedicated Aurora PG16 + Secrets Manager password.
- [ ] ElastiCache Redis (the gap).
- [ ] S3 bucket.
- [ ] IAM task/execution roles.

**Phase 2 — Compute + ingress**
- [ ] ECS cluster + 3 task defs + 3 services.
- [ ] Internal ALB + target groups + listener rules (WS enabled).
- [ ] Route53 internal record.
- [ ] Migration task → `alembic upgrade head`.

**Phase 3 — Config + hardening**
- [ ] All env/secrets wired (DB, Redis, S3=native, SECRET_KEY, COOKIE_SECURE, CORS, Bedrock).
- [ ] Smoke test through ALB: health, login, upload → S3, a pipeline run (NLP + Bedrock classify), worker executes job.
- [ ] Observability (logs + Datadog/Prometheus).

**Phase 4 — CI/CD**
- [ ] Automate build→push→migrate→deploy→smoke.

**Converge with SSO workstream** before opening to real users.

---

## Open Questions / Risks

1. **PHI → Bedrock governance** — is clinical text allowed to be sent to Bedrock in this account? IAM says yes; policy may say no. **Blocking if no.**
2. **Worker sizing** — NLP (spaCy) + per-patient batching memory footprint under real note volume is unknown. Load-test before fixing task size.
3. **spaCy model in image** — confirm `backend/Dockerfile` bakes in the required spaCy model, or set `CEDARS_SPACY_MODEL` and download at build (not runtime — no repeated egress).
4. **PINES** — deferred/optional in v2. Not deployed here. If needed later → SageMaker/Model Serving or a 4th ECS service with GPU.
5. **Migration strategy** — dedicated migration task vs. startup hook. Recommend dedicated task to avoid races across backend replicas.
6. **WebSocket through internal ALB** — supported, but confirm idle-timeout tuning for long pipeline progress streams.
7. **Redis HA** — single node is a SPOF for the queue. Decide single-node (cheaper) vs. replication group (HA) for production.

---

## Bottom Line

CEDARS v2 deploys cleanly as a **self-contained ECS Fargate stack in account `180294205688`**. Aurora PG16, ECS, ECR, and **working Bedrock** already exist in-account; the only net-new stateful piece is **ElastiCache Redis**. **App code changes are near-zero** — S3 and Bedrock are config-only. The real production blocker remains **SSO/ezGroups** (separate workstream), not this infrastructure.
