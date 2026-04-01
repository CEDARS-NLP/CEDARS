"""Tests for sequential evaluation review endpoints."""

import pytest


async def register_and_login(client, email="reviewer@test.com"):
    """Register and login a user."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Reviewer", "password": "testpass123"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 200


async def create_project(client, name="Review Test"):
    """Create a project, return its ID."""
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_eval_session(client, project_id):
    """Create an evaluation session, return the response data."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "stroke", "type": "include"}]},
    )
    assert resp.status_code == 201
    return resp.json()


@pytest.mark.asyncio
async def test_next_unreviewed_returns_404_when_no_results(client):
    """Next endpoint returns 404 when no unreviewed results exist."""
    await register_and_login(client)
    project_id = await create_project(client)
    session = await create_eval_session(client, project_id)

    resp = await client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}/results/next"
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_next_unreviewed_returns_result(client, app):
    """Full flow: create session, add patient result, get next unreviewed."""
    await register_and_login(client)
    project_id = await create_project(client)
    session = await create_eval_session(client, project_id)

    # Inject a PatientResult using the test database session
    from app.common.database import get_session
    from app.evaluation.models import PatientResult, PatientResultStatus

    # Get the overridden test session from the app fixture
    async for db in app.dependency_overrides[get_session]():
        pr = PatientResult(
            session_id=session["id"],
            patient_id="fake-patient-1",
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Test reasoning",
            predicted_score=0.9,
        )
        db.add(pr)
        await db.commit()
        break  # Only need one iteration

    resp = await client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}/results/next"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["patient_id"] == "fake-patient-1"
    assert data["finding_label"] == "positive"
    assert data["review_judgment"] is None
    assert data["position"] == 1
    assert data["total_unreviewed"] == 1
    assert data["total_results"] == 1


# Helper functions to reduce duplication
async def _register_and_login(client):
    """Register and login test user."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "test@test.com", "name": "Test", "password": "testpass123"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": "test@test.com", "password": "testpass123"},
    )
    assert resp.status_code == 200


async def _create_project(client):
    """Create project and return ID."""
    resp = await client.post("/api/v1/projects", json={"name": "Test Project"})
    assert resp.status_code == 201
    return resp.json()["id"]


@pytest.mark.asyncio
async def test_result_notes_returns_full_context(client, app):
    """Notes endpoint returns full note text for evidence review."""
    await _register_and_login(client)
    project_id = await _create_project(client)

    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "stroke", "type": "include"}]},
    )
    session_id = resp.json()["id"]

    from app.common.database import get_session
    from app.connectors.models import Patient, Note
    from app.evaluation.models import PatientResult, PatientResultStatus, SearchMatch
    from datetime import datetime, UTC

    # Use the test's overridden database session
    async for db in app.dependency_overrides[get_session]():
        patient = Patient(project_id=project_id, patient_id_ext="MRN001")
        db.add(patient)
        await db.flush()

        note = Note(
            project_id=project_id,
            patient_id=patient.id,
            text_id="NOTE001",
            note_date=datetime(2026, 1, 15, tzinfo=UTC),
            text="Patient presented with acute ischemic stroke symptoms.",
        )
        db.add(note)
        await db.flush()

        sm = SearchMatch(
            session_id=session_id,
            patient_id=patient.id,
            note_id=note.id,
            matched_tokens=["stroke"],
            match_positions=[{"start": 40, "end": 46, "token": "stroke"}],
        )
        db.add(sm)

        pr = PatientResult(
            session_id=session_id,
            patient_id=patient.id,
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Acute stroke confirmed",
            finding_evidence=[{
                "note_id": note.id,
                "text": "acute ischemic stroke symptoms",
                "note_date": "2026-01-15",
            }],
            predicted_score=0.95,
            notes_searched=1,
            notes_matched=1,
        )
        db.add(pr)
        await db.commit()

        result_id = pr.id
        break  # Only need one iteration

    resp = await client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/results/{result_id}/notes"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["notes"]) == 1
    assert data["notes"][0]["text_id"] == "NOTE001"
    assert "stroke" in data["notes"][0]["text"]
    assert len(data["notes"][0]["matched_tokens"]) > 0
    assert data["search_keywords"] == ["stroke"]
