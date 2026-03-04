"""API integration tests for annotations: bulk runs, review operations."""

import pytest
from httpx import AsyncClient
from unittest.mock import AsyncMock, patch

from app.predictors.base import PredictionResult


async def register_and_login(client: AsyncClient, email: str = "anno@example.com") -> None:
    """Register a user and login. Cookies are set automatically by httpx."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Annotator", "password": "secret123"},
    )
    await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "secret123"},
    )


async def create_project(client: AsyncClient) -> str:
    """Create a project and return its ID."""
    resp = await client.post(
        "/api/v1/projects",
        json={"name": "Annotation Project", "description": "test"},
    )
    return resp.json()["id"]


async def setup_notes_and_nlp(client: AsyncClient, pid: str):
    """Create data source, ingest notes, add query, run NLP."""
    from unittest.mock import patch as mock_patch

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
    with mock_patch("app.connectors.file_upload.download_file", return_value=csv_data):
        await client.post(
            f"/api/v1/projects/{pid}/data/sources/{ds_id}/ingest",
        )

    # Add search query and run NLP
    await client.post(
        f"/api/v1/projects/{pid}/nlp/queries",
        json={"query": "troponin OR myocardial"},
    )
    await client.post(f"/api/v1/projects/{pid}/nlp/run")


async def setup_notes_with_dates(client: AsyncClient, pid: str):
    """Create data source with note_date column for date-aware skip tests."""
    from unittest.mock import patch as mock_patch

    create_resp = await client.post(
        f"/api/v1/projects/{pid}/data/sources",
        json={
            "name": "dated.csv",
            "connector_type": "file_upload",
            "config": {
                "s3_key": "dated.csv",
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
        b"P001,N002,Follow-up shows continued troponin elevation.,2026-01-15\n"
        b"P001,N003,Final visit shows troponin normalized.,2026-01-20\n"
        b"P002,N004,Patient with myocardial infarction confirmed.,2026-02-01\n"
        b"P002,N005,Follow-up myocardial function test.,2026-02-10\n"
    )
    with mock_patch("app.connectors.file_upload.download_file", return_value=csv_data):
        await client.post(
            f"/api/v1/projects/{pid}/data/sources/{ds_id}/ingest",
        )

    # Add search query (with default skip_after_event=True) and run NLP
    await client.post(
        f"/api/v1/projects/{pid}/nlp/queries",
        json={"query": "troponin OR myocardial"},
    )
    await client.post(f"/api/v1/projects/{pid}/nlp/run")


async def add_predictor(client: AsyncClient, pid: str) -> str:
    """Add and activate an LLM predictor."""
    resp = await client.post(
        f"/api/v1/projects/{pid}/predictors",
        json={
            "name": "Test LLM",
            "predictor_type": "llm",
            "config": {
                "provider": "ollama",
                "model": "test-model",
                "api_base": "http://localhost:11434",
                "event_name": "MI",
                "event_description": "Myocardial Infarction",
                "include_criteria": "troponin elevation",
                "exclude_criteria": "ruled out",
            },
        },
    )
    pred_id = resp.json()["id"]
    await client.post(f"/api/v1/projects/{pid}/predictors/{pred_id}/activate")
    return pred_id


async def _full_setup(client: AsyncClient, use_dates: bool = False) -> str:
    """Full setup: notes, NLP, predictor, bulk run -> annotations exist."""
    await register_and_login(client)
    pid = await create_project(client)
    if use_dates:
        await setup_notes_with_dates(client, pid)
    else:
        await setup_notes_and_nlp(client, pid)
    await add_predictor(client, pid)

    mock_result = PredictionResult(score=0.85, label=1, model="test", reasoning="test")
    with patch("app.annotations.prediction_service.create_predictor") as mock_factory:
        mock_predictor = AsyncMock()
        mock_predictor.predict.return_value = mock_result
        mock_factory.return_value = mock_predictor
        await client.post(f"/api/v1/projects/{pid}/annotations/run")

    return pid


class TestBulkRun:
    async def test_run_predictions(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await setup_notes_and_nlp(client, pid)
        await add_predictor(client, pid)

        mock_result = PredictionResult(score=0.85, label=1, model="test", reasoning="troponin elevated")

        with patch("app.annotations.prediction_service.create_predictor") as mock_factory:
            mock_predictor = AsyncMock()
            mock_predictor.predict.return_value = mock_result
            mock_factory.return_value = mock_predictor

            resp = await client.post(f"/api/v1/projects/{pid}/annotations/run")

        assert resp.status_code == 200
        data = resp.json()
        assert data["total_sentences"] > 0
        assert data["annotations_created"] > 0
        assert data["errors"] == 0

    async def test_run_without_predictor(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(f"/api/v1/projects/{pid}/annotations/run")
        assert resp.status_code == 400
        assert "No active predictor" in resp.json()["detail"]


class TestAnnotationReview:
    async def _setup_with_annotations(self, client):
        return await _full_setup(client)

    async def test_list_annotations(self, client):
        pid = await self._setup_with_annotations(client)
        resp = await client.get(f"/api/v1/projects/{pid}/annotations")
        assert resp.status_code == 200
        annotations = resp.json()
        assert len(annotations) > 0
        assert all(a["review_status"] == "unreviewed" for a in annotations)

    async def test_get_stats(self, client):
        pid = await self._setup_with_annotations(client)
        resp = await client.get(f"/api/v1/projects/{pid}/annotations/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total"] > 0
        assert stats["unreviewed"] == stats["total"]
        assert stats["reviewed"] == 0

    async def test_get_next_unreviewed(self, client):
        pid = await self._setup_with_annotations(client)
        resp = await client.get(f"/api/v1/projects/{pid}/annotations/next")
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "unreviewed"

    async def test_review_annotation(self, client):
        pid = await self._setup_with_annotations(client)

        # Get an annotation
        list_resp = await client.get(f"/api/v1/projects/{pid}/annotations")
        anno_id = list_resp.json()[0]["id"]

        # Review it — now returns ReviewResultResponse
        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{anno_id}/review",
            json={},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["annotation"]["review_status"] == "reviewed"
        assert data["skipped_count"] == 0

    async def test_skip_annotation(self, client):
        pid = await self._setup_with_annotations(client)

        list_resp = await client.get(f"/api/v1/projects/{pid}/annotations")
        anno_id = list_resp.json()[0]["id"]

        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{anno_id}/skip",
            json={},
        )
        assert resp.status_code == 200
        assert resp.json()["review_status"] == "skipped"

    async def test_review_with_event_date(self, client):
        pid = await self._setup_with_annotations(client)

        list_resp = await client.get(f"/api/v1/projects/{pid}/annotations")
        anno_id = list_resp.json()[0]["id"]

        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{anno_id}/review",
            json={"event_date": "2026-01-15T00:00:00Z"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["annotation"]["review_status"] == "reviewed"
        assert data["annotation"]["event_date"] is not None

    async def test_annotation_context(self, client):
        pid = await self._setup_with_annotations(client)

        list_resp = await client.get(f"/api/v1/projects/{pid}/annotations")
        anno_id = list_resp.json()[0]["id"]

        resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/{anno_id}/context",
        )
        assert resp.status_code == 200
        ctx = resp.json()
        assert "text" in ctx
        assert "sentences" in ctx
        assert len(ctx["sentences"]) > 0


class TestPatientReview:
    """Tests for the patient-first review flow."""

    async def test_get_next_patient(self, client):
        """GET /patient/next returns first patient with unreviewed annotations and locks them."""
        pid = await _full_setup(client)

        resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] is not None
        assert data["patient_id_ext"] is not None
        assert data["total_annotations"] > 0
        assert data["unreviewed_annotations"] > 0
        assert data["all_complete"] is False

    async def test_next_patient_all_complete(self, client):
        """GET /patient/next returns all_complete when no unreviewed annotations exist."""
        pid = await _full_setup(client)

        # Review all annotations
        annotations = (await client.get(
            f"/api/v1/projects/{pid}/annotations?limit=200"
        )).json()
        for ann in annotations:
            await client.post(
                f"/api/v1/projects/{pid}/annotations/{ann['id']}/review",
                json={},
            )

        resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        assert resp.status_code == 200
        data = resp.json()
        assert data["patient_id"] is None
        assert data["all_complete"] is True

    async def test_patient_annotations_sorted(self, client):
        """GET /patient/{id}/annotations returns annotations sorted by note_date, sentence_number."""
        pid = await _full_setup(client, use_dates=True)

        # Get a patient
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )
        assert resp.status_code == 200
        annotations = resp.json()
        assert len(annotations) > 0

        # Verify sorted by note_date
        dates = [a["note_date"] for a in annotations if a["note_date"] is not None]
        assert dates == sorted(dates)

        # All annotations should have note context fields
        for a in annotations:
            assert "note_text_id" in a
            assert "sentence_number" in a

    async def test_review_with_event_date_skips_post_event(self, client):
        """POST /{id}/review with event_date skips only annotations on/after event date."""
        pid = await _full_setup(client, use_dates=True)

        # Get patient and their annotations
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        annos_resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )
        annotations = annos_resp.json()
        assert len(annotations) >= 2, "Need at least 2 annotations to test date-aware skip"

        # Find the earliest annotation
        first_anno = annotations[0]

        # Review with event_date = the earliest note's date
        # This should skip annotations on/after that date (except the reviewed one)
        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{first_anno['id']}/review",
            json={"event_date": first_anno["note_date"]},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["annotation"]["review_status"] == "reviewed"
        assert data["annotation"]["event_date"] is not None
        # Should have skipped some annotations
        assert data["skipped_count"] >= 1

    async def test_review_event_date_respects_skip_after_event_false(self, client):
        """POST /{id}/review with event_date does not skip when skip_after_event=False."""
        pid = await _full_setup(client, use_dates=True)

        # Update the search query to have skip_after_event=False
        queries_resp = await client.get(f"/api/v1/projects/{pid}/nlp/queries")
        query_id = queries_resp.json()[0]["id"]
        await client.put(
            f"/api/v1/projects/{pid}/nlp/queries/{query_id}",
            json={"skip_after_event": False},
        )

        # Get patient and annotations
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        annos_resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )
        annotations = annos_resp.json()
        first_anno = annotations[0]

        # Review with event_date — should NOT skip anything
        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{first_anno['id']}/review",
            json={"event_date": first_anno["note_date"]},
        )
        assert resp.status_code == 200
        assert resp.json()["skipped_count"] == 0

    async def test_delete_event_date(self, client):
        """POST /{id}/delete-event-date reverts SKIPPED → UNREVIEWED, clears event_date."""
        pid = await _full_setup(client, use_dates=True)

        # Get patient and annotations
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        annos_resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )
        annotations = annos_resp.json()
        first_anno = annotations[0]

        # Review with event_date to create skips
        review_resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{first_anno['id']}/review",
            json={"event_date": first_anno["note_date"]},
        )
        skipped = review_resp.json()["skipped_count"]
        assert skipped >= 1

        # Delete the event date
        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/{first_anno['id']}/delete-event-date",
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["annotation"]["event_date"] is None
        assert data["annotation"]["review_status"] == "unreviewed"
        assert data["reverted_count"] >= 1

    async def test_unlock_patient(self, client):
        """POST /patient/{id}/unlock clears locked_by/locked_at."""
        pid = await _full_setup(client)

        # Lock a patient
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        # Unlock
        resp = await client.post(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/unlock",
        )
        assert resp.status_code == 200

    async def test_patient_stats(self, client):
        """GET /patient/{id}/stats returns correct review stats."""
        pid = await _full_setup(client, use_dates=True)

        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/stats"
        )
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total"] > 0
        assert stats["unreviewed"] == stats["total"]
        assert stats["reviewed"] == 0
        assert stats["skipped"] == 0
        assert stats["current_event_date"] is None
        assert stats["event_annotation_id"] is None

    async def test_full_patient_review_flow(self, client):
        """Full flow: review all annotations → patient REVIEWED → next patient."""
        pid = await _full_setup(client, use_dates=True)

        # Get first patient
        next_resp = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        patient_id = next_resp.json()["patient_id"]

        # Get all annotations for this patient
        annos_resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/annotations"
        )
        annotations = annos_resp.json()

        # Review all annotations
        for ann in annotations:
            if ann["review_status"] == "unreviewed":
                await client.post(
                    f"/api/v1/projects/{pid}/annotations/{ann['id']}/review",
                    json={},
                )

        # Check patient stats — all should be reviewed
        stats_resp = await client.get(
            f"/api/v1/projects/{pid}/annotations/patient/{patient_id}/stats"
        )
        stats = stats_resp.json()
        assert stats["unreviewed"] == 0

        # Get next patient — should return a different patient
        next_resp2 = await client.get(f"/api/v1/projects/{pid}/annotations/patient/next")
        data = next_resp2.json()
        if data["patient_id"] is not None:
            assert data["patient_id"] != patient_id
