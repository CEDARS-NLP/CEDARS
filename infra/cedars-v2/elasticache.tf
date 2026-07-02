########################################################################
# ElastiCache Redis — the one net-new stateful piece (nothing in-account
# to reuse). Backs the ARQ job queue.
########################################################################

resource "aws_elasticache_subnet_group" "redis" {
  name       = "${local.prefix}-redis"
  subnet_ids = var.private_subnet_ids
}

resource "aws_elasticache_replication_group" "redis" {
  replication_group_id = "${local.prefix}-redis"
  description          = "CEDARS v2 ARQ queue"

  engine         = "redis"
  engine_version = var.redis_engine_version
  node_type      = var.redis_node_type
  port           = 6379

  # Single node by default (cheaper). Set redis_ha_enabled=true for a replica
  # and automatic failover to remove the queue SPOF.
  num_cache_clusters         = var.redis_ha_enabled ? 2 : 1
  automatic_failover_enabled = var.redis_ha_enabled
  multi_az_enabled           = var.redis_ha_enabled

  subnet_group_name  = aws_elasticache_subnet_group.redis.name
  security_group_ids = [aws_security_group.redis.id]

  at_rest_encryption_enabled = true

  # NOTE: transit_encryption (TLS) is intentionally OFF. Enabling it requires
  # the app to use rediss:// and ARQ/redis-py TLS config. Revisit if in-VPC
  # transit encryption is required by policy.
  transit_encryption_enabled = false

  snapshot_retention_limit = 1

  lifecycle {
    ignore_changes = [num_cache_clusters]
  }
}

locals {
  redis_url = "redis://${aws_elasticache_replication_group.redis.primary_endpoint_address}:6379"
}
