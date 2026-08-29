"""P2 tests: data upload + ingestion (S3 stubbed, ingest runs against a throwaway SQLite db)."""
import os
import shutil
from unittest.mock import MagicMock

import pytest

from app.services import data_service

GOOD_PASSWORD = "Abcdef12!!"
SAMPLE_CSV = os.path.join(os.path.dirname(__file__), "..", "tests", "simulated_patients.csv")


@pytest.fixture()
def admin_client(client):
    """A logged-in admin client with one project; returns (client, project_id)."""
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    pid = client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]
    return client, pid


@pytest.fixture()
def stub_s3(monkeypatch):
    """Replace the S3 client so download returns the bundled sample CSV."""
    mock = MagicMock()

    def _download_file(_bucket, _key, local_filename):
        shutil.copyfile(SAMPLE_CSV, local_filename)

    mock.download_file.side_effect = _download_file
    mock.list_objects_v2.return_value = {"Contents": [
        {"Key": "cedars_proj_x/uploaded_files/simulated_patients.csv", "Size": 2048}]}
    monkeypatch.setattr(data_service, "s3", mock)
    return mock


def test_upload_requires_admin(client):
    client.post("/api/v1/auth/register", json={
        "username": "AdminUser", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    client.post("/api/v1/auth/register", json={
        "username": "Plain", "password": GOOD_PASSWORD,
        "confirm_password": GOOD_PASSWORD, "is_admin": False})
    # Admin creates a project.
    client.post("/api/v1/auth/login",
                json={"username": "AdminUser", "password": GOOD_PASSWORD})
    pid = client.post("/api/v1/projects", json={"name": "Cohort"}).json()["id"]
    # Annotator cannot upload.
    client.post("/api/v1/auth/login",
                json={"username": "Plain", "password": GOOD_PASSWORD})
    resp = client.post(f"/api/v1/projects/{pid}/data/upload",
                       data={"miniofile": "x/uploaded_files/simulated_patients.csv"})
    assert resp.status_code == 403


def test_ingest_from_existing_s3_file(admin_client, stub_s3):
    client, pid = admin_client
    key = f"cedars_proj_{pid}/uploaded_files/simulated_patients.csv"
    resp = client.post(f"/api/v1/projects/{pid}/data/upload", data={"miniofile": key})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["total_rows"] > 0
    assert body["total_patients"] > 0
    assert body["filename"] == key

    # Verify the project's database was populated.
    from app import database
    from app.database.project_table_creation import Notes, Patients
    from sqlalchemy import func, select
    from sqlalchemy.orm import Session

    engine = database.get_project_engine(pid)
    with Session(engine) as session:
        note_count = session.execute(select(func.count()).select_from(Notes)).scalar_one()
        patient_count = session.execute(select(func.count()).select_from(Patients)).scalar_one()
    assert note_count == body["total_rows"]
    assert patient_count == body["total_patients"]


def test_list_files(admin_client, stub_s3):
    client, pid = admin_client
    resp = client.get(f"/api/v1/projects/{pid}/data/files")
    assert resp.status_code == 200, resp.text
    names = [f["name"] for f in resp.json()]
    assert "simulated_patients.csv" in names


def test_upload_rejects_bad_extension(admin_client, stub_s3):
    client, pid = admin_client
    files = {"file": ("notes.txt", b"hello", "text/plain")}
    resp = client.post(f"/api/v1/projects/{pid}/data/upload", files=files)
    assert resp.status_code == 400
