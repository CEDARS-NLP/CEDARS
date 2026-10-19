"""Tests for ARQ worker configuration and NLP job dispatch."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.annotations.models import Annotation
from app.common.utils import now_utc
from app.connectors.models import Note, Patient
from app.evaluation.models import EvaluationSession, PatientResult, PatientResultStatus
from app.nlp.engine import process_note
from app.nlp.models import SearchQuery
from app.pipeline.classifier import ClassificationResult
from app.pipeline.models import EventConfig, PipelineRun
from app.worker import run_eval_pipeline_job
from tests.conftest import seed_project_and_user


@pytest.fixture(autouse=True)
def _force_sync_dispatch():
    """Force dispatch_nlp_job to use the synchronous fallback path."""
    with patch("arq.create_pool", side_effect=ConnectionError("no Redis in tests")):
        yield


@pytest.mark.asyncio
async def test_enqueue_nlp_job(app, auth_client):
    """NLP run endpoint returns a job with pending status (async dispatch)."""
    # Create project
    resp = await auth_client.post(
        "/api/v1/projects", json={"name": "Test Project"}
    )
    project_id = resp.json()["id"]

    # Trigger NLP run — will fall back to sync since no Redis in tests
    resp = await auth_client.post(f"/api/v1/projects/{project_id}/nlp/run")
    assert resp.status_code == 200
    data = resp.json()
    assert "job_id" in data
    assert "status" in data
    assert data["status"] in ("pending", "running", "completed")


@pytest.mark.asyncio
async def test_dispatch_creates_background_job(app, auth_client):
    """dispatch_nlp_job creates a BackgroundJob record."""
    resp = await auth_client.post(
        "/api/v1/projects", json={"name": "Job Test"}
    )
    project_id = resp.json()["id"]

    import asyncio
    resp = await auth_client.post(f"/api/v1/projects/{project_id}/nlp/run")
    assert resp.status_code == 200
    job_id = resp.json()["job_id"]
    await asyncio.sleep(0.5)

    # Verify the BackgroundJob exists via DB
    from app.common.database import get_session
    from app.jobs.models import BackgroundJob

    async for session in app.dependency_overrides[get_session]():
        bg_job = await session.get(BackgroundJob, job_id)
        assert bg_job is not None
        assert bg_job.project_id == project_id
        assert bg_job.job_type.value == "nlp"


async def test_eval_worker_uses_boolean_truth_and_session_query(app):
    project_id, user_id = await seed_project_and_user(app)
    async with app.state.test_session_factory() as db:
        session = EvaluationSession(project_id=project_id, created_by=user_id)
        event = EventConfig(
            project_id=project_id, name="Event", description="Synthetic event",
            include_criteria="Elevated troponin", exclude_criteria="",
            llm_provider="openai", llm_model="synthetic-model",
        )
        db.add_all([session, event])
        await db.flush()
        run = PipelineRun(
            project_id=project_id, event_config_id=event.id, created_by=user_id, run_type="full",
            config_snapshot={"search_queries": [{"type": "include", "query": "troponin AND elevated"}]},
        )
        db.add(run)
        db.add(SearchQuery(project_id=project_id, query="headache"))
        await db.flush()
        for index, text in enumerate([
            "Troponin measured.", "No troponin elevated.",
            "Troponin elevated.", "Troponin elevated. Troponin measured.",
        ]):
            patient = Patient(project_id=project_id, patient_id_ext=f"synthetic-{index}")
            db.add(patient)
            await db.flush()
            db.add(Note(
                project_id=project_id, patient_id=patient.id, text_id=f"synthetic-{index}",
                text=text, note_date=now_utc(),
            ))
            db.add(PatientResult(
                session_id=session.id, pipeline_run_id=run.id, patient_id=patient.id,
                status=PatientResultStatus.COMPLETED if index == 3 else PatientResultStatus.QUEUED,
                finding_label="positive" if index == 3 else None,
            ))
        await db.commit()
        run_id = run.id

    def process_with_partial_tokens(text, groups):
        sentences = process_note(text, groups)
        for sentence in sentences:
            if not sentence["is_target"]:
                sentence["matched_tokens"] = ["troponin"]
        return sentences

    classification = ClassificationResult(label="positive", confidence=0.9, reasoning="Match")
    with patch("app.common.database.async_session", app.state.test_session_factory), \
         patch("app.nlp.engine.process_note", side_effect=process_with_partial_tokens), \
         patch("app.pipeline.classifier.classify_patient", new_callable=AsyncMock,
               return_value=classification) as classify:
        await run_eval_pipeline_job({}, run_id)
        classify.assert_awaited_once()
        assert classify.call_args.args[0][0]["text"] == "Troponin elevated."
    async with app.state.test_session_factory() as db:
        results = (await db.execute(select(PatientResult))).scalars().all()
        assert sum(result.status == PatientResultStatus.NO_MATCH for result in results) == 2
        annotations = (await db.execute(select(Annotation))).scalars().all()
        assert len(annotations) == 2
        assert all(annotation.sentence_text == "Troponin elevated." for annotation in annotations)
