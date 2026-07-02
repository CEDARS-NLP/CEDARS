########################################################################
# IAM — ECS execution role and task role.
#
# MSK guardrail (see variables.tf): mskEngineerUser can self-create the
# EXECUTION role (userServiceRole- prefix + automation boundary) but NOT the
# Bedrock TASK role (needs bedrockServiceAccess- prefix + bedrock boundary,
# which the automation boundary does not permit — bedrock:InvokeModel is
# capped out). So by default:
#   create_execution_role = true   -> created here
#   create_task_role      = false  -> referenced by ARN (IAM admin provisions)
#
# ecs.tf consumes local.execution_role_arn / local.task_role_arn.
########################################################################

locals {
  execution_role_arn = var.create_execution_role ? aws_iam_role.execution[0].arn : var.execution_role_arn
  task_role_arn      = var.create_task_role ? aws_iam_role.task[0].arn : var.task_role_arn
}

data "aws_iam_policy_document" "ecs_assume" {
  statement {
    actions = ["sts:AssumeRole"]
    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }
  }
}

########################################################################
# Execution role (used by the ECS agent: ECR pull, logs, read secrets).
########################################################################

resource "aws_iam_role" "execution" {
  count                = var.create_execution_role ? 1 : 0
  name                 = "${var.execution_role_name_prefix}${local.prefix}-ecs-execution"
  assume_role_policy   = data.aws_iam_policy_document.ecs_assume.json
  permissions_boundary = var.execution_permissions_boundary_arn
}

resource "aws_iam_role_policy_attachment" "execution_managed" {
  count      = var.create_execution_role ? 1 : 0
  role       = aws_iam_role.execution[0].name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Read the secrets injected into task defs. Note the injected secrets are named
# `user-cedars-v2-*`, which the automation boundary permits (secret:user*).
data "aws_iam_policy_document" "execution_secrets" {
  count = var.create_execution_role ? 1 : 0
  statement {
    sid     = "ReadInjectedSecrets"
    actions = ["secretsmanager:GetSecretValue"]
    resources = [
      aws_secretsmanager_secret.db_url.arn,
      aws_secretsmanager_secret.app_secret_key.arn,
    ]
  }
}

resource "aws_iam_role_policy" "execution_secrets" {
  count  = var.create_execution_role ? 1 : 0
  name   = "${local.prefix}-execution-secrets"
  role   = aws_iam_role.execution[0].id
  policy = data.aws_iam_policy_document.execution_secrets[0].json
}

########################################################################
# Task role (app runtime: S3 + Bedrock). Created only with elevated IAM
# rights; otherwise referenced by ARN (default at MSK).
########################################################################

resource "aws_iam_role" "task" {
  count                = var.create_task_role ? 1 : 0
  name                 = "${var.task_role_name_prefix}${local.prefix}-task"
  assume_role_policy   = data.aws_iam_policy_document.ecs_assume.json
  permissions_boundary = var.task_permissions_boundary_arn
}

data "aws_iam_policy_document" "task" {
  count = var.create_task_role ? 1 : 0

  # S3 scoped to the CEDARS bucket only.
  statement {
    sid       = "S3Bucket"
    actions   = ["s3:ListBucket", "s3:GetBucketLocation"]
    resources = [aws_s3_bucket.storage.arn]
  }

  statement {
    sid       = "S3Objects"
    actions   = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"]
    resources = ["${aws_s3_bucket.storage.arn}/*"]
  }

  # KMS for the SSE-KMS bucket.
  statement {
    sid       = "KmsForS3"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey"]
    resources = ["*"]
    condition {
      test     = "StringEquals"
      variable = "kms:ViaService"
      values   = ["s3.${var.region}.amazonaws.com"]
    }
  }

  # Bedrock runtime invoke — inference profiles + underlying foundation models.
  statement {
    sid = "BedrockInvoke"
    actions = [
      "bedrock:InvokeModel",
      "bedrock:InvokeModelWithResponseStream",
    ]
    resources = concat(
      var.bedrock_inference_profile_arns,
      var.bedrock_foundation_model_arns,
    )
  }
}

resource "aws_iam_role_policy" "task" {
  count  = var.create_task_role ? 1 : 0
  name   = "${local.prefix}-task"
  role   = aws_iam_role.task[0].id
  policy = data.aws_iam_policy_document.task[0].json
}
