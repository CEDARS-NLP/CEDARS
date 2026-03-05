"""API tests for prediction job dispatch, status, and cancellation."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.predictors.base import PredictionResult


async def register_and_login(client: AsyncClient, email: str = "admin@test.com") -> None:
    await client.post("/api/v1/auth/register", json={"email": email, "name": "Admin", "password": "secret123"})
    await client.post("/api/v1/auth/login", json={"email": email, "password": "secret123"})


async def create_project(client: AsyncClient) -> str:
    resp = await client.post("/api/v1/projects", json={"name": "Pred Dispatch Test", "description": "test"})
    return resp.json()["id"]


async def setup_notes_and_nlp(client: AsyncClient, pid: str):
    from unittest.mock import patch as mock_patch
    create_resp = await client.post(
        f"/api/v1/projects/{pid}/data/sources",
        json={"name": "test.csv", "connector_type": "file_upload", "config": {
            "s3_key": "test.csv", "file_type": "csv",
            "column_mapping": {"patient_id": "patient_id", "text_id": "text_id", "text": "text", "note_date": "date"},
        }},
    )
    ds_id = create_resp.json()["id"]
    csv_data = (
        b"patient_id,text_id,text,date\n"
        b"P001,N001,Patient presents with troponin elevation.,2026-01-10\n"
        b"P002,N002,Confirmed myocardial infarction.,2026-01-12\n"
    )
    with mock_patch("app.connectors.file_upload.download_file", return_value=csv_data):
        await client.post(f"/api/v1/projects/{pid}/data/sources/{ds_id}/ingest")
    await client.post(f"/api/v1/projects/{pid}/nlp/queries", json={"query": "troponin OR myocardial"})
    await client.post(f"/api/v1/projects/{pid}/nlp/run")


async def add_predictor(client: AsyncClient, pid: str) -> str:
    resp = await client.post(f"/api/v1/projects/{pid}/predictors", json={
        "name": "Test LLM", "predictor_type": "llm",
        "config": {"provider": "ollama", "model": "llama3", "api_base": "http://localhost:11434",
                   "event_definition": {"name": "MI", "description": "Myocardial Infarction",
                                        "include_criteria": "troponin", "exclude_criteria": ""}},
    })
    pred_id = resp.json()["id"]
    await client.post(f"/api/v1/projects/{pid}/predictors/{pred_id}/activate")
    return pred_id


class TestPredictionJobDispatch:
    async def test_run_dispatches_job(self, client):
        """POST /annotations/predictions/run creates a background job."""
        await register_and_login(client)
        pid = await create_project(client)
        await setup_notes_and_nlp(client, pid)
        await add_predictor(client, pid)

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="ok")
        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor
            resp = await client.post(f"/api/v1/projects/{pid}/annotations/predictions/run")

        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] in ("pending", "running", "completed")

    async def test_status_returns_job_info(self, client):
        """GET /annotations/predictions/status returns latest job info."""
        await register_and_login(client)
        pid = await create_project(client)
        await setup_notes_and_nlp(client, pid)
        await add_predictor(client, pid)

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="ok")
        with patch("app.jobs.prediction.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor
            await client.post(f"/api/v1/projects/{pid}/annotations/predictions/run")

        resp = await client.get(f"/api/v1/projects/{pid}/annotations/predictions/status")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert "status" in data
        assert "progress" in data

    async def test_cancel_returns_404_when_no_running_job(self, client):
        """POST /annotations/predictions/cancel returns 404 when no running job."""
        await register_and_login(client)
        pid = await create_project(client)
        resp = await client.post(f"/api/v1/projects/{pid}/annotations/predictions/cancel")
        assert resp.status_code == 404

    async def test_run_fails_without_active_predictor(self, client):
        """POST /annotations/predictions/run returns 400 without active predictor."""
        await register_and_login(client)
        pid = await create_project(client)
        resp = await client.post(f"/api/v1/projects/{pid}/annotations/predictions/run")
        assert resp.status_code == 400
