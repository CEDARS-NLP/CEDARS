---
name: aws-tags
description: Enforce MSK's mandatory tagging requirements for all AWS resources managed by Terraform. Use this when generating Terraform provider configuration, creating resources, or validating existing infrastructure.
---

## Tagging Requirements

### Core Rules
1. **All AWS resources MUST include tags** using `default_tags` in the provider block
2. **`env` MUST be a variable** — all other tag values may be hardcoded strings, but `env` must always reference a variable so it can be toggled per deployment
3. **Validate compliance** before generating or accepting any resource configuration

### Required Tags

| Tag | Description | Allowed Values / Format | Examples |
|-----|-------------|------------------------|---------|
| `application` | Application name. All lowercase, separated by hyphens (`-`). Final format determined by CMDB initiative. | Lowercase string, hyphen-separated | `telemedicine`, `mymsk-web`, `patient-self-scheduling`, `portal-secure-messaging` |
| `application-id` | Unique Application ID. Determined by CMDB initiative & updated in APM Table. | APM identifier (`APM` followed by digits) | `APM0001163`, `APM0002015`, `APM0002265` |
| `application-tier` | Application tier for reporting and NOC response. Determined by CMDB initiative & updated in APM Table. | `tier-0`, `tier-0-prime`, `tier-1`, `tier-1-prime`, `tier-2`, `tier-3`, `tier-4`, `hygiene-lite` | `tier-1`, `tier-2` |
| `cost-center` | Official MSK cost center code belonging to the resource owner. | Numeric cost center code | `12345` |
| `env` | Application environment. All lowercase, no symbols (no hyphens). Suggested values for application teams. For Hybrid Cloud Platform use `alpha` or `main`. | `dev`, `test`, `preprod`, `prod` (suggested); `alpha`, `main` (Hybrid Cloud Platform); other lowercase values accepted | `dev`, `prod`, `preprod` |
| `owner-email` | Owner (team or individual) of the resource. | Valid email address | `zzPDL_DigITs_Telemed_All@mskcc.org`, `zzPDL_MIS_PP_DBA@mskcc.org` |
| `service-id` | ServiceNow service catalog ID for the application. Determined by CMDB initiative & updated in APM Table. | `SNSVC` followed by digits | `SNSVC0006195`, `SNSVC0001234` |

> **Tip:** If you're unsure of the correct value for any tag, check AWS Parameter Store — the Hybrid Cloud team publishes these values there.

### Implementation Pattern

**Provider Configuration (provider.tf):**
```hcl
provider "aws" {
  region = var.aws_region
  
  default_tags {
    tags = {
      application      = "my-service"
      application-id   = "APM0001163"
      application-tier = "tier-1"
      cost-center      = "12345"
      env              = var.environment
      owner-email      = "zzPDL_MyTeam@mskcc.org"
      service-id       = "SNSVC0000000"
    }
  }
}
```

**Variable Definitions (variables.tf):**
```hcl
variable "environment" {
  description = "Application environment (e.g., dev, test, preprod, prod). All lowercase, no symbols."
  type        = string
}
```

### Enforcement Rules

1. **Always use `default_tags`** in the provider block — do not add the same tags individually on each resource.
2. **`env` MUST be a variable** — never hardcode `env`; it must reference a `var.*` variable so it can be toggled per deployment. All other tag values may be hardcoded strings.
3. **`application` format**: all lowercase, hyphen-separated (e.g., `my-service`, `patient-self-scheduling`).
4. **`application-id` format**: must follow the `APM` + digits pattern (e.g., `APM0001163`).
5. **`application-tier`** must be one of the defined tier values — reject any other value.
6. **`env` format**: all lowercase, no symbols or hyphens (e.g., `dev`, `preprod`). Common values are `dev`, `test`, `preprod`, `prod`; Hybrid Cloud Platform uses `alpha` or `main`.
7. **`service-id` format**: must follow the `SNSVC` + digits pattern (e.g., `SNSVC0000000`).
8. **All seven required tags are mandatory** — refuse to generate or accept a provider block that is missing any of them.
9. **When reviewing existing Terraform**, add any missing required tags and ensure `env` uses a variable (convert it if hardcoded). Other tags may remain hardcoded.

### Non-Compliant Example (Never Generate)

```hcl
# ❌ env is hardcoded and missing required tags
provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      application = "my-app"
      env         = "prod"         # ❌ env must be a variable, not a hardcoded string
      # application-id, application-tier, cost-center, owner-email, service-id are missing
    }
  }
}
```

## Further Reading

For the full official MSK resource tagging standards, refer to:
- [AWS Resource Tagging User Guide](https://github.com/MSKCC-Internal/DIGITS-DevPlatDocumentation/blob/main/products/CloudDocs/user-docs/aws/resource-tagging.md)
- [Global Resource Tagging Strategy](https://github.com/MSKCC-Internal/DIGITS-DevPlatDocumentation/blob/main/products/CloudDocs/cloud-design/global-strategy/resource-tagging-strategy.md)
