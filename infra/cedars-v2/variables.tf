############################
# Core / account
############################

variable "region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "allowed_account_ids" {
  description = "Account IDs Terraform is permitted to apply to. Verified target: 180294205688 (profile saml)."
  type        = list(string)
  default     = ["180294205688"]
}

variable "environment" {
  description = "Deployment environment name"
  type        = string
  default     = "dev"
}

variable "name_prefix" {
  description = "Prefix for all resource names"
  type        = string
  default     = "cedars-v2"
}

############################
# Networking (verified via recon 2026-06-30)
############################

variable "vpc_id" {
  description = "VPC to deploy into (shared account primitive)"
  type        = string
  default     = "vpc-0429430969d2ccc0a"
}

variable "private_subnet_ids" {
  description = "Private subnets for ECS tasks, Aurora, Redis, and the internal ALB. All 4 subnets in the VPC are private."
  type        = list(string)
  default = [
    "subnet-05b3174a08b2b04cd", # us-east-1a  10.7.43.0/26
    "subnet-03bbe260b752010b2", # us-east-1f  10.7.43.64/26
    "subnet-0fc0e8216ec3a9b3d", # us-east-1c  10.7.43.128/26
    "subnet-02998fff64ddfd2bc", # us-east-1d  10.7.43.192/26
  ]
}

############################
# Ingress / DNS / TLS
############################

variable "alb_ingress_cidrs" {
  description = "CIDRs allowed to reach the ALB. Empty = VPC CIDR only (default, most restrictive). The ALB is internal, so 0.0.0.0/0 only admits sources that can already route to the private ALB IPs (in-VPC + VPN). Use [\"0.0.0.0/0\"] for a spike when VPN clients aren't in the VPC CIDR."
  type        = list(string)
  default     = []
}

variable "enable_https" {
  description = "Serve the ALB over HTTPS:443 (requires alb_certificate_arn). When false, the ALB serves plain HTTP:80 and no cert is needed — use this for a spike, reached via the ALB's AWS-generated DNS name."
  type        = bool
  default     = false
}

variable "alb_certificate_arn" {
  description = "ACM certificate ARN for the internal ALB HTTPS listener. Required only when enable_https = true. None exists in-account yet."
  type        = string
  default     = ""
}

variable "app_hostname" {
  description = "Internal hostname CEDARS is served at (e.g. cedars.example.internal). Used for CORS and DNS."
  type        = string
  default     = ""
}

variable "route53_zone_id" {
  description = "Route53 private hosted zone ID to create the CEDARS A/ALIAS record in. Leave blank to skip DNS record creation."
  type        = string
  default     = ""
}

############################
# Images
############################

variable "backend_image_tag" {
  description = "Image tag (git SHA) for the backend/worker image in ECR"
  type        = string
  default     = "latest"
}

variable "frontend_image_tag" {
  description = "Image tag (git SHA) for the frontend image in ECR"
  type        = string
  default     = "latest"
}

############################
# Aurora PostgreSQL
############################

variable "db_name" {
  description = "Initial database name"
  type        = string
  default     = "cedars"
}

variable "db_master_username" {
  description = "Aurora master username"
  type        = string
  default     = "cedars"
}

variable "db_engine_version" {
  description = "Aurora PostgreSQL engine version (matches in-account 16.11)"
  type        = string
  default     = "16.11"
}

variable "db_instance_class" {
  description = "Aurora instance class"
  type        = string
  default     = "db.serverless"
}

variable "db_serverless_min_acu" {
  description = "Aurora Serverless v2 minimum ACUs (used when db_instance_class = db.serverless)"
  type        = number
  default     = 0.5
}

variable "db_serverless_max_acu" {
  description = "Aurora Serverless v2 maximum ACUs (used when db_instance_class = db.serverless)"
  type        = number
  default     = 4
}

variable "db_reader_enabled" {
  description = "Create a reader instance for HA"
  type        = bool
  default     = true
}

variable "db_deletion_protection" {
  description = "Aurora deletion protection. Keep true in production; override to false to allow teardown."
  type        = bool
  default     = true
}

variable "db_skip_final_snapshot" {
  description = "Skip the final snapshot on Aurora deletion. Keep false in production; override to true for a clean teardown of an empty cluster."
  type        = bool
  default     = false
}

############################
# ElastiCache Redis (the net-new gap)
############################

variable "redis_engine_version" {
  description = "Redis engine version"
  type        = string
  default     = "7.1"
}

variable "redis_node_type" {
  description = "ElastiCache node type"
  type        = string
  default     = "cache.t4g.small"
}

variable "redis_ha_enabled" {
  description = "Enable a replica for HA (removes queue SPOF). Single-node is cheaper."
  type        = bool
  default     = false
}

############################
# ECS sizing
############################

variable "backend_cpu" {
  description = "Backend task CPU units"
  type        = number
  default     = 1024
}

variable "backend_memory" {
  description = "Backend task memory (MiB)"
  type        = number
  default     = 2048
}

variable "backend_desired_count" {
  description = "Backend service desired task count (>=2 for HA)"
  type        = number
  default     = 2
}

variable "worker_cpu" {
  description = "Worker task CPU units. NLP/spaCy + per-patient batching may need more; size after load test."
  type        = number
  default     = 2048
}

variable "worker_memory" {
  description = "Worker task memory (MiB)"
  type        = number
  default     = 4096
}

variable "worker_desired_count" {
  description = "Worker service desired task count"
  type        = number
  default     = 1
}

variable "frontend_cpu" {
  description = "Frontend task CPU units"
  type        = number
  default     = 256
}

variable "frontend_memory" {
  description = "Frontend task memory (MiB)"
  type        = number
  default     = 512
}

variable "frontend_desired_count" {
  description = "Frontend service desired task count (>=2 for HA)"
  type        = number
  default     = 2
}

############################
# Application config
############################

variable "bedrock_inference_profile_arns" {
  description = "Bedrock inference-profile ARNs the task role may invoke. Defaults to all Anthropic profiles in the region; scope down for least privilege."
  type        = list(string)
  default     = ["arn:aws:bedrock:us-east-1:180294205688:inference-profile/*"]
}

variable "bedrock_foundation_model_arns" {
  description = "Bedrock foundation-model ARNs referenced by inference profiles (cross-region invoke needs the underlying model ARNs too)."
  type        = list(string)
  default     = ["arn:aws:bedrock:*::foundation-model/anthropic.*"]
}

variable "log_retention_days" {
  description = "CloudWatch log retention"
  type        = number
  default     = 30
}

############################
# IAM
#
# mskEngineerUser cannot create IAM roles (iam:CreateRole is denied). At MSK,
# roles are provisioned out-of-band with fixed prefixes (`userServiceRole-*`
# for execution, `bedrockServiceAccess-*` for Bedrock-enabled task roles) and
# referenced by ARN. Keep create_iam_roles = false and supply the ARNs.
#
# Set create_iam_roles = true only in an account where you hold iam:CreateRole
# (then the module creates least-privilege roles itself).
############################

# --- MSK iam:CreateRole guardrail (verified in-account 2026-07-01) ---
# mskEngineerUser CAN create a role only with prefix `userServiceRole-` AND the
# `AutomationOrUserServiceRolePermissions` boundary. That boundary allows
# ecr:*, ecs:*, s3:* (Get/List/Put/Delete), secretsmanager:* on user-* secrets,
# logs:* — but for Bedrock only `bedrock-agentcore:InvokeAgent*`, NOT
# `bedrock:InvokeModel`. A boundary is a hard ceiling, so the Bedrock task role
# MUST use the `bedrockServiceAccess-` prefix + `hccp-automation-bedrock-*`
# boundary, which mskEngineerUser is NOT allowed to create — an IAM-admin task.
#
# Therefore: create the EXECUTION role here (self-service), REFERENCE a
# pre-created TASK role by ARN (IAM admin / automation provisions it).

# ---- Execution role ----
variable "create_execution_role" {
  description = "Create the ECS execution role here. True works for mskEngineerUser (userServiceRole- prefix + automation boundary)."
  type        = bool
  default     = true
}

variable "execution_role_name_prefix" {
  description = "Required name prefix for a self-created execution role at MSK."
  type        = string
  default     = "userServiceRole-"
}

variable "execution_permissions_boundary_arn" {
  description = "Permissions boundary required on a self-created execution role at MSK."
  type        = string
  default     = "arn:aws:iam::180294205688:policy/AutomationOrUserServiceRolePermissions"
}

variable "execution_role_arn" {
  description = "Pre-created ECS execution role ARN. Used when create_execution_role = false."
  type        = string
  default     = ""
}

# ---- Task role (Bedrock) ----
variable "create_task_role" {
  description = "Create the Bedrock task role here. mskEngineerUser CANNOT (needs bedrockServiceAccess- prefix + bedrock boundary). Keep false and supply task_role_arn; set true only with elevated IAM rights."
  type        = bool
  default     = false
}

variable "task_role_name_prefix" {
  description = "Required name prefix for a self-created Bedrock task role at MSK."
  type        = string
  default     = "bedrockServiceAccess-"
}

variable "task_permissions_boundary_arn" {
  description = "Permissions boundary for a self-created Bedrock task role at MSK."
  type        = string
  default     = "arn:aws:iam::180294205688:policy/hccp-automation-bedrock-permission-boundary"
}

variable "task_role_arn" {
  description = "Pre-created Bedrock task role ARN (scoped to CEDARS bucket + bedrock:InvokeModel). Required when create_task_role = false."
  type        = string
  default     = ""
}
