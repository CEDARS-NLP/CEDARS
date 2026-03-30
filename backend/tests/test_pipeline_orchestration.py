"""Tests for pipeline run orchestration (dispatch, cancel, retry, stats)."""

from datetime import UTC, datetime

import pytest
from httpx import AsyncClient

from tests.test_pipeline_api import EVENT_CONFIG_BODY, create_project, register_and_login


async def _seed_patients(app, project_id: str, count: int = 3) -> list[str]:
    """Insert patients + notes directly into the database."""
    from app.common.database import get_session
    from app.connectors.models import Note, Patient

    patient_ids = []
    async for session in app.dependency_overrides[get_session]():
        for i in range(count):
            p = Patient(project_id=project_id, patient_id_ext=f"P{i:03d}")
            session.add(p)
            await session.flush()
            patient_ids.append(p.id)

            n = Note(
                project_id=project_id,
                patient_id=p.id,
                text_id=f"N{i:03d}",
                note_date=datetime(2025, 1, i + 1, tzinfo=UTC),
                text=f"Patient P{i:03d} presents with troponin elevation at {i + 1}.0 ng/mL and chest pain.",
            )
            session.add(n)
        await session.commit()
    return patient_ids


async def _create_and_get_event_config(client: AsyncClient, pid: str) -> str:
    resp = await client.post(
        f"/api/v1/projects/{pid}/pipeline/events",
        json=EVENT_CONFIG_BODY,
    )
    return resp.json()["id"]


class TestRunSample:
    async def test_dispatch_sample_run(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=5)
        eid = await _create_and_get_event_config(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_type"] == "sample"
        assert data["total_patients"] == 2
        assert data["status"] == "queued"
        assert data["sample_size"] == 2

    async def test_sample_run_no_patients_returns_400(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        eid = await _create_and_get_event_config(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 5},
        )
        assert resp.status_code == 400


class TestRunFull:
    async def test_full_run_requires_committed_config(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid)
        eid = await _create_and_get_event_config(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-full",
        )
        assert resp.status_code == 400
        assert "committed" in resp.json()["detail"].lower()

    async def test_dispatch_full_run(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=3)
        eid = await _create_and_get_event_config(client, pid)

        await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/commit",
            json={"confidence_threshold": 0.8},
        )

        resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-full",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["run_type"] == "full"
        assert data["total_patients"] == 3


class TestConcurrentRunRejection:
    async def test_rejects_concurrent_run_same_config(self, app, client):
        """Decision #35: 409-style conflict for concurrent runs."""
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=5)
        eid = await _create_and_get_event_config(client, pid)

        resp1 = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        assert resp1.status_code == 200

        resp2 = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        assert resp2.status_code == 400
        assert "active" in resp2.json()["detail"].lower()


class TestRunManagement:
    async def test_list_runs(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=5)
        eid = await _create_and_get_event_config(client, pid)

        await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs")
        assert resp.status_code == 200
        assert len(resp.json()) == 1

    async def test_get_run(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=5)
        eid = await _create_and_get_event_config(client, pid)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 2},
        )
        run_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs/{run_id}")
        assert resp.status_code == 200
        assert resp.json()["id"] == run_id

    async def test_get_run_stats(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=3)
        eid = await _create_and_get_event_config(client, pid)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 3},
        )
        run_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 3
        assert data["queued"] == 3

    async def test_get_run_tasks(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=3)
        eid = await _create_and_get_event_config(client, pid)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 3},
        )
        run_id = create_resp.json()["id"]

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/tasks")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    async def test_cancel_run(self, app, client):
        await register_and_login(client)
        pid = await create_project(client)
        await _seed_patients(app, pid, count=3)
        eid = await _create_and_get_event_config(client, pid)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/pipeline/events/{eid}/run-sample",
            json={"sample_size": 3},
        )
        run_id = create_resp.json()["id"]

        resp = await client.post(f"/api/v1/projects/{pid}/pipeline/runs/{run_id}/cancel")
        assert resp.status_code == 200
        assert resp.json()["is_cancelled"] is True
        assert resp.json()["status"] == "cancelled"

    async def test_nonexistent_run_returns_404(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(f"/api/v1/projects/{pid}/pipeline/runs/nonexistent")
        assert resp.status_code == 404
