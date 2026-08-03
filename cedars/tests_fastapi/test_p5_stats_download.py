"""P5 tests: project statistics + annotation export (download)."""
from datetime import datetime
from unittest.mock import MagicMock

import pytest
from bson import ObjectId

from app import database
from app.services import download_service

GOOD_PASSWORD = "Abcdef12!!"


def _proj_db(pid):
    return database.get_client()[database.project_db_name(pid)]


@pytest.fixture()
def admin_project(client):
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    pid = client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]
    return client, pid


def _seed_stats(pid):
    db_ = _proj_db(pid)
    db_["PATIENTS"].insert_many([
        {"patient_id": "1", "reviewed": True, "reviewed_by": "AdminUser"},
        {"patient_id": "2", "reviewed": False},
    ])
    now = datetime(2024, 1, 1)
    db_["ANNOTATIONS"].insert_many([
        {"_id": ObjectId(), "patient_id": "1", "token": "cancer", "isNegated": False},
        {"_id": ObjectId(), "patient_id": "1", "token": "cancer", "isNegated": False},
        {"_id": ObjectId(), "patient_id": "2", "token": "sepsis", "isNegated": False},
        {"_id": ObjectId(), "patient_id": "2", "token": "ignored", "isNegated": True},
    ])
    _ = now


def test_stats(admin_project):
    client, pid = admin_project
    _seed_stats(pid)

    resp = client.get(f"/api/v1/projects/{pid}/stats")
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["number_of_patients"] == 2
    assert body["number_of_annotated_patients"] == 2
    assert body["number_of_reviewed"] == 1
    assert body["user_review_stats"] == {"AdminUser": 1}
    # cancer 2/3 -> 66, sepsis 1/3 -> 33 (negated token excluded).
    assert body["lemma_dist"] == {"cancer": 66, "sepsis": 33}


def test_stats_available_to_annotator(admin_project):
    client, pid = admin_project
    _seed_stats(pid)
    client.post("/api/v1/auth/register", json={
        "username": "Plain", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "Plain", "password": GOOD_PASSWORD})
    assert client.get(f"/api/v1/projects/{pid}/stats").status_code == 200


def test_create_download_returns_job(admin_project):
    client, pid = admin_project
    resp = client.post(f"/api/v1/projects/{pid}/download/compact")
    assert resp.status_code == 200, resp.text
    job_id = resp.json()["job_id"]
    assert job_id

    # No worker runs the job, so it stays queued.
    status = client.get(f"/api/v1/projects/{pid}/download/check/{job_id}")
    assert status.status_code == 200
    assert status.json()["status"] in {"in_progress", "finished"}


def test_create_full_download(admin_project):
    client, pid = admin_project
    resp = client.post(f"/api/v1/projects/{pid}/download/full")
    assert resp.status_code == 200
    assert resp.json()["job_id"]


def test_list_download_files(admin_project, monkeypatch):
    client, pid = admin_project
    mock = MagicMock()
    mock.list_objects_v2.return_value = {"Contents": [{
        "Key": f"cedars_proj_{pid}/annotated_files/annotations_compact_Cohort.csv",
        "Size": 512,
        "LastModified": datetime(2024, 1, 2, 3, 4, 5),
    }]}
    monkeypatch.setattr(download_service, "s3", mock)

    resp = client.get(f"/api/v1/projects/{pid}/download/files")
    assert resp.status_code == 200, resp.text
    files = resp.json()
    assert files[0]["name"] == "annotations_compact_Cohort.csv"
    assert files[0]["last_modified"] == "2024-01-02 03:04:05"


def test_download_requires_admin(admin_project):
    client, pid = admin_project
    client.post("/api/v1/auth/register", json={
        "username": "Plain", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "Plain", "password": GOOD_PASSWORD})
    assert client.post(f"/api/v1/projects/{pid}/download/compact").status_code == 403
