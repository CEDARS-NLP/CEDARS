---
name: aws-secretsmanager
description: Enforce MSK's standards for all AWS Secrets Manager secrets created, generated, reviewed, or refactored in Terraform.
---

This skill enforces MSK standards for **every Terraform `aws_secretsmanager_secret`** the copilot generates or validates, including secrets created directly or through modules.

## Scope
- Applies to any Terraform configuration that **creates or updates** Secrets Manager secrets (e.g., `resource "aws_secretsmanager_secret"`, or modules that create secrets).
- Does **not** apply to secrets managed outside of Terraform (e.g., secrets created via the AWS console or CLI without Terraform).

---

## Rule 1 — Secret Name Prefix (Mandatory)

### Requirement
All secrets **must** have a name that starts with `user-`.

### Enforcement
When generating or reviewing Terraform:
- Never output a secret name without the `user-` prefix.
- If a secret name is non-compliant, rewrite it to use the `user-` prefix.
- If asked to violate the standard, refuse and provide a compliant alternative.

### Terraform Implementation Notes
- Prefer explicit `name = "user-..."`.
- `name_prefix` is allowed only if it still guarantees the required prefix (e.g., `name_prefix = "user-..."`).
- When a secret name is derived from a variable or local, ensure the value passed includes the `user-` prefix (add a validation rule or prepend the prefix explicitly).

### Compliant Examples

**Basic secret:**
```hcl
resource "aws_secretsmanager_secret" "db_password" {
  name        = "user-db-password"
  description = "Database password for the application"
}
```

**Secret with name derived from a variable:**
```hcl
variable "secret_name" {
  description = "Name of the secret (without the user- prefix)"
  type        = string
}

resource "aws_secretsmanager_secret" "app_secret" {
  name        = "user-${var.secret_name}"
  description = "Application secret"
}
```

**Secret using name_prefix:**
```hcl
resource "aws_secretsmanager_secret" "api_key" {
  name_prefix = "user-api-key-"
  description = "API key for external service"
}
```

**Secret with rotation:**
```hcl
resource "aws_secretsmanager_secret" "rds_credentials" {
  name        = "user-rds-credentials"
  description = "RDS database credentials"

  rotation_rules {
    automatically_after_days = 30
  }
}
```

### Non-Compliant Examples (Never Generate)

```hcl
# ❌ Missing user- prefix
resource "aws_secretsmanager_secret" "bad" {
  name = "db-password"
}

# ❌ Missing user- prefix (uses a different prefix)
resource "aws_secretsmanager_secret" "bad" {
  name = "app/my-secret"
}

# ❌ name_prefix that does not start with user-
resource "aws_secretsmanager_secret" "bad" {
  name_prefix = "api-key-"
}

# ❌ Variable used without prepending user- prefix
variable "secret_name" {
  type = string
}

resource "aws_secretsmanager_secret" "bad" {
  name = var.secret_name   # Not guaranteed to start with user-
}
```

