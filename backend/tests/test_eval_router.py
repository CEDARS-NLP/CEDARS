"""Tests for the unified evaluation session router."""

import pytest


async def register_and_login(client, email="eval@test.com"):
    """Register and login a user."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Eval User", "password": "testpass123"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 200


async def create_project(client, name="Eval Project"):
    """Create a project, return its ID."""
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_eval_session(client, project_id):
    """Create an evaluation session, return the response data."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "troponin", "type": "include"}]},
    )
    assert resp.status_code == 201
    return resp.json()


class TestSessionCRUD:
    """Session create, list, get, discard."""

    async def test_create_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"search_queries": [{"query": "troponin", "type": "include"}]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["project_id"] == pid
        assert len(data["search_queries"]) == 1

    async def test_list_sessions(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await create_eval_session(client, pid)

        resp = await client.get(f"/api/v1/projects/{pid}/evaluation/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 1

    async def test_get_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == session["id"]

    async def test_get_session_not_found(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/nonexistent"
        )
        assert resp.status_code == 404

    async def test_discard_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.delete(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

    async def test_create_blocked_by_existing_draft(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await create_eval_session(client, pid)

        # Second create should fail
        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"search_queries": []},
        )
        assert resp.status_code == 409


class TestQueries:
    """Update and execute search queries."""

    async def test_update_queries(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.put(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/queries",
            json={
                "search_queries": [
                    {"query": "MI OR myocardial", "type": "include"},
                    {"query": "ruled out", "type": "exclude"},
                ]
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["search_queries"]) == 2

    async def test_execute_queries(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/queries/execute"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sample_patients" in data
        assert "matched_patients" in data


class TestEventConfig:
    """Event configuration update."""

    async def test_update_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.put(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/event-config",
            json={
                "event_name": "Myocardial Infarction",
                "event_description": "A heart attack event",
                "include_criteria": "troponin elevation, ST changes",
                "exclude_criteria": "ruled out",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_name"] == "Myocardial Infarction"


class TestResultsAndMetrics:
    """Results listing, funnel stats, and metrics."""

    async def test_get_results_empty(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/results"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_get_funnel(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/funnel"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sample_patients" in data
        assert "matched_patients" in data
        assert "filter_percent" in data

    async def test_get_metrics_empty(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/metrics"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reviewed"] == 0
        assert data["accuracy"] == 0.0
        assert data["tp"] == 0


class TestCommit:
    """Session commit endpoint."""

    async def test_commit_requires_reviewing_status(self, client):
        """DRAFT session cannot be committed."""
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/commit",
            json={},
        )
        # Session is in DRAFT, should fail
        assert resp.status_code == 409
