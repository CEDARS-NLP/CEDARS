########################################################################
# Aurora PostgreSQL — dedicated CEDARS cluster (NOT shared with
# clinical-trials-research). Engine version matches in-account 16.11.
########################################################################

resource "random_password" "db_master" {
  length  = 32
  special = false # avoid URL-encoding headaches in the asyncpg DSN
}

resource "aws_secretsmanager_secret" "db_password" {
  name        = "user-${local.prefix}-aurora-password"
  description = "CEDARS v2 Aurora master password"

  # Hard-delete on destroy so the name frees immediately.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_password" {
  secret_id     = aws_secretsmanager_secret.db_password.id
  secret_string = random_password.db_master.result
}

resource "aws_db_subnet_group" "aurora" {
  name       = "${local.prefix}-aurora"
  subnet_ids = var.private_subnet_ids
  tags       = { Name = "${local.prefix}-aurora" }
}

resource "aws_rds_cluster" "aurora" {
  cluster_identifier = "${local.prefix}-aurora"
  engine             = "aurora-postgresql"
  engine_version     = var.db_engine_version
  database_name      = var.db_name
  master_username    = var.db_master_username
  master_password    = random_password.db_master.result

  db_subnet_group_name   = aws_db_subnet_group.aurora.name
  vpc_security_group_ids = [aws_security_group.aurora.id]

  storage_encrypted         = true
  deletion_protection       = var.db_deletion_protection
  skip_final_snapshot       = var.db_skip_final_snapshot
  final_snapshot_identifier = var.db_skip_final_snapshot ? null : "${local.prefix}-aurora-final"

  backup_retention_period      = 7
  preferred_backup_window      = "07:00-09:00"
  preferred_maintenance_window = "sun:09:30-sun:10:30"

  # Serverless v2 scaling (used when instances are db.serverless).
  serverlessv2_scaling_configuration {
    min_capacity = var.db_serverless_min_acu
    max_capacity = var.db_serverless_max_acu
  }

  lifecycle {
    ignore_changes = [master_password]
  }
}

resource "aws_rds_cluster_instance" "writer" {
  identifier         = "${local.prefix}-aurora-writer"
  cluster_identifier = aws_rds_cluster.aurora.id
  instance_class     = var.db_instance_class
  engine             = aws_rds_cluster.aurora.engine
  engine_version     = aws_rds_cluster.aurora.engine_version

  db_subnet_group_name = aws_db_subnet_group.aurora.name
}

resource "aws_rds_cluster_instance" "reader" {
  count = var.db_reader_enabled ? 1 : 0

  identifier         = "${local.prefix}-aurora-reader"
  cluster_identifier = aws_rds_cluster.aurora.id
  instance_class     = var.db_instance_class
  engine             = aws_rds_cluster.aurora.engine
  engine_version     = aws_rds_cluster.aurora.engine_version

  db_subnet_group_name = aws_db_subnet_group.aurora.name
}

# Full asyncpg DSN (with password) stored as a secret and injected whole into
# CEDARS_DATABASE_URL. The app config expects a complete URL, so we can't split
# out just the password. random_password uses special=false so no URL-encoding.
resource "aws_secretsmanager_secret" "db_url" {
  name        = "user-${local.prefix}-database-url"
  description = "CEDARS v2 full asyncpg DATABASE_URL"

  # Hard-delete on destroy so the name frees immediately.
  recovery_window_in_days = 0
}

resource "aws_secretsmanager_secret_version" "db_url" {
  secret_id = aws_secretsmanager_secret.db_url.id
  secret_string = format(
    "postgresql+asyncpg://%s:%s@%s:5432/%s",
    var.db_master_username,
    random_password.db_master.result,
    aws_rds_cluster.aurora.endpoint,
    var.db_name,
  )
}
