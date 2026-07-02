########################################################################
# Application secrets (SECRET_KEY for JWT signing). DB URL secret lives in
# rds.tf; Aurora master password secret also in rds.tf.
########################################################################

resource "random_password" "app_secret_key" {
  length  = 64
  special = false
}

resource "aws_secretsmanager_secret" "app_secret_key" {
  name        = "user-${local.prefix}-secret-key"
  description = "CEDARS v2 JWT signing secret (CEDARS_SECRET_KEY)"

  # Hard-delete on destroy so the name frees immediately (no 7-30 day pending
  # window that blocks recreating a same-named secret).
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "app_secret_key" {
  secret_id     = aws_secretsmanager_secret.app_secret_key.id
  secret_string = random_password.app_secret_key.result
}
