from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select

from app.annotations.models import Annotation
from app.common.utils import now_utc
from app.connectors.models import Note, Patient
from app.evaluation.models import (
    EvaluationSession,
    PatientResult,
    PatientResultStatus,
    SessionStatus,
)
from app.evaluation.service import (
    SessionLockedError,
    commit_session,
    dispatch_full_pipeline_run,
)
from app.nlp.engine import process_note
from app.production.models import ProductionResult, ProductionRun
from app.worker import run_eval_pipeline_job
from tests.conftest import seed_project_and_user


@pytest.mark.asyncio
async def test_dispatch_uses_production_without_copying_sample_results(app):
    project_id, user_id = await seed_project_and_user(app)
    async with app.state.test_session_factory() as db:
        patient = Patient(project_id=project_id, patient_id_ext="production-patient")
        db.add(patient)
        await db.flush()
        note = Note(
            project_id=project_id,
            patient_id=patient.id,
            text_id="production-note",
            text="Troponin elevated.",
            note_date=now_utc(),
        )
        session = EvaluationSession(
            project_id=project_id,
            created_by=user_id,
            committed_by=user_id,
            status=SessionStatus.COMMITTED,
            search_queries=[{"query": "troponin AND elevated", "type": "include"}],
            sample_patient_ids=[patient.id],
            committed_config={
                "search_queries": [{"query": "troponin AND elevated", "type": "include"}],
                "exclude_negated": True,
            },
        )
        db.add_all([note, session])
        await db.flush()
        sample_result = PatientResult(
            session_id=session.id,
            patient_id=patient.id,
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Sample result must remain unchanged",
        )
        db.add(sample_result)
        await db.commit()
        session_id = session.id
        sample_result_id = sample_result.id

        with patch(
            "app.evaluation.service._enqueue_eval_pipeline_run", new_callable=AsyncMock
        ) as enqueue:
            run_adapter = await dispatch_full_pipeline_run(db, session)
        enqueue.assert_awaited_once_with(run_adapter.id)

    def match_note(text, query_groups):
        return process_note(text, query_groups)

    with patch("app.common.database.async_session", app.state.test_session_factory), \
         patch("app.production.service.process_note", side_effect=match_note) as matcher:
        result = await run_eval_pipeline_job({}, run_adapter.id)

    assert result["failed"] == 0
    matcher.assert_called_once()
    async with app.state.test_session_factory() as db:
        sample_result = await db.get(PatientResult, sample_result_id)
        assert sample_result.pipeline_run_id is None
        assert sample_result.status == PatientResultStatus.COMPLETED
        assert sample_result.finding_reasoning == "Sample result must remain unchanged"
        assert len((await db.execute(select(PatientResult))).scalars().all()) == 1
        run = await db.get(ProductionRun, run_adapter.id)
        assert run.status == "completed"
        assert run.config_snapshot["evaluation_session_id"] == session_id
        production_results = (
            await db.execute(select(ProductionResult).where(ProductionResult.project_id == project_id))
        ).scalars().all()
        assert len(production_results) == 1
        annotations = (
            await db.execute(
                select(Annotation).where(Annotation.production_run_id == run_adapter.id)
            )
        ).scalars().all()
        assert annotations


@pytest.mark.asyncio
async def test_commit_does_not_rebuild_project_nlp(app):
    project_id, user_id = await seed_project_and_user(app)
    async with app.state.test_session_factory() as db:
        from app.projects.models import Project

        project = await db.get(Project, project_id)
        project.llm_provider = "openai"
        project.llm_model = "test-model"
        session = EvaluationSession(
            project_id=project_id,
            created_by=user_id,
            status=SessionStatus.REVIEWING,
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        db.add(session)
        await db.commit()
        session_id = session.id

        with patch("app.nlp.service.run_nlp_pipeline", new_callable=AsyncMock) as rebuild:
            committed = await commit_session(db, session_id, user_id)

        rebuild.assert_not_awaited()
        assert committed.status == SessionStatus.COMMITTED
        assert committed.committed_config["_production_confirmation"]["confirmed"] is False


@pytest.mark.asyncio
async def test_dispatch_passes_saved_confirmation_to_production_by_keyword(app):
    project_id, user_id = await seed_project_and_user(app)
    impact = {"annotations": 0, "predictions": 0, "sentences": 0}
    async with app.state.test_session_factory() as db:
        session = EvaluationSession(
            project_id=project_id,
            created_by=user_id,
            committed_by=user_id,
            status=SessionStatus.COMMITTED,
            search_queries=[{"query": "troponin", "type": "include"}],
            committed_config={
                "search_queries": [{"query": "troponin", "type": "include"}],
                "_production_confirmation": {"confirmed": True, "impact": impact},
            },
        )
        db.add(session)
        await db.commit()

        production_run = SimpleNamespace(id="production-run", total_notes=1)
        with patch("app.nlp.service.reprocess_is_busy", new_callable=AsyncMock,
                   return_value=False), \
             patch("app.nlp.service.get_reprocess_impact", new_callable=AsyncMock,
                   return_value=impact), \
             patch("app.production.service.start_run", new_callable=AsyncMock,
                   return_value=production_run) as start_run, \
             patch("app.evaluation.service._enqueue_eval_pipeline_run", new_callable=AsyncMock):
            adapter = await dispatch_full_pipeline_run(db, session)

        assert adapter.id == production_run.id
        assert start_run.call_args.args == ()
        assert start_run.call_args.kwargs["db"] is db
        assert start_run.call_args.kwargs["confirmed"] is True
        assert start_run.call_args.kwargs["config"]["evaluation_session_id"] == session.id


@pytest.mark.asyncio
async def test_dispatch_refuses_active_processing_or_review_lock(app):
    project_id, user_id = await seed_project_and_user(app)
    async with app.state.test_session_factory() as db:
        session = EvaluationSession(
            project_id=project_id,
            created_by=user_id,
            status=SessionStatus.COMMITTED,
            search_queries=[{"query": "troponin", "type": "include"}],
            committed_config={
                "search_queries": [{"query": "troponin", "type": "include"}],
                "_production_confirmation": {
                    "confirmed": False,
                    "impact": {"annotations": 0, "predictions": 0, "sentences": 0},
                },
            },
        )
        db.add(session)
        await db.commit()

        with patch("app.nlp.service.reprocess_is_busy", new_callable=AsyncMock,
                   return_value=True), \
             patch("app.production.service.start_run", new_callable=AsyncMock) as start_run:
            with pytest.raises(SessionLockedError):
                await dispatch_full_pipeline_run(db, session)
        start_run.assert_not_awaited()
