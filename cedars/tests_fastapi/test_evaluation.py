"""Tests for isolated, project-local LLM evaluations."""
from datetime import date
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import database
from app.database.project_table_creation import (
    Annotations,
    EvaluationSessions,
    LLMEvaluationResults,
    Notes,
    Patients,
    PINES,
    ProjectSettings,
    Results,
    Task,
)
from app.database.db_session import session_scope
from app.database.project_table_creation import ProjectUsers
from app.routers import evaluation as evaluation_router

from . import sql_test_helpers as sql

GOOD_PASSWORD = "Abcdef12!!"


def _admin_project(client):
    client.post("/api/v1/auth/register", json={
        "username": "EvalAdmin", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False,
    })
    client.post("/api/v1/auth/login", json={
        "username": "EvalAdmin", "password": GOOD_PASSWORD,
    })
    project_id = client.post("/api/v1/projects", json={"name": "Eval cohort"}).json()["id"]
    return project_id


def _create_session(client, project_id):
    return client.post(f"/api/v1/projects/{project_id}/evaluation/sessions", json={
        "event_name": "Test event",
        "event_description": "Evaluation-only metadata",
        "include_criteria": "include",
        "exclude_criteria": "exclude",
        "sample_patient_ids": ["P1"],
    })


def test_evaluation_reads_inputs_and_persists_without_workflow_mutations(client, monkeypatch):
    project_id = _admin_project(client)
    sql.seed_patient(project_id, "P1", index_no=1)
    sql.seed_note(project_id, "N1", "P1", "A sample note.", date(2024, 1, 1))

    response = client.get(f"/api/v1/projects/{project_id}/evaluation/patients")
    assert response.status_code == 200, response.text
    assert response.json() == [{"patient_id": "P1", "note_count": 1}]
    response = client.get(f"/api/v1/projects/{project_id}/evaluation/patients/P1/notes")
    assert response.status_code == 200, response.text
    assert response.json()[0]["note_id"] == "N1"

    created = _create_session(client, project_id)
    assert created.status_code == 201, created.text
    session_id = created.json()["eval_session_id"]

    engine = database.get_project_engine(project_id)
    with session_scope(engine) as db_session:
        settings = db_session.scalar(select(ProjectSettings))
        settings.pines_url = "http://pines.test"
        settings.is_pines_server_enabled = True

    monkeypatch.setattr(
        evaluation_router,
        "get_prediction",
        lambda _url, _text: (0.83, "positive", "test-model", 0.5),
    )
    response = client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/run",
        json={"note_ids": ["N1"]},
    )
    assert response.status_code == 200, response.text
    assert response.json()[0]["predicted_score"] == 0.83

    response = client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions/"
        f"{session_id}/results/{response.json()[0]['evaluation_result_id']}/judge",
        json={"judgment": "correct"},
    )
    assert response.status_code == 200, response.text
    response = client.get(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/metrics"
    )
    assert response.json()["accuracy"] == 1.0

    response = client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/finalize"
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == "completed"

    with Session(engine) as db_session:
        assert db_session.scalar(select(func.count()).select_from(LLMEvaluationResults)) == 1
        assert db_session.scalar(select(func.count()).select_from(EvaluationSessions)) == 1
        assert db_session.scalar(select(func.count()).select_from(Patients)) == 1
        assert db_session.scalar(select(func.count()).select_from(Notes)) == 1
        assert db_session.scalar(select(func.count()).select_from(Annotations)) == 0
        assert db_session.scalar(select(func.count()).select_from(PINES)) == 0
        assert db_session.scalar(select(func.count()).select_from(Results)) == 0
        assert db_session.scalar(select(func.count()).select_from(Task)) == 0
        assert db_session.scalar(select(func.count()).select_from(ProjectUsers)) == 3
        assert db_session.get(Patients, "P1").pines_status is None


def test_evaluation_access_is_admin_only(client):
    project_id = _admin_project(client)
    client.post("/api/v1/auth/register", json={
        "username": "EvalAnnotator", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False,
    })
    client.post("/api/v1/auth/login", json={
        "username": "EvalAnnotator", "password": GOOD_PASSWORD,
    })
    response = client.get(f"/api/v1/projects/{project_id}/evaluation/patients")
    assert response.status_code == 403


def test_evaluation_session_cannot_reference_another_project_patient(client):
    first_project_id = _admin_project(client)
    sql.seed_patient(first_project_id, "PRIVATE-ONE")

    client.post("/api/v1/auth/logout")
    client.post("/api/v1/auth/login", json={
        "username": "EvalAdmin", "password": GOOD_PASSWORD,
    })
    second_project_id = client.post(
        "/api/v1/projects", json={"name": "Separate cohort"}
    ).json()["id"]

    response = client.post(
        f"/api/v1/projects/{second_project_id}/evaluation/sessions",
        json={"event_name": "No cross-project access", "sample_patient_ids": ["PRIVATE-ONE"]},
    )
    assert response.status_code == 400