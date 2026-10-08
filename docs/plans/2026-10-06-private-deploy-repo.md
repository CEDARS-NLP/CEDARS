# Move site deploy config to a private repo

**Date:** 2026-10-06
**Status:** Proposed. Nothing moved yet.
**Depends on:** the secret-scanning change (`.gitleaks.toml`, the pre-commit hook, `ci.yml` security lane). It takes the account ID, the Terraform Cloud organization and workspace, and the LLM VPN hosts out of the tracked files.

## Problem

`infra/cedars-v2/` is the Terraform for one site's ECS deployment, and this repo is public. The secret-scanning change removed the values that identify the site's AWS account and Terraform Cloud (TFC) workspace. Other site details are still in the files:

- `variables.tf` defaults: the VPC ID, the subnet IDs and their CIDRs, the IAM role-name prefixes, and the permissions-boundary policy names.
- `variables.tf` and `iam.tf` comments: the site's IAM guardrail (which principal may create which roles).
- `README.md`: the IAM roles handoff, the access-group name, and the deploy runbook as that site runs it.
- `terraform.tfvars.example`: the site's role names.
- `docs/plans/2026-06-30-aws-ecs-deployment-plan.md`: the account recon.

A config file can't keep these out of a public repo. They need to live in a private repo.

## Options

| | What moves | Effect |
|---|---|---|
| **A. Move `infra/cedars-v2/` wholesale** | Everything. This repo keeps only an example. | control-cedars stops working: it needs `infra/cedars-v2` to exist, and its parity stack and `infra validate` read it. Public users lose the reference stack. Two copies of the resources drift. |
| **B. Generic module here, site root in the private repo** (recommended) | The backend, the provider block, the site variables, the runbook and the IAM handoff. | The resource code stays in this repo and keeps its tests (`infra validate`, the parity stack). The private repo pins it by commit SHA. |
| **C. Keep it here and template every value** | Nothing. | Values leave the files, but the guardrail docs and runbook still describe one site's internals. Every new resource is another chance to leak. |

## Plan (option B)

### 1. This repo: make `infra/cedars-v2/` a module

The resource files (`alb`, `ecr`, `ecs`, `elasticache`, `iam`, `rds`, `s3`, `secrets`, `security_groups`, `main`, `outputs`) stay as they are. Their resource addresses must not change.

- `versions.tf`: keep `required_version` and `required_providers`, and drop `cloud {}`. A module doesn't pick its backend.
- `providers.tf`: move it to the example root (step 2). With no provider block in the module, a caller can use `count` or `for_each` on it later. `allowed_account_ids` and `default_tags` are provider settings, so they move with it.
- `variables.tf`: strip the site defaults.
  - `vpc_id` and `private_subnet_ids` become required (no default).
  - The role-name prefixes default to something neutral (derived from `name_prefix`).
  - The permissions boundaries default to `null`, meaning no boundary. A site whose IAM rules require one sets it.
  - Rewrite the IAM comments as general guidance: some accounts only let you create roles under a fixed prefix and boundary, and those accounts should set the variables.
- `iam.tf`: the boundary defaults built from the account ID become "use the variable if it's set, otherwise attach no boundary".
- `README.md`: generic. Explain what the stack creates, list the inputs, and give a placeholder runbook that uses `terraform output` for every URL and ID. Drop the IAM handoff, the access group and the site's guardrail story.
- `terraform.tfvars.example`: only placeholders (`123456789012`, `vpc-0123456789abcdef0`, `subnet-0123456789abcdef0`, `example.com`).

### 2. This repo: add `infra/cedars-v2/examples/basic/`

This is a deployable root that shows how to call the module:

```hcl
terraform {
  # Pick a backend. For Terraform Cloud: cloud {} plus TF_CLOUD_ORGANIZATION
  # and TF_WORKSPACE in the environment.
}

provider "aws" {
  region              = var.region
  allowed_account_ids = var.allowed_account_ids
  default_tags { tags = { Project = "cedars-v2", ManagedBy = "terraform" } }
}

module "cedars" {
  source             = "../.."
  region             = var.region
  vpc_id             = var.vpc_id
  private_subnet_ids = var.private_subnet_ids
  # ...
}
```

It also gets a `terraform.tfvars.example` of placeholders.

### 3. The private deploy repo

- `main.tf`: the same shape as the example. The module source is pinned by SHA, for example `git::https://github.com/CEDARS-NLP/CEDARS.git//infra/cedars-v2?ref=<sha>`. Upgrading the stack becomes a reviewed bump of that ref.
- `versions.tf`: `cloud {}` with the real organization and workspace. That is fine in a private repo.
- `site.auto.tfvars`: the VPC, the subnets, the role prefixes, the boundary ARNs and the task role ARN. Secrets stay as TFC workspace variables.
- `moved.tf`: one `moved {}` block per resource (52 today), for example `from = aws_ecs_service.backend` to `module.cedars.aws_ecs_service.backend`. Generate it from `terraform state list` rather than by hand. A `moved` block on a counted resource carries all of its instances.
- `README.md`: the site runbook, the IAM handoff and the account recon, moved from this repo.
- Deployment templates for other services at the same site go here too. One open branch adds CloudFormation templates with site values; move them before that PR merges.
- The same gitleaks hook and CI job, so it can't leak credentials either.

### 4. Cut over without touching resources

1. **Baseline.** On the current config, run `terraform plan`. It must show no changes. If it doesn't, settle that drift first, so it can't hide inside the refactor.
2. Merge steps 1 and 2 here. `control-cedars infra validate` must pass on the module and on `examples/basic`.
3. In the private repo, pin the module to that merge SHA and run `terraform plan` against the same workspace.
4. **The gate:** every resource is listed as "has moved to `module.cedars.…`", and the summary reads `0 to add, 0 to change, 0 to destroy`. Any add, change or destroy means a site default didn't make it into `site.auto.tfvars`. Fix the tfvars, not the module, and plan again.
   - A dropped permissions boundary or role prefix shows up as an IAM change or replacement.
   - A dropped subnet list shows up as ECS, RDS or ALB replacement. Aurora replacement would destroy the database, though `db_deletion_protection` should block that.
5. Apply. This run only rewrites state addresses.
6. Plan again. It must show no changes.
7. Point the TFC workspace at the private repo. Today the workspace is CLI-driven, so this only means running from the private repo; check its "Terraform Working Directory" setting. If it has been switched to VCS-driven, change its repository instead.
8. Remove the site files from this repo: the old runbook text, and the account recon in `docs/plans/2026-06-30-aws-ecs-deployment-plan.md` (keep the architecture reasoning as a generic note).
9. Keep the `moved` blocks for one release, then delete them.

**Rollback:** until step 5, nothing has changed. After it, revert the private root to the pre-move state addresses (inverse `moved` blocks), or run `terraform state` operations from the TFC state version history. Neither touches AWS resources.

### 5. Afterwards

- Add gitleaks rules for VPC, subnet and security-group IDs (`vpc-`, `subnet-`, `sg-` followed by 8 or 17 hex characters). Once the module is clean they will only fire on new leaks.
- Optional: a CI job that runs `terraform fmt -check` and `validate` on the module and the example.

## Effects on the verify skills (changes need approval)

- `control-cedars infra validate` copies `infra/cedars-v2` and validates it. It still works on the module. It should also validate `examples/basic`.
- `parity check` reads `region`, `enable_https` and `app_hostname` defaults from `variables.tf`. Those keep their defaults.
- The feature map's `ops-infra-terraform` and `ops-deploy-runbook` rows cite `infra/cedars-v2/README.md` line ranges. The runbook moves to the private repo, so the row has to say where the site runbook lives without naming site internals.
- `aws status` and `deploy rehearse --from aws` default to a site AWS profile. That default could come from an environment variable.
