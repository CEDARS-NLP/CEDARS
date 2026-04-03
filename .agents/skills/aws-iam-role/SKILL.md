---
name: aws-iam-role
description: Enforce MSK IAM role naming conventions and mandatory permissions boundary requirements for all AWS IAM roles created, generated, reviewed, or refactored in Terraform.
---

This skill enforces MSK standards for **every Terraform `aws_iam_role`** the copilot generates or validates, including roles created directly or through modules.

## Scope
- Applies to any Terraform configuration that **creates or updates** IAM roles (e.g., `resource "aws_iam_role"`, or modules that create IAM roles).
- Does **not** apply to AWS-managed **service-linked roles** (which are not created with `aws_iam_role` and have AWS-controlled naming/boundaries).
- “Custom IAM role” in this skill means: any role created via Terraform `aws_iam_role`.

## Bedrock vs Non-Bedrock Classification (Deterministic)
Treat a role as **Bedrock-related** if **any** of the following are true:
1. The assume-role trust policy principal includes the service: `bedrock.amazonaws.com`, OR
2. The role name contains `bedrock` (case-insensitive), OR
3. Any attached/inline policy contains actions that start with `bedrock:`.

Otherwise, treat it as **non-Bedrock**.

## IAM Role Naming Requirements
### 1) Prefix Rules (Mandatory)
- **Non-Bedrock roles** must start with: `userServiceRole-`
- **Bedrock roles** must start with: `bedrockServiceAccess-`

### 2) Enforcement
When generating or reviewing Terraform:
- Never output an IAM role name without the required prefix.
- If a role name is non-compliant, rewrite it to use the correct prefix.
- If asked to violate the standard, refuse and provide a compliant alternative.

### 3) Terraform Implementation Notes
- Prefer explicit `name = "..."`
- `name_prefix` is allowed only if it still guarantees the required prefix (e.g., `name_prefix = "userServiceRole-..."`).

## Permissions Boundary Requirements
### 1) Mandatory Boundaries
- Every Terraform `aws_iam_role` **must** set `permissions_boundary`.
- Refuse to generate an IAM role missing `permissions_boundary`.
- If reviewing existing Terraform, add or correct `permissions_boundary` to be compliant.

### 2) Correct Boundary by Role Type (Mandatory)
- **Non-Bedrock roles** must use:
  `arn:aws:iam::{AccountNumber}:policy/AutomationOrUserServiceRolePermissions`
- **Bedrock roles** must use:
  `arn:aws:iam::{AccountNumber}:policy/hccp-automation-bedrock-permission-boundary`

### 3) Account Number Retrieval (Required)
Always obtain the account number using Terraform:
```hcl
data "aws_caller_identity" "current" {}
# Reference: data.aws_caller_identity.current.account_id
```

Use `data.aws_caller_identity.current.account_id` in the `permissions_boundary` ARN (substituting `{AccountNumber}` in the patterns above).

## Compliant Examples

**Non-Bedrock role (e.g., Lambda execution role):**
```hcl
data "aws_caller_identity" "current" {}

resource "aws_iam_role" "example" {
  name = "userServiceRole-my-service"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
    }]
  })

  permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/AutomationOrUserServiceRolePermissions"
}
```

**Bedrock role:**
```hcl
data "aws_caller_identity" "current" {}

resource "aws_iam_role" "bedrock_agent" {
  name = "bedrockServiceAccess-my-agent"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "bedrock.amazonaws.com" }
    }]
  })

  permissions_boundary = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:policy/hccp-automation-bedrock-permission-boundary"
}
```

## Non-Compliant Examples (Never Generate)

```hcl
# ❌ Missing prefix
resource "aws_iam_role" "bad" {
  name = "my-lambda-role"
  # ...
}

# ❌ Missing permissions_boundary
resource "aws_iam_role" "bad" {
  name = "userServiceRole-my-service"
  # permissions_boundary is absent — not allowed
}

# ❌ Wrong boundary for Bedrock role
resource "aws_iam_role" "bad_bedrock" {
  name                 = "bedrockServiceAccess-my-agent"
  permissions_boundary = "arn:aws:iam::123456789012:policy/AutomationOrUserServiceRolePermissions"
  # Should use hccp-automation-bedrock-permission-boundary for Bedrock roles
}
```
