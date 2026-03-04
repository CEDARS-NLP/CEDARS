"""API integration tests for predictor endpoints."""

import pytest
from httpx import AsyncClient


async def register_and_login(client: AsyncClient) -> None:
    """Register a user and login. Cookies are set automatically by httpx."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "pred@example.com", "name": "Predictor User", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "pred@example.com", "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    """Create a project and return its ID."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Pred Project", "description": "For predictor tests"},
    )
    return resp.json()["id"]


class TestPredictorCRUD:
    async def test_create_llm_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={
                "name": "GPT-4o MI Detector",
                "predictor_type": "llm",
                "config": {
                    "provider": "openai",
                    "model": "gpt-4o",
                    "event_definition": {
                        "name": "Myocardial Infarction",
                        "description": "Heart attack",
                        "include_criteria": "Positive troponin, ECG changes",
                        "exclude_criteria": "Rule-out, family history",
                    },
                },
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "GPT-4o MI Detector"
        assert data["predictor_type"] == "llm"
        assert data["is_active"] is False

    async def test_create_pines_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={
                "name": "PINES v1",
                "predictor_type": "pines",
                "config": {"pines_api_url": "http://pines:8000"},
            },
        )
        assert resp.status_code == 201
        assert resp.json()["predictor_type"] == "pines"

    async def test_list_predictors(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        for name in ["Pred A", "Pred B"]:
            await client.post(
                f"/api/v1/projects/{pid}/predictors",
                json={"name": name, "predictor_type": "llm", "config": {}},
            )

        resp = await client.get(f"/api/v1/projects/{pid}/predictors")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={"name": "Test", "predictor_type": "llm", "config": {}},
        )
        pred_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/predictors/{pred_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == pred_id

    async def test_update_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={"name": "Old Name", "predictor_type": "llm", "config": {"model": "gpt-3.5"}},
        )
        pred_id = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/projects/{pid}/predictors/{pred_id}",
            json={"name": "New Name", "config": {"model": "gpt-4o"}},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New Name"
        assert resp.json()["config"]["model"] == "gpt-4o"

    async def test_delete_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={"name": "To Delete", "predictor_type": "llm", "config": {}},
        )
        pred_id = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/projects/{pid}/predictors/{pred_id}")
        assert resp.status_code == 204

        list_resp = await client.get(f"/api/v1/projects/{pid}/predictors")
        assert len(list_resp.json()) == 0

    async def test_activate_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        # Create two predictors
        resp_a = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={"name": "A", "predictor_type": "llm", "config": {}},
        )
        resp_b = await client.post(
            f"/api/v1/projects/{pid}/predictors",
            json={"name": "B", "predictor_type": "llm", "config": {}},
        )
        id_a = resp_a.json()["id"]
        id_b = resp_b.json()["id"]

        # Activate A
        resp = await client.post(f"/api/v1/projects/{pid}/predictors/{id_a}/activate")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is True

        # Activate B -- A should be deactivated
        await client.post(f"/api/v1/projects/{pid}/predictors/{id_b}/activate")

        resp_a_check = await client.get(f"/api/v1/projects/{pid}/predictors/{id_a}")
        assert resp_a_check.json()["is_active"] is False

        resp_b_check = await client.get(f"/api/v1/projects/{pid}/predictors/{id_b}")
        assert resp_b_check.json()["is_active"] is True

    async def test_get_nonexistent_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(f"/api/v1/projects/{pid}/predictors/nonexistent")
        assert resp.status_code == 404
