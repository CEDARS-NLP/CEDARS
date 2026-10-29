from app.common import secrets
from app.config import settings


def test_secrets_manager_client_uses_configured_endpoint(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "aws_region", "us-east-1")
    monkeypatch.setattr(
        settings, "secrets_manager_endpoint_url", "http://localstack:4566"
    )
    monkeypatch.setattr(
        secrets.boto3,
        "client",
        lambda service, **options: calls.append((service, options)) or object(),
    )

    secrets.get_secrets_manager_client()

    assert calls == [
        (
            "secretsmanager",
            {"region_name": "us-east-1", "endpoint_url": "http://localstack:4566"},
        )
    ]


def test_secrets_manager_client_uses_aws_default_endpoint_without_override(monkeypatch):
    calls = []
    monkeypatch.setattr(settings, "aws_region", "us-east-1")
    monkeypatch.setattr(settings, "secrets_manager_endpoint_url", None)
    monkeypatch.setattr(
        secrets.boto3,
        "client",
        lambda service, **options: calls.append((service, options)) or object(),
    )

    secrets.get_secrets_manager_client()

    assert calls == [("secretsmanager", {"region_name": "us-east-1"})]
