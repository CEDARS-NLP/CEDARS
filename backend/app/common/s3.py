"""S3-compatible object storage client."""

import functools
import io
from typing import BinaryIO

import boto3
from botocore.config import Config as BotoConfig

from app.config import settings


@functools.lru_cache(maxsize=1)
def get_s3_client():
    """Create or return cached boto3 S3 client."""
    kwargs: dict = {
        "region_name": settings.s3_region or None,
        "config": BotoConfig(signature_version="s3v4"),
    }
    if settings.s3_endpoint:
        kwargs["endpoint_url"] = settings.s3_endpoint
    if settings.s3_access_key:
        kwargs["aws_access_key_id"] = settings.s3_access_key
        kwargs["aws_secret_access_key"] = settings.s3_secret_key
    return boto3.client("s3", **kwargs)


def upload_file(key: str, data: BinaryIO, content_type: str = "application/octet-stream") -> str:
    """Upload a file to S3 and return the key."""
    client = get_s3_client()
    client.upload_fileobj(data, settings.s3_bucket, key, ExtraArgs={"ContentType": content_type})
    return key


def download_file(key: str) -> bytes:
    """Download a file from S3 and return its contents."""
    client = get_s3_client()
    buf = io.BytesIO()
    client.download_fileobj(settings.s3_bucket, key, buf)
    buf.seek(0)
    return buf.read()


def delete_file(key: str) -> None:
    """Delete a file from S3."""
    client = get_s3_client()
    client.delete_object(Bucket=settings.s3_bucket, Key=key)
