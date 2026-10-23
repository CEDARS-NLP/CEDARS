"""Tests for ARQ worker configuration and NLP job dispatch."""
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.annotations.models import Annotation
from app.common.utils import now_utc
from app.connectors.models import Note, Patient
from app.evaluation.models import EvaluationSession, SessionStatus
from app.nlp.models import SearchQuery
from app.production.classifier import NoteClassification
from app.production.models import NotePrediction
from app.production.service import start_run
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
        session = EvaluationSession(
            project_id=project_id,
            created_by=user_id,
            status=SessionStatus.COMMITTED,
        )
        db.add(session)
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
                project_id=project_id,
                patient_id=patient.id,
                patient_id_ext=patient.patient_id_ext,
                text_id=f"synthetic-{index}",
                text=text,
                note_date=now_utc(),
            ))
        await db.flush()
        run = await start_run(
            db,
            project_id,
            user_id,
            {
                "query": "troponin AND elevated",
                "exclude_negated": True,
                "evaluation_session_id": session.id,
                "llm_config": {"provider": "openai", "model": "synthetic-model"},
            },
        )
        run_id = run.id

    classification = NoteClassification(
        label=1,
        score=0.9,
        reasoning="Match",
        evidence_spans=[],
    )
    with patch("app.common.database.async_session", app.state.test_session_factory), \
         patch("app.production.service.classify_note", new_callable=AsyncMock,
               return_value=classification) as classify:
        await run_eval_pipeline_job({}, run_id)
        assert classify.await_count == 2
        assert {
            call.args[1]["text_id"] for call in classify.await_args_list
        } == {"synthetic-2", "synthetic-3"}
    async with app.state.test_session_factory() as db:
        predictions = (await db.execute(select(NotePrediction))).scalars().all()
        assert len(predictions) == 2
        assert {prediction.patient_id for prediction in predictions} == {
            "synthetic-2", "synthetic-3",
        }
        annotations = (await db.execute(select(Annotation))).scalars().all()
        assert len(annotations) == 6
        excluded_negations = [
            annotation for annotation in annotations
            if annotation.patient_id == "synthetic-1"
        ]
        assert len(excluded_negations) == 2
        assert all(annotation.status == "R" for annotation in excluded_negations)
        assert {annotation.review_reason for annotation in excluded_negations} == {
            "negated", "duplicate",
        }
        assert all(
            annotation.sentence == "Troponin elevated."
            for annotation in annotations
            if annotation.patient_id in {"synthetic-2", "synthetic-3"}
        )
        refreshed_session = await db.get(EvaluationSession, session.id)
        assert refreshed_session.status == SessionStatus.COMPLETED


async def test_nlp_worker_reuses_confirmed_production_run(app):
    """A queued NLP job must reuse the API-created production run.

    Regression: the worker previously called _process_notes_into_sentences with
    create_annotations=True, which started a second, unconfirmed production run
    and raised ProductionConfirmationRequired once production data existed.
    """
    from app.jobs.models import BackgroundJob, JobType
    from app.jobs.nlp import execute_nlp_job

    project_id, user_id = await seed_project_and_user(app)
    async with app.state.test_session_factory() as db:
        patient = Patient(project_id=project_id, patient_id_ext="reuse-patient")
        db.add(patient)
        await db.flush()
        db.add(Note(
            project_id=project_id,
            patient_id=patient.id,
            patient_id_ext=patient.patient_id_ext,
            text_id="reuse-note",
            text="Troponin elevated.",
            note_date=now_utc(),
        ))
        db.add(SearchQuery(project_id=project_id, query="troponin AND elevated"))
        await db.commit()

        run = await start_run(
            db,
            project_id,
            user_id,
            {
                "query": "troponin AND elevated",
                "exclude_negated": True,
                "llm_config": {"provider": "openai", "model": "synthetic-model"},
            },
            confirmed=True,
        )
        job = BackgroundJob(
            project_id=project_id,
            job_type=JobType.NLP,
            result_summary={"production_run_id": run.id},
        )
        db.add(job)
        await db.commit()
        job_id = job.id
        run_id = run.id

    classification = NoteClassification(
        label=1, score=0.9, reasoning="Match", evidence_spans=[],
    )
    with patch("app.production.service.classify_note", new_callable=AsyncMock,
               return_value=classification):
        result = await execute_nlp_job(project_id, job_id, app.state.test_session_factory)

    assert result.get("run_id") == run_id
    async with app.state.test_session_factory() as db:
        job = await db.get(BackgroundJob, job_id)
        assert job.status.value == "completed"
        predictions = (await db.execute(select(NotePrediction))).scalars().all()
        assert len(predictions) == 1
        assert predictions[0].run_id == run_id
