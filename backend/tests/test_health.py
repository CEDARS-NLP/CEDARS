import pytest


@pytest.mark.asyncio
async def test_health_endpoint(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["version"] == "2.0.0"


@pytest.mark.asyncio
async def test_health_reports_the_build_commit(client, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "git_sha", "abc12345")
    data = (await client.get("/api/v1/health")).json()
    assert data["commit"] == "abc12345"
    assert data["version"] == "2.0.0"  # existing consumers keep working
