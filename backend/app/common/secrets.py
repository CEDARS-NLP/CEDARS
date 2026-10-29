"""AWS Secrets Manager client configuration."""

import boto3

from app.config import settings


def get_secrets_manager_client():
    """Create a Secrets Manager client, optionally targeting a local endpoint."""
    options = {"region_name": settings.aws_region}
    if settings.secrets_manager_endpoint_url:
        options["endpoint_url"] = settings.secrets_manager_endpoint_url
    return boto3.client("secretsmanager", **options)
