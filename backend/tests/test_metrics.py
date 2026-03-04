"""Tests for Prometheus metrics endpoint."""
import pytest


@pytest.mark.asyncio
async def test_metrics_endpoint_exists(app, client):
    """The /metrics endpoint returns Prometheus format data."""
    resp = await client.get("/metrics")
    assert resp.status_code == 200
    text = resp.text
    assert "http_request" in text or "HELP" in text
