# CEDARS v2 — AWS ECS Terraform

Self-contained ECS Fargate stack for CEDARS v2 in account **180294205688**
(`research-us-east-1` VPC), region `us-east-1`. Separate from
`clinical-trials-research`; shares only VPC + Bedrock + the ECR registry.

**State & auth:** managed by **Terraform Cloud** (org `mskcc`, workspace
`APM0004784-aws-research-us-east-1-ctdatahubpoc` — a research-account workspace
repurposed for CEDARS testing). AWS auth is the workspace's **dynamic OIDC**
credentials — no static keys, no `AWS_PROFILE`. See "Deploy via Terraform Cloud".

Design doc: `../../docs/plans/2026-06-30-aws-ecs-deployment-plan.md`

## What this creates

| File | Resources |
|------|-----------|
| `ecr.tf` | `cedars-v2-<env>-backend`, `-frontend` repos (keep last 10) |
| `security_groups.tf` | ALB, backend, worker, frontend, aurora, redis SGs |
| `rds.tf` | Aurora PostgreSQL 16 (writer + optional reader), password + full DATABASE_URL secrets |
| `elasticache.tf` | Redis 7 replication group (ARQ queue) — the one net-new stateful piece |
| `s3.tf` | Object-storage bucket (versioned, SSE-KMS, TLS-only, no public access) |
| `iam.tf` / `secrets.tf` | ECS execution + task roles; SECRET_KEY secret |
| `alb.tf` | Internal ALB, HTTPS listener, path routing (`/api`,`/ws`→backend; `/`→frontend), optional Route53 record |
| `ecs.tf` | Cluster, backend/worker/frontend services, one-off migrate task def, log groups |

Three services from **two images**: the backend image runs both `backend`
(uvicorn) and `worker` (arq) via different commands.

## App config mapping (why almost no code changes)

- **S3**: `CEDARS_S3_ENDPOINT`/access keys set empty → `app/common/s3.py` uses
  native AWS S3 via the ECS **task role**. Config-only.
- **Bedrock**: task role has `bedrock:InvokeModel`; litellm uses `provider: bedrock`.
- **DB/Redis/secret**: injected as env/secrets from Aurora, ElastiCache, Secrets Manager.

## TLS: spike vs. production

Controlled by `enable_https` (default **false**).

- **Spike (`enable_https = false`)** — ALB serves plain **HTTP on :80**, no domain
  or cert required. Reach the app at `http://$(terraform output -raw alb_dns_name)`
  from inside the VPC (bastion / VPN / another in-VPC host). The stack sets
  `CEDARS_COOKIE_SECURE=false` automatically so login works over HTTP.
- **Production (`enable_https = true`)** — ALB serves **HTTPS on :443**; requires
  `alb_certificate_arn` (+ `app_hostname`). See "Generating the certificate" below.
  Cookies become Secure automatically.

## Prerequisites (Phase 0)

1. **Terraform Cloud access** — membership in `GRP_MIS_TERRAFORM_Users`, an
   invite accepted to the `mskcc` org, and MSK VPN. State/auth are handled by TFC
   (`cloud {}` block in `versions.tf`) — no S3 backend, no static AWS creds.
2. **IAM task role** — pre-create the Bedrock task role via the TFC workspace's
   OIDC role (if it holds `iam:CreateRole` for the `bedrockServiceAccess-` prefix,
   set `create_task_role = true`), otherwise have an IAM admin create it and set
   `task_role_arn`. See "IAM roles handoff".
3. **Governance**: confirm PHI/clinical text may be sent to Bedrock (policy, not IAM).
4. **(Production only)** ACM cert for `app_hostname` — none exists in-account yet.

> **Note on the OIDC role's IAM rights.** The `mskEngineerUser` guardrail
> (below) applies to *interactive* users. The TFC workspace assumes its own OIDC
> role, which may have broader `iam:CreateRole` scope. If it can create the
> `bedrockServiceAccess-` role, flip `create_task_role = true` and skip the admin
> handoff entirely. Confirm in a `plan` before assuming.

## IAM roles handoff

MSK's `iam:CreateRole` guardrail (verified 2026-07-01) allows `mskEngineerUser`
to create a role **only** with prefix `userServiceRole-` AND the
`AutomationOrUserServiceRolePermissions` permissions boundary. That boundary
permits `ecr:*`, `ecs:*`, `s3:*`, `secretsmanager:*` on `user-*` secrets,
`logs:*` — but for Bedrock only `bedrock-agentcore:InvokeAgent*`, **not**
`bedrock:InvokeModel`. A boundary is a hard ceiling.

Consequence, split by role:

| Role | Provisioned by | How |
|------|---------------|-----|
| **Execution** (ECR pull, logs, read `user-cedars-v2-*` secrets) | **this module** | `create_execution_role = true` (default) — self-service |
| **Task** (S3 to CEDARS bucket + `bedrock:InvokeModel`) | **IAM admin / automation** | pre-created; set `task_role_arn` |

**Ask the IAM admin to create the task role** (mirrors the existing
`bedrockServiceAccess-clinical-trials-research-backend-task`):
- **Name**: `bedrockServiceAccess-cedars-v2-<env>-task`
- **Permissions boundary**: `hccp-automation-bedrock-permission-boundary`
- **Trust**: `ecs-tasks.amazonaws.com` (`sts:AssumeRole`)
- **Inline policy**:
  - `s3:ListBucket`,`s3:GetBucketLocation` on `arn:aws:s3:::user-cedars-v2-<env>-storage`
  - `s3:GetObject`,`s3:PutObject`,`s3:DeleteObject` on `.../*`
  - `kms:Decrypt`,`kms:GenerateDataKey` (via `s3.us-east-1.amazonaws.com`)
  - `bedrock:InvokeModel`,`bedrock:InvokeModelWithResponseStream` on the Anthropic
    inference-profile + foundation-model ARNs

(If you later get elevated IAM rights, set `create_task_role = true` and the module
builds this exact policy itself — see `iam.tf`.)

## Generating the certificate (production only)

The app is internal-only (no public DNS), so **public ACM DNS-validation does not
apply**. Two paths, decided by MSK cloud/security:
- **ACM Private CA** — if MSK has one in/shared to this account, request an
  `aws_acm_certificate` from it (auto-renews). Clients must trust the private root.
- **Import from MSK corporate PKI** — get cert+key+chain from the PKI team and
  `aws acm import-certificate ...`; set the returned ARN as `alb_certificate_arn`.
  Imported certs do not auto-renew.

Not needed at all while `enable_https = false`.

## Deploy via Terraform Cloud

Auth is TFC + dynamic OIDC — **no `AWS_PROFILE`**. On MSK VPN, `terraform login`
once (or drop a token in `~/.terraformrc`); the AWS creds come from the workspace.

Set non-default inputs as **workspace variables** in the TFC UI (Terraform
variables), not a local `terraform.tfvars` — that's the TFC-native way and keeps
secrets/toggles with the workspace. Relevant ones: `create_task_role` or
`task_role_arn`, and (production only) `enable_https` + `alb_certificate_arn` +
`app_hostname`. Sensible defaults (VPC, subnets, region, account guard) are baked
into the code for this account.

```bash
cd infra/cedars-v2
terraform login            # one-time, stores TFC token (VPN required)
terraform init             # connects to the mskcc workspace, pulls remote state
terraform plan             # runs remotely in TFC; review the plan
terraform apply            # stands up ECR, Aurora, Redis, S3, exec role, ALB, ECS
```

(You can also run `plan`/`apply` from the TFC web UI — the CLI just queues remote
runs. Image tags below can be set as workspace vars instead of `-var`.)

```bash
# 1. Build & push images to the new ECR repos (URLs come from `terraform output`)
aws ecr get-login-password --region us-east-1 \
  | docker login --username AWS --password-stdin 180294205688.dkr.ecr.us-east-1.amazonaws.com
docker build -t <backend_repo_url>:<sha> ../../backend  && docker push <backend_repo_url>:<sha>
docker build -t <frontend_repo_url>:<sha> ../../frontend && docker push <frontend_repo_url>:<sha>

# 2. Set backend_image_tag / frontend_image_tag (workspace vars or -var) and re-apply
terraform apply -var backend_image_tag=<sha> -var frontend_image_tag=<sha>

# 3. Run DB migrations (one-off task) BEFORE the backend serves traffic.
#    Needs AWS creds locally, so run from a machine with a same-account profile:
aws ecs run-task \
  --cluster $(terraform output -raw ecs_cluster_name) \
  --task-definition $(terraform output -raw migrate_task_definition) \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[<private-subnets>],securityGroups=[<worker-sg>],assignPublicIp=DISABLED}"

# 4. Smoke test through the ALB (from inside the VPC)
#    Spike (HTTP):  curl http://$(terraform output -raw alb_dns_name)/api/v1/health
#    Production:    curl https://<app_hostname>/api/v1/health
# Expect: {"status":"ok","version":"2.0.0"}
```

## Notes & decisions

- **Aurora Serverless v2** by default (`db.serverless`, 0.5–4 ACU). Switch to a
  provisioned class via `db_instance_class` if preferred.
- **Redis** is single-node by default (cheaper). Set `redis_ha_enabled=true` for a
  replica + failover to remove the queue SPOF in production.
- **Deletion protection** is ON for Aurora and the S3 bucket is `force_destroy=false`.
- **Migrations** run as a dedicated one-off task, not a startup hook, to avoid
  races across the 2 backend replicas.
- **Frontend nginx** `proxy_pass` blocks are inert here — the ALB routes `/api`
  and `/ws` to the backend before they reach the frontend container.
- **WebSockets**: ALB `idle_timeout=300` + target-group stickiness support the
  pipeline/eval progress streams. Tune if streams run longer.
- **Transit encryption on Redis is OFF** — enabling requires `rediss://` + ARQ TLS
  config in the app. Revisit if policy requires in-VPC transit encryption.

## Not included (by design)

- **SSO/ezGroups** — the real production blocker; separate app-side workstream.
- **PINES** — deferred/optional in v2; would be SageMaker/Model Serving or a GPU
  ECS service later.
- **Observability** — account uses Datadog (`hccp-datadog-*`); wire the Datadog
  ECS integration or scrape the app's `/metrics`. Container Insights is enabled.
