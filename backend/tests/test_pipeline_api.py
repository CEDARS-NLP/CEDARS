"""API integration tests for pipeline EventConfig CRUD."""

import pytest
from httpx import AsyncClient


async def register_and_login(client: AsyncClient) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": "pipeline@example.com", "name": "Pipeline User", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "pipeline@example.com", "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Pipeline Project", "description": "For pipeline tests"},
    )
    return resp.json()["id"]


EVENT_CONFIG_BODY = {
    "name": "Myocardial Infarction",
    "description": "Confirmed MI event detection",
    "include_criteria": "Troponin elevation, ECG changes, chest pain",
    "exclude_criteria": "Rule-out, family history only",
    "search_patterns": {
        "keywords": ["troponin", "MI"],
        "regex_patterns": [r"troponin.*elevated"],
        "exclusion_patterns": ["rule.?out"],
    },
    "llm_provider": "ollama",
    "llm_model": "llama3",
}


class TestEventConfigCRUD:
    async def test_create_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json=EVENT_CONFIG_BODY,
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Myocardial Infarction"
        assert data["is_committed"] is False
        assert data["llm_provider"] == "ollama"

    async def test_list_event_configs(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        await client.post(f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY)
        await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json={**EVENT_CONFIG_BODY, "name": "DVT Detection"},
        )

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/events")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2

    async def test_get_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/events/{eid}")
        assert resp.status_code == 200
        assert resp.json()["id"] == eid

    async def test_get_nonexistent_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/events/nonexistent")
        assert resp.status_code == 404

    async def test_update_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}",
            json={"name": "Updated MI Detection", "llm_model": "llama3.1"},
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Updated MI Detection"
        assert resp.json()["llm_model"] == "llama3.1"

    async def test_delete_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/projects/{pid}/pipeline/events/{eid}")
        assert resp.status_code == 204

        # Verify it's gone from the list
        list_resp = await client.get(f"/api/v1/projects/{pid}/pipeline/events")
        assert len(list_resp.json()) == 0

    async def test_commit_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit",
            json={"confidence_threshold": 0.85},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["is_committed"] is True
        assert data["confidence_threshold"] == 0.85

    async def test_cannot_update_committed_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        await client.post(f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit", json={})

        resp = await client.put(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}",
            json={"name": "Should Fail"},
        )
        assert resp.status_code == 400

    async def test_cannot_delete_committed_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        await client.post(f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit", json={})

        resp = await client.delete(f"/api/v1/projects/{pid}/pipeline/events/{eid}")
        assert resp.status_code == 400

    async def test_cross_project_access_returns_404(self, client):
        """EventConfig from project A should not be accessible via project B."""
        await register_and_login(client)
        pid_a = await create_project(client)
        pid_b = (await client.post(
            "/api/v1/projects",
            json={"name": "Other Project", "description": "B"},
        )).json()["id"]

        create_resp = await client.post(
            f"/api/v1/projects/{pid_a}/pipeline/events", json=EVENT_CONFIG_BODY
        )
        eid = create_resp.json()["id"]

        # Try to access via project B — should 404
        resp = await client.get(f"/api/v1/projects/{pid_b}/pipeline/events/{eid}")
        assert resp.status_code == 404

    async def test_description_max_length_validation(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events",
            json={**EVENT_CONFIG_BODY, "description": "x" * 5001},
        )
        assert resp.status_code == 422
