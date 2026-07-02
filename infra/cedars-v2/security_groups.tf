########################################################################
# Security groups
#
# Traffic flow:
#   internal network -> ALB(443) -> backend(8000) / frontend(80)
#   backend, worker  -> aurora(5432), redis(6379), S3/Bedrock(egress 443)
########################################################################

# ---- ALB ----
resource "aws_security_group" "alb" {
  name        = "${local.prefix}-alb"
  description = "CEDARS internal ALB"
  vpc_id      = var.vpc_id

  # Ingress CIDRs default to the VPC CIDR only (see var.alb_ingress_cidrs).
  # The ALB is `internal` (no public IP), so widening to 0.0.0.0/0 only admits
  # sources that can already route to the private ALB IPs (in-VPC + VPN/peering)
  # — useful for a spike when VPN clients aren't in the VPC CIDR.
  # Port depends on enable_https: 443 (HTTPS) or 80 (HTTP spike).
  ingress {
    description = "App traffic (see var.alb_ingress_cidrs)"
    from_port   = var.enable_https ? 443 : 80
    to_port     = var.enable_https ? 443 : 80
    protocol    = "tcp"
    cidr_blocks = length(var.alb_ingress_cidrs) > 0 ? var.alb_ingress_cidrs : [data.aws_vpc.selected.cidr_block]
  }

  egress {
    description = "To backend and frontend tasks"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.prefix}-alb" }
}

data "aws_vpc" "selected" {
  id = var.vpc_id
}

# ---- Backend tasks ----
resource "aws_security_group" "backend" {
  name        = "${local.prefix}-backend"
  description = "CEDARS backend (uvicorn) tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "App traffic from ALB"
    from_port       = 8000
    to_port         = 8000
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound (Aurora, Redis, S3, Bedrock, ECR)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.prefix}-backend" }
}

# ---- Worker tasks (no ingress) ----
resource "aws_security_group" "worker" {
  name        = "${local.prefix}-worker"
  description = "CEDARS ARQ worker tasks"
  vpc_id      = var.vpc_id

  egress {
    description = "All outbound (Aurora, Redis, S3, Bedrock, ECR)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.prefix}-worker" }
}

# ---- Frontend tasks ----
resource "aws_security_group" "frontend" {
  name        = "${local.prefix}-frontend"
  description = "CEDARS frontend (nginx) tasks"
  vpc_id      = var.vpc_id

  ingress {
    description     = "HTTP from ALB"
    from_port       = 80
    to_port         = 80
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "All outbound (ECR)"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = { Name = "${local.prefix}-frontend" }
}

# ---- Aurora ----
resource "aws_security_group" "aurora" {
  name        = "${local.prefix}-aurora"
  description = "CEDARS Aurora PostgreSQL"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Postgres from backend"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
  }

  ingress {
    description     = "Postgres from worker"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  tags = { Name = "${local.prefix}-aurora" }
}

# ---- Redis ----
resource "aws_security_group" "redis" {
  name        = "${local.prefix}-redis"
  description = "CEDARS ElastiCache Redis"
  vpc_id      = var.vpc_id

  ingress {
    description     = "Redis from backend"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.backend.id]
  }

  ingress {
    description     = "Redis from worker"
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.worker.id]
  }

  tags = { Name = "${local.prefix}-redis" }
}
