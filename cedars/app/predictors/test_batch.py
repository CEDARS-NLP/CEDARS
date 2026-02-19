"""
Test script for BedrockBatchProcessor.
Run on EC2 with AWS credentials configured.

Usage:
    python -m app.predictors.test_batch

Requires:
    - boto3, pandas installed
    - AWS credentials (IAM role on EC2 or env vars)
    - S3 bucket with Bedrock access
    - sample.csv with columns: text_id, text
"""

import json
import time
from pathlib import Path

import pandas as pd

from .batch_bedrock import BedrockBatchProcessor

# ---- CONFIGURE THESE ----
MODEL_ID = "anthropic.claude-3-haiku-20240307-v1:0:48k"
ROLE_ARN = "arn:aws:iam::180294205688:role/userServiceRoleBedrockBatchInference"  # Your Bedrock role ARN
S3_BUCKET = "llm-vte-labeling-data"                   # Your S3 bucket
REGION = "us-east-1"
CSV_PATH = "simulated_patients.csv"
PROJECT_ID = "testrun"

EVENT_DEFINITION = {
    "name": "Venous Thromboembolism",
    "description": "Evidence of deep vein thrombosis (DVT) or pulmonary embolism (PE)",
    "include_criteria": "Confirmed DVT or PE diagnosis, new anticoagulation for VTE",
    "exclude_criteria": "Historical VTE only, prophylactic anticoagulation, rule-out without confirmation",
}
# --------------------------


def main():
    df = pd.read_csv(CSV_PATH)
    print(f"Loaded {len(df)} notes from {CSV_PATH}")
    print(f"Columns: {list(df.columns)}")
    print(f"Sample:\n{df.head(2)}\n")

    processor = BedrockBatchProcessor(
        model_id=MODEL_ID,
        role_arn=ROLE_ARN,
        region=REGION,
        s3_bucket=S3_BUCKET,
        event_definition=EVENT_DEFINITION,
        minio_client=None,
    )

    # Step 1: Create JSONL batch input files
    print("=" * 50)
    print("STEP 1: Creating batch input files...")
    input_files = processor.create_batch_input_file(df, "/tmp/test_batch")
    for f in input_files:
        print(f"  Created: {f}")
        with open(f) as fh:
            first_line = json.loads(fh.readline())
            print(f"  First record ID: {first_line['recordId']}")
            print(f"  System prompt preview: {first_line['modelInput']['system'][:100]}...")

    # Step 2: Upload to S3
    print("\n" + "=" * 50)
    print("STEP 2: Uploading to S3...")
    s3_uris = []
    for local_file in input_files:
        filename = Path(local_file).name
        s3_key = f"cedars/batch_inputs/{PROJECT_ID}/{filename}"
        s3_uri = processor.upload_to_s3(local_file, s3_key, also_save_to_minio=False)
        s3_uris.append(s3_uri)
        print(f"  Uploaded: {s3_uri}")

    # Step 3: Submit batch job
    print("\n" + "=" * 50)
    print("STEP 3: Submitting batch job...")
    output_prefix = f"s3://{S3_BUCKET}/cedars/batch_outputs/{PROJECT_ID}/"

    jobs = []
    for idx, uri in enumerate(s3_uris):
        job_info = processor.submit_batch_job(uri, output_prefix, f"test-{PROJECT_ID}-job{idx+1}")
        jobs.append(job_info)
        print(job_info)
        print(f"  Job ARN: {job_info['job_arn']}")
        print(f"  Status:  {job_info['status']}")

    # Step 4: Poll for completion
    print("\n" + "=" * 50)
    print("STEP 4: Waiting for completion (polling every 60s)...")
    for job in jobs:
        while True:
            status = processor.get_job_status(job["job_arn"])
            print(f"  [{time.strftime('%H:%M:%S')}] {job['job_name']}: {status['status']}")

            if status["status"] in ["Completed", "Failed", "Stopped"]:
                if status["status"] == "Failed":
                    print(f"  FAILED: {status.get('message')}")
                break
            time.sleep(60)

    # Step 5: Download and parse results
    print("\n" + "=" * 50)
    print("STEP 5: Downloading results...")
    result_files = processor.download_results(output_prefix, "/tmp/test_batch_results", also_save_to_minio=False)
    print(f"  Downloaded {len(result_files)} files")

    print("\nSTEP 6: Parsing results...")
    results_df = processor.parse_results(result_files)
    print(f"  Parsed {len(results_df)} predictions")
    print(f"\nResults:\n{results_df.to_string()}")

    # Summary
    print("\n" + "=" * 50)
    print("SUMMARY:")
    print(f"  Total notes:       {len(df)}")
    print(f"  Total predictions: {len(results_df)}")
    print(f"  Successful:        {results_df['prediction'].notna().sum()}")
    print(f"  Failed to parse:   {results_df['prediction'].isna().sum()}")
    if results_df['prediction'].notna().any():
        print(f"  Mean score:        {results_df['prediction'].mean():.3f}")


if __name__ == "__main__":
    main()
