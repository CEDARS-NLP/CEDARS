########################################################################
# S3 bucket for CEDARS object storage (uploads, exports, artifacts).
# Replaces MinIO. app/common/s3.py uses the task role (no static keys)
# when CEDARS_S3_ENDPOINT and access keys are empty.
########################################################################

resource "aws_s3_bucket" "storage" {
  bucket = "user-${local.prefix}-storage"

  # Bucket holds clinical artifacts — do not allow accidental destroy with
  # objects present. Remove force_destroy override deliberately if tearing down.
  force_destroy = false
}

resource "aws_s3_bucket_versioning" "storage" {
  bucket = aws_s3_bucket.storage.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "storage" {
  bucket = aws_s3_bucket.storage.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "aws:kms"
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_public_access_block" "storage" {
  bucket                  = aws_s3_bucket.storage.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Enforce TLS-only access.
resource "aws_s3_bucket_policy" "storage" {
  bucket = aws_s3_bucket.storage.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "DenyInsecureTransport"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource = [
        aws_s3_bucket.storage.arn,
        "${aws_s3_bucket.storage.arn}/*",
      ]
      Condition = {
        Bool = { "aws:SecureTransport" = "false" }
      }
    }]
  })
}
