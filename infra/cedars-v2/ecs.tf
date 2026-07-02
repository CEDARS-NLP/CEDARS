########################################################################
# ECS cluster + task definitions + services.
#   backend  : uvicorn (from backend image), behind ALB /api,/ws
#   worker   : arq (same backend image, different command), no ingress
#   frontend : nginx static (frontend image), behind ALB /
########################################################################

resource "aws_ecs_cluster" "main" {
  name = local.prefix

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---- Log groups ----
resource "aws_cloudwatch_log_group" "backend" {
  name              = "/ecs/${local.prefix}/backend"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "worker" {
  name              = "/ecs/${local.prefix}/worker"
  retention_in_days = var.log_retention_days
}

resource "aws_cloudwatch_log_group" "frontend" {
  name              = "/ecs/${local.prefix}/frontend"
  retention_in_days = var.log_retention_days
}

locals {
  backend_image  = "${aws_ecr_repository.backend.repository_url}:${var.backend_image_tag}"
  frontend_image = "${aws_ecr_repository.frontend.repository_url}:${var.frontend_image_tag}"

  # Non-secret environment shared by backend + worker.
  app_environment = [
    { name = "CEDARS_REDIS_URL", value = local.redis_url },
    { name = "CEDARS_S3_ENDPOINT", value = "" },   # empty => native AWS S3
    { name = "CEDARS_S3_ACCESS_KEY", value = "" }, # empty => task role creds
    { name = "CEDARS_S3_SECRET_KEY", value = "" },
    { name = "CEDARS_S3_REGION", value = var.region },
    { name = "CEDARS_S3_BUCKET", value = aws_s3_bucket.storage.bucket },
    { name = "CEDARS_COOKIE_SECURE", value = local.cookie_secure },
    { name = "CEDARS_CORS_ORIGINS", value = local.cors_origins },
    { name = "CEDARS_ALLOW_CLOUD_LLM", value = "true" },
  ]

  # Secrets injected from Secrets Manager (full-value secrets).
  app_secrets = [
    { name = "CEDARS_DATABASE_URL", valueFrom = aws_secretsmanager_secret.db_url.arn },
    { name = "CEDARS_SECRET_KEY", valueFrom = aws_secretsmanager_secret.app_secret_key.arn },
  ]
}

# ---- Backend task definition ----
resource "aws_ecs_task_definition" "backend" {
  family                   = "${local.prefix}-backend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.backend_cpu
  memory                   = var.backend_memory
  execution_role_arn       = local.execution_role_arn
  task_role_arn            = local.task_role_arn

  container_definitions = jsonencode([{
    name         = "backend"
    image        = local.backend_image
    essential    = true
    environment  = local.app_environment
    secrets      = local.app_secrets
    portMappings = [{ containerPort = 8000, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "backend"
      }
    }
  }])

  lifecycle {
    precondition {
      condition     = var.create_execution_role || var.execution_role_arn != ""
      error_message = "Execution role: set create_execution_role = true (self-service at MSK) or supply execution_role_arn."
    }
    precondition {
      condition     = var.create_task_role || var.task_role_arn != ""
      error_message = "Task role: mskEngineerUser cannot create the Bedrock task role. Have IAM admin pre-create it (bedrockServiceAccess- prefix, bedrock boundary, scoped to the CEDARS bucket + bedrock:InvokeModel) and set task_role_arn."
    }
  }
}

# ---- Worker task definition (same image, arq command) ----
resource "aws_ecs_task_definition" "worker" {
  family                   = "${local.prefix}-worker"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.worker_cpu
  memory                   = var.worker_memory
  execution_role_arn       = local.execution_role_arn
  task_role_arn            = local.task_role_arn

  container_definitions = jsonencode([{
    name        = "worker"
    image       = local.backend_image
    essential   = true
    command     = ["uv", "run", "arq", "app.worker.WorkerSettings"]
    environment = local.app_environment
    secrets     = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.worker.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "worker"
      }
    }
  }])
}

# ---- Frontend task definition ----
resource "aws_ecs_task_definition" "frontend" {
  family                   = "${local.prefix}-frontend"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.frontend_cpu
  memory                   = var.frontend_memory
  execution_role_arn       = local.execution_role_arn

  container_definitions = jsonencode([{
    name         = "frontend"
    image        = local.frontend_image
    essential    = true
    portMappings = [{ containerPort = 80, protocol = "tcp" }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.frontend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "frontend"
      }
    }
  }])
}

# ---- Services ----
resource "aws_ecs_service" "backend" {
  name            = "${local.prefix}-backend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.backend.arn
  desired_count   = var.backend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.backend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.backend.arn
    container_name   = "backend"
    container_port   = 8000
  }

  # Zero-downtime rolling deploy.
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  depends_on = [aws_lb_listener_rule.backend]
}

resource "aws_ecs_service" "worker" {
  name            = "${local.prefix}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.worker_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.worker.id]
    assign_public_ip = false
  }
}

resource "aws_ecs_service" "frontend" {
  name            = "${local.prefix}-frontend"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.frontend.arn
  desired_count   = var.frontend_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.private_subnet_ids
    security_groups  = [aws_security_group.frontend.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.frontend.arn
    container_name   = "frontend"
    container_port   = 80
  }

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  depends_on = [aws_lb_listener.http, aws_lb_listener.https]
}

# ---- Migration task definition (run one-off: alembic upgrade head) ----
# Run via: aws ecs run-task --cluster <cluster> --task-definition <family> \
#   --launch-type FARGATE --network-configuration '...' \
#   --overrides '{"containerOverrides":[{"name":"migrate",...}]}'
resource "aws_ecs_task_definition" "migrate" {
  family                   = "${local.prefix}-migrate"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = 512
  memory                   = 1024
  execution_role_arn       = local.execution_role_arn
  task_role_arn            = local.task_role_arn

  container_definitions = jsonencode([{
    name        = "migrate"
    image       = local.backend_image
    essential   = true
    command     = ["uv", "run", "alembic", "upgrade", "head"]
    environment = local.app_environment
    secrets     = local.app_secrets
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = aws_cloudwatch_log_group.backend.name
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "migrate"
      }
    }
  }])
}
