"""Tests for ARQ worker configuration and NLP job dispatch."""
from unittest.mock import patch

import pytest


@pytest.fixture(autouse=True)
def _force_sync_dispatch():
    """Force dispatch_nlp_job to use the synchronous fallback path."""
    with patch("arq.create_pool", side_effect=ConnectionError("no Redis in tests")):
        yield


@pytest.mark.asyncio
async def test_enqueue_nlp_job(app, auth_client):
    """NLP run endpoint returns a job with pending status (async dispatch)."""
    # Create project
    resp = await auth_client.post(
        "/api/v1/projects", json={"name": "Test Project"}
    )
    project_id = resp.json()["id"]

    # Trigger NLP run — will fall back to sync since no Redis in tests
    resp = await auth_client.post(f"/api/v1/projects/{project_id}/nlp/run")
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert "status" in data
    assert data["status"] in ("pending", "running", "completed")


@pytest.mark.asyncio
async def test_dispatch_creates_background_job(app, auth_client):
    """dispatch_nlp_job creates a BackgroundJob record."""
    resp = await auth_client.post(
        "/api/v1/projects", json={"name": "Job Test"}
    )
    project_id = resp.json()["id"]

    resp = await auth_client.post(f"/api/v1/projects/{project_id}/nlp/run")
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]

    # Verify the BackgroundJob exists via DB
    from app.common.database import get_session
    from app.jobs.models import BackgroundJob

    async for session in app.dependency_overrides[get_session]():
        bg_job = await session.get(BackgroundJob, job_id)
        assert bg_job is not None
        assert bg_job.project_id == project_id
        assert bg_job.job_type.value == "nlp"
