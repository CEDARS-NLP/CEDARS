"""API integration tests for data source endpoints."""

import json
from unittest.mock import patch, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient


# -- Helpers ───────────────────────────────────────────────────────


async def register_and_login(client: AsyncClient) -> None:
    """Register a user and login. Cookies are set automatically by httpx."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "test@example.com", "name": "Test User", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "test@example.com", "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    """Create a project and return its ID."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Test Project", "description": "Test"},
    )
    return resp.json()["id"]


# -- Data Source CRUD tests ────────────────────────────────────────


class TestDataSourceCRUD:
    async def test_create_data_source(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={
                "name": "test.csv",
                "connector_type": "file_upload",
                "config": {"s3_key": "test.csv", "file_type": "csv",
                           "column_mapping": {"patient_id": "MRN", "text": "note"}},
            },
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test.csv"
        assert data["connector_type"] == "file_upload"
        assert data["status"] == "pending"

    async def test_list_data_sources(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        # Create two data sources
        for name in ["a.csv", "b.csv"]:
            await client.post(
                f"/api/v1/projects/{project_id}/data/sources",
                json={"name": name, "connector_type": "file_upload", "config": {}},
            )

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/sources",
        )
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_get_data_source(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={"name": "test.csv", "connector_type": "file_upload", "config": {}},
        )
        ds_id = create_resp.json()["id"]

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/sources/{ds_id}",
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == ds_id

    async def test_get_nonexistent_data_source(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        resp = await client.get(
            f"/api/v1/projects/{project_id}/data/sources/nonexistent",
        )
        assert resp.status_code == 404

    async def test_delete_data_source(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={"name": "test.csv", "connector_type": "file_upload", "config": {}},
        )
        ds_id = create_resp.json()["id"]

        resp = await client.delete(
            f"/api/v1/projects/{project_id}/data/sources/{ds_id}",
        )
        assert resp.status_code == 204

        # Should be gone from listing
        list_resp = await client.get(
            f"/api/v1/projects/{project_id}/data/sources",
        )
        assert len(list_resp.json()) == 0


# -- Ingestion tests ───────────────────────────────────────────────


class TestIngestion:
    async def test_ingest_csv_data(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        # Create data source with config
        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={
                "name": "test.csv",
                "connector_type": "file_upload",
                "config": {
                    "s3_key": "test.csv",
                    "file_type": "csv",
                    "column_mapping": {"patient_id": "MRN", "text_id": "text_id", "text": "note_text", "note_date": "date"},
                },
            },
        )
        ds_id = create_resp.json()["id"]

        # Mock S3 download
        csv_data = b"MRN,text_id,note_text,date\nP001,N001,Note one,2024-01-01\nP001,N002,Note two,2024-01-02\nP002,N003,Note three,2024-01-03"
        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            resp = await client.post(
                f"/api/v1/projects/{project_id}/data/sources/{ds_id}/ingest",
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "completed"
        assert "3 rows" in data["message"]

        # Verify patients created
        patients_resp = await client.get(
            f"/api/v1/projects/{project_id}/data/patients",
        )
        assert patients_resp.status_code == 200
        patients = patients_resp.json()
        assert len(patients) == 2  # P001 and P002

        # Find P001 and check note count
        p001 = next(p for p in patients if p["patient_id_ext"] == "P001")
        assert p001["note_count"] == 2

        # Verify notes for P001
        notes_resp = await client.get(
            f"/api/v1/projects/{project_id}/data/patients/{p001['id']}/notes",
        )
        assert notes_resp.status_code == 200
        notes = notes_resp.json()
        assert len(notes) == 2

    async def test_ingest_invalid_config(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={
                "name": "bad.csv",
                "connector_type": "file_upload",
                "config": {},  # Missing s3_key and column_mapping
            },
        )
        ds_id = create_resp.json()["id"]

        resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources/{ds_id}/ingest",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "failed"

    async def test_ingest_nonexistent_source(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources/nonexistent/ingest",
        )
        assert resp.status_code == 404


# -- File upload endpoint tests ────────────────────────────────────


class TestFileUpload:
    async def test_upload_csv_file(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        csv_content = b"patient_id,text,note_date\nP001,Hello world,2024-01-01"
        mapping = json.dumps({"patient_id": "patient_id", "text_id": "patient_id", "text": "text", "note_date": "note_date"})

        with patch("app.connectors.router.upload_file") as mock_upload:
            mock_upload.return_value = "projects/p/uploads/test.csv"
            resp = await client.post(
                f"/api/v1/projects/{project_id}/data/upload",
                files={"file": ("test.csv", csv_content, "text/csv")},
                data={"column_mapping": mapping},
            )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "test.csv"
        assert data["connector_type"] == "file_upload"
        assert "s3_key" in data["config"]

    async def test_upload_unsupported_filetype(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{project_id}/data/upload",
            files={"file": ("data.xlsx", b"fake data", "application/xlsx")},
        )
        assert resp.status_code == 400

    async def test_upload_requires_auth(self, client):
        resp = await client.post(
            "/api/v1/projects/fake/data/upload",
            files={"file": ("test.csv", b"data", "text/csv")},
        )
        assert resp.status_code in (401, 403)


# -- Preview tests ─────────────────────────────────────────────────


class TestPreview:
    async def test_preview_data_source(self, client):
        await register_and_login(client)
        project_id = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{project_id}/data/sources",
            json={
                "name": "test.csv",
                "connector_type": "file_upload",
                "config": {
                    "s3_key": "test.csv",
                    "file_type": "csv",
                    "column_mapping": {"patient_id": "MRN", "text": "note"},
                },
            },
        )
        ds_id = create_resp.json()["id"]

        csv_data = b"MRN,note\nP001,Hello\nP002,World"
        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            resp = await client.get(
                f"/api/v1/projects/{project_id}/data/sources/{ds_id}/preview?limit=1",
            )
        assert resp.status_code == 200
        data = resp.json()
        assert data["columns"] == ["MRN", "note"]
        assert len(data["rows"]) == 1
        assert data["total_available"] == 2
