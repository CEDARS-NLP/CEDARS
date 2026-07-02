output "alb_dns_name" {
  description = "Internal ALB DNS name"
  value       = aws_lb.main.dns_name
}

output "ecr_backend_repository_url" {
  description = "Push backend/worker image here"
  value       = aws_ecr_repository.backend.repository_url
}

output "ecr_frontend_repository_url" {
  description = "Push frontend image here"
  value       = aws_ecr_repository.frontend.repository_url
}

output "aurora_endpoint" {
  description = "Aurora writer endpoint"
  value       = aws_rds_cluster.aurora.endpoint
}

output "aurora_reader_endpoint" {
  description = "Aurora reader endpoint"
  value       = aws_rds_cluster.aurora.reader_endpoint
}

output "redis_primary_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
}

output "s3_bucket" {
  description = "CEDARS object storage bucket"
  value       = aws_s3_bucket.storage.bucket
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "migrate_task_definition" {
  description = "Task definition family for one-off alembic migrations"
  value       = aws_ecs_task_definition.migrate.family
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN holding the full CEDARS_DATABASE_URL"
  value       = aws_secretsmanager_secret.db_url.arn
}
