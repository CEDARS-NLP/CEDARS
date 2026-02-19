# AWS Bedrock Batch Inference Setup Guide

## Overview

AWS Bedrock batch inference allows you to process large volumes of clinical notes asynchronously at ~50% lower cost compared to real-time inference. This is ideal for initial annotation of large datasets.

## Storage Architecture

CEDARS uses a **hybrid storage approach**:

```
┌─────────────────────────────────────────────────────┐
│                 CEDARS Application                  │
├─────────────────────────────────────────────────────┤
│  MinIO (Local)              AWS S3 (Cloud)          │
│  ├─ Uploaded datasets       ├─ Batch input files   │
│  ├─ Batch file copies       ├─ Batch results       │
│  └─ Result archives         └─ (Temporary)         │
└─────────────────────────────────────────────────────┘
                          │
                          ▼
                 ┌────────────────┐
                 │  AWS Bedrock   │
                 │ Batch Inference│
                 └────────────────┘
```

**Why?** AWS Bedrock requires REAL AWS S3 (cannot access your local MinIO). The hybrid approach:
- Keeps all your data locally in MinIO (primary storage)
- Temporarily uploads batch files to AWS S3 for Bedrock processing
- Downloads results and stores them back in MinIO
- AWS S3 acts as a staging area only

## Prerequisites

1. AWS account with Bedrock access
2. IAM role with Bedrock batch inference permissions
3. S3 bucket for batch job input/output
4. boto3 installed (`pip install boto3>=1.28.57`)

## Step 1: AWS IAM Setup

### Create IAM Role for Bedrock Batch Jobs

Create an IAM role with the following trust policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": {
        "Service": "bedrock.amazonaws.com"
      },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

Attach the following permissions policy:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:PutObject",
        "s3:ListBucket"
      ],
      "Resource": [
        "arn:aws:s3:::your-bucket-name/*",
        "arn:aws:s3:::your-bucket-name"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel"
      ],
      "Resource": "*"
    }
  ]
}
```

## Step 2: Configure Environment Variables

Add these to your `.env` file:

```bash
# AWS Credentials (already configured for real-time)
AWS_ACCESS_KEY_ID=your_access_key
AWS_SECRET_ACCESS_KEY=your_secret_key
AWS_SESSION_TOKEN=your_session_token  # If using temporary credentials
AWS_REGION_NAME=us-east-1

# Batch Inference Specific
BEDROCK_MODEL_ID=anthropic.claude-3-5-sonnet-20240620-v1:0
AWS_BEDROCK_ROLE_ARN=arn:aws:iam::123456789012:role/BedrockBatchRole
AWS_BEDROCK_S3_BUCKET=your-batch-inference-bucket
```

## Step 3: S3 Bucket Setup

Create an AWS S3 bucket (for Bedrock batch jobs only):

```
your-batch-inference-bucket/
├── cedars/
│   ├── batch_inputs/
│   │   └── {project_id}/
│   │       └── {timestamp}/
│   │           └── batch_input_1.jsonl
│   └── batch_outputs/
│       └── {project_id}/
│           └── {timestamp}/
│               └── results.jsonl.out
```

Enable versioning and encryption on your S3 bucket (recommended).

### Optional: S3 Lifecycle Policy

Since S3 is only used as temporary staging, you can set up a lifecycle policy to auto-delete files after processing:

```json
{
  "Rules": [
    {
      "Id": "DeleteBatchFilesAfter30Days",
      "Status": "Enabled",
      "Prefix": "cedars/",
      "Expiration": {
        "Days": 30
      }
    }
  ]
}
```

This saves storage costs as all permanent data is in your local MinIO.

## Step 4: Request Model Access

1. Go to AWS Bedrock Console
2. Navigate to "Model access"
3. Request access to Claude models
4. Wait for approval (usually instant for some models)

## Data Flow

Here's what happens when you start a batch job:

```
1. Upload Dataset (CSV/Parquet)
   ↓
   [Stored in MinIO: uploaded_files/]
   
2. Click "Start Batch Inference"
   ↓
   [Create JSONL batch files]
   ↓
   [Save copy to MinIO: batch_files/]
   ↓
   [Upload to AWS S3: s3://bucket/cedars/batch_inputs/]
   
3. Submit to Bedrock
   ↓
   [Bedrock reads from S3, processes notes]
   ↓
   [Bedrock writes results to S3: s3://bucket/cedars/batch_outputs/]
   
4. Click "Import Results"
   ↓
   [Download from S3]
   ↓
   [Save to MinIO: batch_results/]
   ↓
   [Import predictions to MongoDB]
   ↓
   [Annotations appear in CEDARS UI]
```

**Note:** Your clinical notes never leave your control except temporarily on AWS S3 during processing. All permanent storage is in your local MinIO instance.

## Usage

### Via Web UI

1. Go to **Operations > Upload Query**
2. Upload your clinical notes
3. Click **"Start Batch Inference"**
4. Monitor progress on the batch status page
5. Once complete, click **"Import Results"**

### Programmatically

```python
from app.predictors.batch_bedrock import BedrockBatchProcessor
import pandas as pd

# Initialize processor
processor = BedrockBatchProcessor(
    model_id="anthropic.claude-3-5-sonnet-20240620-v1:0",
    role_arn="arn:aws:iam::123456789012:role/BedrockBatchRole",
    region="us-east-1",
    s3_bucket="your-batch-inference-bucket"
)

# Load notes
notes_df = pd.read_csv("clinical_notes.csv")

# Process batch
batch_info = processor.process_batch_end_to_end(
    notes_df=notes_df,
    project_id="my_project",
    wait_for_completion=False  # Set True to block until complete
)

print(f"Submitted {len(batch_info['jobs'])} jobs")
print(f"Job ARNs: {[job['job_arn'] for job in batch_info['jobs']]}")
```

### Monitoring Job Status

```python
# Check job status
status = processor.get_job_status(job_arn)
print(f"Status: {status['status']}")

# Wait for completion (blocks)
final_status = processor.wait_for_completion(
    job_arn=job_arn,
    check_interval=60,  # Check every 60 seconds
    timeout=3600  # Timeout after 1 hour
)

# Download and parse results
result_files = processor.download_results(
    output_s3_uri=status['output_uri'],
    local_dir='/tmp/results'
)

results_df = processor.parse_results(result_files)
print(results_df.head())
```

## Cost Comparison

**Real-time Inference (via completion API):**
- Claude 3.5 Sonnet: $3.00 per MTok input / $15.00 per MTok output

**Batch Inference:**
- Claude 3.5 Sonnet: $1.50 per MTok input / $7.50 per MTok output
- **~50% cost savings**

Example: 10,000 notes × 500 tokens each = 5M tokens
- Real-time: ~$15.00
- Batch: ~$7.50

## Limitations

- Maximum 50,000 records per batch file
- Results may take hours to complete (not real-time)
- No streaming support
- Limited to models that support batch inference

## Troubleshooting

### "Invalid API Key format" Error

**Solution**: Set `bedrock: None` in the `api_key_env_map` in `ops.py` to let boto3 read credentials from environment.

### "botocore not found" Error

**Solution**: Install boto3:
```bash
pip install boto3>=1.28.57
```

And rebuild Docker containers:
```bash
docker compose --profile selfhosted up --build -d
```

### Job Stuck in "Submitted" Status

**Check**:
1. IAM role has correct permissions
2. S3 bucket policy allows Bedrock access
3. Model access has been granted in Bedrock console

### Results Not Importing

**Check**:
1. Job status is "Completed" (not "InProgress")
2. S3 output URI contains result files
3. Database has BATCH_JOBS collection

## Best Practices

1. **Start Small**: Test with 100 notes before processing thousands
2. **Monitor Costs**: Set up AWS Cost Alerts
3. **Use Appropriate Model**: Haiku for simple tasks, Sonnet for complex reasoning
4. **Chunk Large Datasets**: Stay under 50k records per file
5. **Keep S3 Clean**: Set lifecycle policies to delete old batch files

## Integration with Existing Workflow

```
┌─────────────────────┐
│  Upload Notes       │
│  (CSV/Parquet)      │
└──────────┬──────────┘
           │
     ┌─────▼──────┐
     │   Choose   │
     └─────┬──────┘
           │
     ┌─────┴──────┐
     │            │
┌────▼────┐  ┌───▼────────┐
│ Real-   │  │   Batch    │
│ time    │  │  Inference │
│ (LLM)   │  │ (Bedrock)  │
└────┬────┘  └───┬────────┘
     │           │
     │   ┌───────▼──────┐
     │   │ Wait hours   │
     │   │ Import       │
     │   └───────┬──────┘
     │           │
     └─────┬─────┘
           │
    ┌──────▼────────┐
    │  Annotations  │
    │   Database    │
    └───────────────┘
```

## Support

For issues or questions:
1. Check CloudWatch logs for Bedrock batch jobs
2. Review S3 bucket permissions
3. Verify IAM role trust relationships
4. Check CEDARS logs: `docker logs worker-task`
