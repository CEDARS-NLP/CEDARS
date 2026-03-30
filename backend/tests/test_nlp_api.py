"""API integration tests for NLP pipeline endpoints."""

from unittest.mock import patch

import pytest
from httpx import AsyncClient


async def register_and_login(client: AsyncClient) -> None:
    """Register a user and login. Cookies are set automatically by httpx."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": "nlp@example.com", "name": "NLP User", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": "nlp@example.com", "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    """Create a project and return its ID."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "NLP Project", "description": "For NLP tests"},
    )
    return resp.json()["id"]


class TestSearchQueryCRUD:
    async def test_create_query(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/nlp/queries",
            json={"name": "MI detection", "query": "troponin OR myocardial AND !suspected"},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["query"] == "troponin OR myocardial AND !suspected"
        assert data["is_active"] is True

    async def test_list_queries(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        for q in ["DVT", "PE"]:
            await client.post(
                f"/api/v1/projects/{pid}/nlp/queries",
                json={"query": q},
            )

        resp = await client.get(f"/api/v1/projects/{pid}/nlp/queries")
        assert resp.status_code == 200
        assert len(resp.json()) == 2

    async def test_update_query(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/nlp/queries",
            json={"query": "old query"},
        )
        qid = create_resp.json()["id"]

        resp = await client.put(
            f"/api/v1/projects/{pid}/nlp/queries/{qid}",
            json={"query": "new query", "is_active": False},
        )
        assert resp.status_code == 200
        assert resp.json()["query"] == "new query"
        assert resp.json()["is_active"] is False

    async def test_delete_query(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        create_resp = await client.post(
            f"/api/v1/projects/{pid}/nlp/queries",
            json={"query": "to delete"},
        )
        qid = create_resp.json()["id"]

        resp = await client.delete(f"/api/v1/projects/{pid}/nlp/queries/{qid}")
        assert resp.status_code == 204

        list_resp = await client.get(f"/api/v1/projects/{pid}/nlp/queries")
        assert len(list_resp.json()) == 0


class TestNlpProcessing:
    @pytest.fixture(autouse=True)
    def _force_sync_dispatch(self):
        """Force dispatch_nlp_job to use the synchronous fallback path.

        When Redis is running locally, ARQ enqueue succeeds but no worker
        processes the job, leaving it stuck in 'pending'. Patching create_pool
        to raise ensures the sync fallback is used in tests.
        """
        with patch("arq.create_pool", side_effect=ConnectionError("no Redis in tests")):
            yield

    async def _setup_project_with_notes(self, client, pid):
        """Create a data source and ingest notes for testing."""
        from unittest.mock import patch

        # Create data source
        create_resp = await client.post(
            f"/api/v1/projects/{pid}/data/sources",
            json={
                "name": "test.csv",
                "connector_type": "file_upload",
                "config": {
                    "s3_key": "test.csv",
                    "file_type": "csv",
                    "column_mapping": {
                        "patient_id": "patient_id",
                        "text_id": "text_id",
                        "text": "text",
                        "note_date": "date",
                    },
                },
            },
        )
        ds_id = create_resp.json()["id"]

        csv_data = (
            b"patient_id,text_id,text,date\n"
            b"P001,N001,Patient presents with troponin elevation and chest pain.,2026-01-10\n"
            b"P001,N002,No evidence of DVT was found in lower extremities.,2026-01-11\n"
            b"P002,N003,Confirmed myocardial infarction with ST elevation.,2026-01-12\n"
        )
        import asyncio
        with patch("app.connectors.file_upload.download_file", return_value=csv_data):
            await client.post(
                f"/api/v1/projects/{pid}/data/sources/{ds_id}/ingest",
            )
            await asyncio.sleep(0.5)

    async def test_run_nlp_pipeline(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await self._setup_project_with_notes(client, pid)

        # Add a search query
        await client.post(
            f"/api/v1/projects/{pid}/nlp/queries",
            json={"query": "troponin OR myocardial"},
        )

        # Run NLP (dispatched via BackgroundJob, runs as background task)
        import asyncio
        resp = await client.post(f"/api/v1/projects/{pid}/nlp/run")
        assert resp.status_code == 200
        data = resp.json()
        assert "job_id" in data
        assert data["status"] in ("pending", "running", "completed")
        await asyncio.sleep(0.5)

        # Check stats
        stats_resp = await client.get(f"/api/v1/projects/{pid}/nlp/stats")
        stats = stats_resp.json()
        assert stats["total_notes"] == 3
        assert stats["processed_notes"] == 3
        assert stats["total_sentences"] > 0
        assert stats["target_sentences"] > 0

    async def test_run_nlp_no_queries(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await self._setup_project_with_notes(client, pid)

        # Run NLP without any search queries -- all sentences, none targeted
        import asyncio
        resp = await client.post(f"/api/v1/projects/{pid}/nlp/run")
        assert resp.status_code == 200
        assert resp.json()["status"] in ("pending", "running", "completed")
        await asyncio.sleep(0.5)

        stats_resp = await client.get(f"/api/v1/projects/{pid}/nlp/stats")
        stats = stats_resp.json()
        assert stats["target_sentences"] == 0

    async def test_list_target_sentences(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await self._setup_project_with_notes(client, pid)

        await client.post(
            f"/api/v1/projects/{pid}/nlp/queries",
            json={"query": "troponin"},
        )
        import asyncio
        await client.post(f"/api/v1/projects/{pid}/nlp/run")
        await asyncio.sleep(0.5)

        resp = await client.get(f"/api/v1/projects/{pid}/nlp/sentences")
        assert resp.status_code == 200
        sentences = resp.json()
        assert len(sentences) > 0
        assert all(s["is_target"] for s in sentences)

    async def test_reprocess_clears_and_reruns(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await self._setup_project_with_notes(client, pid)

        await client.post(
            f"/api/v1/projects/{pid}/nlp/queries",
            json={"query": "troponin"},
        )

        # First run
        import asyncio
        await client.post(f"/api/v1/projects/{pid}/nlp/run")
        await asyncio.sleep(0.5)

        # Reprocess
        resp = await client.post(f"/api/v1/projects/{pid}/nlp/reprocess")
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"

    async def test_pipeline_info(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(f"/api/v1/projects/{pid}/nlp/pipeline-info")
        assert resp.status_code == 200
        data = resp.json()
        assert "model_name" in data
        assert "pipes" in data
        assert "has_parser" in data
