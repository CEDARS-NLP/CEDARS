########################################################################
# CEDARS v2 — locals and shared data sources
########################################################################

data "aws_caller_identity" "current" {}
data "aws_region" "current" {}

locals {
  name   = var.name_prefix
  prefix = "${var.name_prefix}-${var.environment}"

  # Scheme follows enable_https. In the HTTP spike there's no hostname/cert, so
  # cookies must NOT be Secure (browsers drop Secure cookies over http) and CORS
  # falls back to localhost (the ALB DNS name has no fixed origin worth pinning).
  app_scheme    = var.enable_https ? "https" : "http"
  cookie_secure = var.enable_https ? "true" : "false"
  cors_origins  = var.app_hostname != "" ? "${local.app_scheme}://${var.app_hostname}" : "http://localhost:5173"

  tags = {
    Project     = "cedars-v2"
    Environment = var.environment
  }
}
