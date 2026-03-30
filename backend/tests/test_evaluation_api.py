"""API integration tests for the evaluation framework."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.predictors.base import PredictionResult


async def register_and_login(client: AsyncClient) -> None:
    """Register a user and login. Cookies are set automatically by httpx."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "eval@example.com", "name": "Evaluator", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "eval@example.com", "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    """Create a project and return its ID."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Eval Project", "description": "test"},
    )
    return resp.json()["id"]


async def setup_project_with_data(client: AsyncClient, pid: str) -> str:
    """Create notes + predictor. Returns predictor_config_id."""
    # Create data source and ingest notes
    create_resp = await client.post(
        f"/api/v1/projects/{pid}/data/sources",
        json={
            "name": "test.csv",
            "connector_type": "file_upload",
            "config": {
                "s3_key": "test.csv",
                "file_type": "csv",
                "column_mapping": {
                    "patient_id": "patient_id",
                    "text_id": "text_id",
                    "text": "text",
                    "note_date": "date",
                },
            },
        },
    )
    ds_id = create_resp.json()["id"]

    csv_data = (
        b"patient_id,text_id,text,date\n"
        b"P001,N001,Patient has troponin elevation and chest pain.,2026-01-10\n"
        b"P001,N002,No significant findings on echocardiogram.,2026-01-11\n"
        b"P002,N003,Confirmed myocardial infarction with ST elevation.,2026-01-12\n"
        b"P002,N004,Patient reports feeling better after medication.,2026-01-13\n"
        b"P003,N005,Elevated troponin levels noted on admission.,2026-01-14\n"
    )
    import asyncio
    with patch("app.connectors.file_upload.download_file", return_value=csv_data):
        await client.post(
            f"/api/v1/projects/{pid}/data/sources/{ds_id}/ingest",
        )
        await asyncio.sleep(0.5)

    # Add predictor
    resp = await client.post(
        f"/api/v1/projects/{pid}/predictors",
        json={
            "name": "Test LLM",
            "predictor_type": "llm",
            "config": {
                "provider": "ollama",
                "model": "test-model",
                "api_base": "http://localhost:11434",
                "event_name": "MI",
                "event_description": "Myocardial Infarction",
                "include_criteria": "troponin elevation",
                "exclude_criteria": "ruled out",
            },
        },
    )
    pred_id = resp.json()["id"]

    # Activate predictor
    await client.post(f"/api/v1/projects/{pid}/predictors/{pred_id}/activate")

    return pred_id


class TestEvaluationSessions:
    async def test_create_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        pred_id = await setup_project_with_data(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={
                "name": "Test Eval",
                "predictor_config_id": pred_id,
                "sample_config": {"size": 3, "keyword_match_ratio": 0.5, "keywords": []},
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "Test Eval"
        assert data["status"] == "sampling"
        assert data["total_notes"] == 3

    async def test_list_sessions(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        pred_id = await setup_project_with_data(client, pid)

        await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"predictor_config_id": pred_id, "sample_config": {"size": 2}},
        )

        resp = await client.get(f"/api/v1/projects/{pid}/evaluation/sessions")
        assert resp.status_code == 200
        assert len(resp.json()) == 1


class TestEvaluationPredictions:
    async def test_run_predictions(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        pred_id = await setup_project_with_data(client, pid)

        # Create session
        create_resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={
                "predictor_config_id": pred_id,
                "sample_config": {"size": 3},
            },
        )
        session_id = create_resp.json()["id"]

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="positive")

        with patch("app.evaluation.service.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor

            resp = await client.post(
                f"/api/v1/projects/{pid}/evaluation/sessions/{session_id}/run",
            )

        assert resp.status_code == 200
        assert resp.json()["status"] == "reviewing"


class TestEvaluationJudgments:
    async def _setup_session_with_predictions(self, client):
        """Full setup: data + session + predictions."""
        await register_and_login(client)
        pid = await create_project(client)
        pred_id = await setup_project_with_data(client, pid)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"predictor_config_id": pred_id, "sample_config": {"size": 3}},
        )
        session_id = create_resp.json()["id"]

        mock_result = PredictionResult(score=0.85, label=1, model="test", reasoning="test")
        with patch("app.evaluation.service.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor
            await client.post(
                f"/api/v1/projects/{pid}/evaluation/sessions/{session_id}/run",
            )

        return pid, session_id

    async def test_list_judgments(self, client):
        pid, sid = await self._setup_session_with_predictions(client)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments",
        )
        assert resp.status_code == 200
        judgments = resp.json()
        assert len(judgments) == 3
        assert all(j["judgment"] == "pending" for j in judgments)
        assert all(j["predicted_label"] == 1 for j in judgments)

    async def test_get_next_pending(self, client):
        pid, sid = await self._setup_session_with_predictions(client)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/next",
        )
        assert resp.status_code == 200
        assert resp.json()["judgment"] == "pending"

    async def test_submit_judgment(self, client):
        pid, sid = await self._setup_session_with_predictions(client)

        # Get a judgment
        judgments_resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments",
        )
        j_id = judgments_resp.json()[0]["id"]

        # Submit correct
        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments/{j_id}",
            json={"judgment": "correct"},
        )
        assert resp.status_code == 200
        assert resp.json()["judgment"] == "correct"
        assert resp.json()["judged_by"] is not None

    async def test_metrics_after_judgments(self, client):
        pid, sid = await self._setup_session_with_predictions(client)

        # Get all judgments and submit them
        judgments_resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments",
        )
        judgments = judgments_resp.json()

        # Submit: 2 correct, 1 wrong
        await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments/{judgments[0]['id']}",
            json={"judgment": "correct"},
        )
        await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments/{judgments[1]['id']}",
            json={"judgment": "correct"},
        )
        await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments/{judgments[2]['id']}",
            json={"judgment": "wrong"},
        )

        # Get metrics
        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/metrics",
        )
        assert resp.status_code == 200
        metrics = resp.json()
        assert metrics["tp"] == 2
        assert metrics["fp"] == 1
        assert metrics["total_judged"] == 3
        assert metrics["total_pending"] == 0
        assert metrics["precision"] > 0

    async def test_session_auto_completes(self, client):
        pid, sid = await self._setup_session_with_predictions(client)

        judgments_resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments",
        )
        for j in judgments_resp.json():
            await client.post(
                f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments/{j['id']}",
                json={"judgment": "correct"},
            )

        # Session should be completed
        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}",
        )
        assert resp.json()["status"] == "completed"


class TestValidation:
    async def _setup_completed_session(self, client):
        """Full setup with completed evaluation session."""
        await register_and_login(client)
        pid = await create_project(client)
        pred_id = await setup_project_with_data(client, pid)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"predictor_config_id": pred_id, "sample_config": {"size": 2}},
        )
        sid = create_resp.json()["id"]

        mock_result = PredictionResult(score=0.9, label=1, model="test", reasoning="test")
        with patch("app.evaluation.service.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor
            await client.post(
                f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/run",
            )

        judgments_resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments",
        )
        for j in judgments_resp.json():
            await client.post(
                f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/judgments/{j['id']}",
                json={"judgment": "correct"},
            )

        return pid, sid

    async def test_validate_predictor(self, client):
        pid, sid = await self._setup_completed_session(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/validate",
            json={"name": "v1.0", "threshold": 0.5},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["name"] == "v1.0"
        assert data["is_active"] is False
        assert "accuracy" in data["metrics_snapshot"]

    async def test_activate_validated(self, client):
        pid, sid = await self._setup_completed_session(client)

        # Validate
        validate_resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/validate",
            json={"name": "v1.0"},
        )
        vp_id = validate_resp.json()["id"]

        # Activate
        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/validated/{vp_id}/activate",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["validated"]["is_active"] is True
        # Activation no longer triggers bulk predictions
        assert data.get("bulk_run") is None

    async def test_list_validated(self, client):
        pid, sid = await self._setup_completed_session(client)

        await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{sid}/validate",
            json={"name": "v1.0"},
        )

        resp = await client.get(f"/api/v1/projects/{pid}/evaluation/validated")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
