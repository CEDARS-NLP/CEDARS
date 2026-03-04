"""Tests for project stats API."""
import pytest


async def _setup_project(client):
    """Register, login, create project, return project_id."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "stats@test.com", "name": "Stats User", "password": "testpass123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "stats@test.com", "password": "testpass123"},
    )
    resp = await client.post(
        "/api/v1/projects", json={"name": "Stats Project"}
    )
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_project_stats_empty(app, client):
    """Stats for a new project return zero counts."""
    project_id = await _setup_project(client)
    resp = await client.get(f"/api/v1/projects/{project_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patients"]["total"] == 0
    assert data["notes"]["total"] == 0
    assert data["sentences"]["total"] == 0
    assert data["annotations"]["total"] == 0
    assert data["annotators"] == []
    assert data["jobs"]["latest"] is None
    assert data["jobs"]["active_count"] == 0
    assert data["jobs"]["failed_count"] == 0


@pytest.mark.asyncio
async def test_project_stats_with_data(app, client):
    """Stats reflect uploaded data."""
    project_id = await _setup_project(client)

    from app.common.database import get_session
    from app.connectors.models import Patient, Note, PatientStatus
    from app.nlp.models import Sentence
    from datetime import datetime, UTC

    async for session in app.dependency_overrides[get_session]():
        p = Patient(
            project_id=project_id, patient_id_ext="P001", status=PatientStatus.NLP_COMPLETE
        )
        session.add(p)
        await session.flush()

        n = Note(
            project_id=project_id,
            patient_id=p.id,
            text_id="N001",
            note_date=datetime.now(UTC),
            text="Patient has chest pain.",
        )
        session.add(n)
        await session.flush()

        s = Sentence(
            note_id=n.id,
            project_id=project_id,
            sentence_number=0,
            text="Patient has chest pain.",
            start_pos=0,
            end_pos=24,
            is_target=True,
        )
        session.add(s)
        await session.commit()

    resp = await client.get(f"/api/v1/projects/{project_id}/stats")
    assert resp.status_code == 200
    data = resp.json()
    assert data["patients"]["total"] == 1
    assert data["patients"]["by_status"]["nlp_complete"] == 1
    assert data["notes"]["total"] == 1
    assert data["sentences"]["total"] == 1
    assert data["sentences"]["target"] == 1
