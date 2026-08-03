"""P6 tests: internal processes + project termination."""
import pytest

from app import database
from app.routers import internal as internal_router

GOOD_PASSWORD = "Abcdef12!!"


@pytest.fixture()
def admin_project(client):
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    pid = client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]
    return client, pid


def test_internal_status(admin_project):
    client, pid = admin_project
    resp = client.get(f"/api/v1/projects/{pid}/internal")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert "rq_dashboard_url" in body
    assert body["queue_length"] == 0
    assert body["failed_jobs"] == 0


def test_update_results_and_unlock_all(admin_project):
    client, pid = admin_project
    r1 = client.post(f"/api/v1/projects/{pid}/internal/update_results")
    assert r1.status_code == 200 and r1.json()["job_id"]
    r2 = client.post(f"/api/v1/projects/{pid}/internal/unlock_all")
    assert r2.status_code == 200 and r2.json()["job_id"]


def test_pines_status_mocked(admin_project, monkeypatch):
    client, pid = admin_project
    monkeypatch.setattr(internal_router, "check_is_pines_available", lambda *a, **k: True)
    resp = client.get(f"/api/v1/projects/{pid}/internal/pines/status")
    assert resp.status_code == 200
    assert resp.json()["available"] is True


def test_pines_status_handles_unreachable(admin_project, monkeypatch):
    client, pid = admin_project

    def _boom(*a, **k):
        raise RuntimeError("unreachable")

    monkeypatch.setattr(internal_router, "check_is_pines_available", _boom)
    resp = client.get(f"/api/v1/projects/{pid}/internal/pines/status")
    assert resp.status_code == 200
    assert resp.json()["available"] is False


def test_internal_requires_admin(admin_project):
    client, pid = admin_project
    client.post("/api/v1/auth/register", json={
        "username": "Plain", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "Plain", "password": GOOD_PASSWORD})
    assert client.get(f"/api/v1/projects/{pid}/internal").status_code == 403


def test_terminate_project(admin_project):
    client, pid = admin_project
    # Seed some data into the project database.
    database.get_client()[database.project_db_name(pid)]["PATIENTS"].insert_one(
        {"patient_id": "1"})

    resp = client.delete(f"/api/v1/projects/{pid}")
    assert resp.status_code == 200
    assert resp.json()["message"] == "Project Terminated."

    # Registry entry gone -> project no longer listed or retrievable.
    assert client.get("/api/v1/projects").json() == []
    assert client.get(f"/api/v1/projects/{pid}").status_code == 404
