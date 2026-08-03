"""P3 tests: query save + NLP dispatch (RQ backed by fakeredis, no worker runs)."""
import pytest

from app import database, queues

GOOD_PASSWORD = "Abcdef12!!"


def _project_db(pid):
    return database.get_client()[database.project_db_name(pid)]


def _seed_patients(pid, n=3):
    _project_db(pid)["PATIENTS"].insert_many([
        {"patient_id": str(i), "reviewed": False, "locked": False, "index_no": i}
        for i in range(1, n + 1)
    ])


@pytest.fixture()
def admin_project(client):
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    pid = client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]
    return client, pid


def test_save_query_dispatches_nlp(admin_project):
    client, pid = admin_project
    _seed_patients(pid, 3)

    resp = client.put(f"/api/v1/projects/{pid}/query", json={
        "query": "cancer OR embolism", "nlp_apply": False,
        "hide_duplicates": True, "skip_after_event": False})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["new_query"] is True
    assert body["dispatched"] == 3

    # One job per patient landed on the (fake) task queue, project-namespaced.
    job_ids = queues.task_queue.job_ids
    assert len(job_ids) == 3
    assert all(jid.startswith(f"spacy:{pid}:") for jid in job_ids)


def test_get_query_returns_saved(admin_project):
    client, pid = admin_project
    _seed_patients(pid, 1)
    client.put(f"/api/v1/projects/{pid}/query", json={
        "query": "sepsis", "nlp_apply": True,
        "hide_duplicates": False, "skip_after_event": True})

    got = client.get(f"/api/v1/projects/{pid}/query").json()
    assert got["query"] == "sepsis"
    assert got["nlp_apply"] is True
    assert got["hide_duplicates"] is False
    assert got["skip_after_event"] is True


def test_nlp_run_and_status(admin_project):
    client, pid = admin_project
    _seed_patients(pid, 2)

    run = client.post(f"/api/v1/projects/{pid}/nlp/run")
    assert run.status_code == 200, run.text
    assert run.json()["dispatched"] == 2

    status = client.get(f"/api/v1/projects/{pid}/nlp/status").json()
    assert status["total_patients"] == 2
    # No worker executed the jobs, so no TASK docs were created yet.
    assert status["tasks_in_progress"] == 0
    assert status["tasks_completed"] == 0


def test_query_requires_admin(admin_project):
    client, pid = admin_project
    client.post("/api/v1/auth/register", json={
        "username": "Plain", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "Plain", "password": GOOD_PASSWORD})
    resp = client.put(f"/api/v1/projects/{pid}/query", json={"query": "x"})
    assert resp.status_code == 403
