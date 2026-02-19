# MinIO + AWS S3 Hybrid Storage Architecture

## Overview

CEDARS uses a **hybrid storage strategy** combining local MinIO (S3-compatible) with AWS S3 for batch inference.

## Why This Architecture?

### The Challenge

**AWS Bedrock Batch Inference Requirements:**
- Requires REAL AWS S3 buckets
- Bedrock runs in AWS cloud and cannot access local storage
- IAM roles only work with AWS S3, not MinIO
- Bedrock needs direct S3 read/write access

**CEDARS Current Setup:**
- Uses MinIO for all file storage (uploaded datasets, results, etc.)
- MinIO runs in Docker network (not accessible from AWS)
- All data stays local for privacy/security

### The Solution: Hybrid Approach

```
┌──────────────────────────────────────────────┐
│          Local (Docker Network)              │
│  ┌────────────┐         ┌─────────────┐     │
│  │   MinIO    │◄────────┤   CEDARS    │     │
│  │  (Primary  │         │Application  │     │
│  │  Storage)  │         └──────┬──────┘     │
│  └────────────┘                │            │
└────────────────────────────────┼────────────┘
                                 │
                        Upload/Download
                                 │
┌────────────────────────────────▼────────────┐
│          AWS Cloud                          │
│  ┌──────────┐        ┌────────────────┐    │
│  │  AWS S3  │◄───────┤  AWS Bedrock   │    │
│  │ (Staging)│        │Batch Inference │    │
│  └──────────┘        └────────────────┘    │
└─────────────────────────────────────────────┘
```

## Storage Locations

### MinIO (Primary - Permanent Storage)

**What's stored:**
- `uploaded_files/` - Original datasets (CSV, Parquet, etc.)
- `batch_files/` - Copies of batch input JSONL files
- `batch_results/` - Copies of batch output results
- `annotated_files/` - Downloaded annotation results

**Access:**
- Internal: http://minio:9000
- External: http://localhost:9000 (via nginx)
- Console: http://localhost:9001

**Credentials:**
- From `.env`: `MINIO_ACCESS_KEY`, `MINIO_SECRET_KEY`

### AWS S3 (Temporary - Staging Only)

**What's stored (temporarily):**
- `cedars/batch_inputs/{project_id}/{timestamp}/` - Batch input files
- `cedars/batch_outputs/{project_id}/{timestamp}/` - Batch results

**Lifecycle:**
1. Files uploaded before Bedrock job submission
2. Results written by Bedrock after processing
3. Files downloaded immediately after job completion
4. **Can be deleted after import** (copies in MinIO)

**Recommendation:** Set S3 lifecycle policy to auto-delete after 30 days

## Data Security

### Privacy Considerations

**Data at Rest:**
- Primary storage: Local MinIO (never leaves your infrastructure)
- Temporary storage: AWS S3 (encrypted, auto-delete policy)

**Data in Transit:**
- MinIO ↔ CEDARS: Docker network (internal only)
- CEDARS ↔ AWS S3: HTTPS (TLS encrypted)
- AWS S3 ↔ Bedrock: AWS internal network (encrypted)

**Recommendations:**
1. Enable S3 bucket encryption (SSE-S3 or SSE-KMS)
2. Use VPC endpoints for Bedrock if available
3. Set bucket policies to restrict access
4. Enable S3 access logging for audit trail
5. Use temporary credentials (AWS STS) when possible

## Cost Optimization

### Storage Costs

**MinIO:**
- Free (uses local disk)
- Only limited by your EC2 instance storage

**AWS S3:**
- Pay per GB stored
- With 30-day lifecycle: minimal cost (~few cents/month)
- Consider S3 Intelligent-Tiering for larger jobs

### Data Transfer Costs

**Inbound to S3:**
- Free (upload batch files)

**Outbound from S3:**
- First 100 GB/month free
- After: ~$0.09/GB

**Estimate:**
- 10,000 notes × 500 tokens × ~4 chars/token = ~20 MB
- Even 1M notes = ~2 GB = ~$0.18 transfer cost

## Configuration

### Environment Variables

```bash
# MinIO (already configured)
MINIO_HOST=minio
MINIO_PORT=9000
MINIO_ACCESS_KEY=your_minio_key
MINIO_SECRET_KEY=your_minio_secret

# AWS S3 (for batch inference)
AWS_ACCESS_KEY_ID=your_aws_key
AWS_SECRET_ACCESS_KEY=your_aws_secret
AWS_SESSION_TOKEN=your_session_token  # if temporary
AWS_REGION_NAME=us-east-1

# Batch-specific
AWS_BEDROCK_S3_BUCKET=your-batch-bucket  # AWS S3, not MinIO!
AWS_BEDROCK_ROLE_ARN=arn:aws:iam::account:role/BedrockBatchRole
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
```

### Code Changes Made

1. **`batch_bedrock.py`:**
   - Added `minio_client` parameter
   - Added `save_to_minio()` method
   - Modified `upload_to_s3()` to also save to MinIO
   - Modified `download_results()` to save to MinIO

2. **`ops.py`:**
   - Pass `minio` client to `BedrockBatchProcessor`
   - All batch operations use hybrid storage

3. **Documentation:**
   - Updated setup guide with hybrid architecture
   - Added this explainer document

## Troubleshooting

### "Cannot access MinIO from Bedrock"

**This is expected!** Bedrock cannot access MinIO. That's why we upload to AWS S3.

**Solution:** Make sure `AWS_BEDROCK_S3_BUCKET` points to a real AWS S3 bucket, not MinIO.

### "Access Denied" on S3 Upload

**Cause:** AWS credentials lack S3 permissions

**Solution:** Ensure IAM user/role has:
```json
{
  "Effect": "Allow",
  "Action": [
    "s3:PutObject",
    "s3:GetObject",
    "s3:ListBucket"
  ],
  "Resource": [
    "arn:aws:s3:::your-bucket/*",
    "arn:aws:s3:::your-bucket"
  ]
}
```

### Files Not Appearing in MinIO

**Check:**
1. MinIO client is passed to `BedrockBatchProcessor`
2. `g.bucket_name` is set correctly
3. MinIO container is running: `docker ps | grep minio`
4. Check MinIO console at http://localhost:9001

### Duplicate Storage Concerns

**Q:** Won't this double my storage usage?

**A:** Temporarily yes, but:
- S3 files can be deleted after import (use lifecycle policy)
- MinIO copies are permanent record-keeping
- For 10k notes, batch files are ~20 MB (negligible)

## Benefits of This Approach

✅ **Privacy:** Primary data stays in local MinIO
✅ **Cost:** S3 only for temporary staging (~30 days)
✅ **Compliance:** Can use Bedrock's ~50% cost savings
✅ **Audit:** Full copies in MinIO for record-keeping
✅ **Flexibility:** Easy to purge S3 without losing data

## Future Enhancements

Possible improvements:

1. **Auto-cleanup:** Automatically delete S3 files after successful import
2. **Compression:** Compress batch files before S3 upload
3. **Incremental:** Only upload new/changed notes
4. **Monitoring:** Dashboard showing MinIO vs S3 usage
5. **Local-only mode:** Option to skip S3 entirely (no batch inference)

## Comparison Table

| Feature | MinIO | AWS S3 |
|---------|-------|--------|
| **Location** | Local Docker | AWS Cloud |
| **Primary Use** | All CEDARS files | Bedrock staging only |
| **Data Retention** | Permanent | Temporary (30 days) |
| **Access** | CEDARS only | CEDARS + Bedrock |
| **Cost** | Free (local disk) | Pay per GB |
| **Encryption** | Optional | Enabled (recommended) |
| **Backup** | Your responsibility | AWS managed |
| **Network** | Internal Docker | Internet |

## Summary

The hybrid MinIO + S3 architecture provides the best of both worlds:

- **Keep your data local and private** (MinIO)
- **Leverage AWS Bedrock's batch inference** (S3 staging)
- **Minimize cloud storage costs** (temp files only)
- **Maintain full audit trail** (copies in MinIO)

Your clinical notes are processed by AWS Bedrock but permanently stored only in your local MinIO instance, giving you control, privacy, and cost savings.
