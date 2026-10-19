"""Tests for the unified evaluation session router."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.annotations.models import Annotation, AnnotationPrediction
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.evaluation.models import (
    EvaluationSession, PatientResult, PatientResultStatus, SearchMatch, SessionStatus,
)
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.jobs.nlp import execute_nlp_job
from app.nlp.models import NlpJob, NlpJobStatus, SearchQuery, Sentence
from app.nlp.service import _process_notes_into_sentences, get_reprocess_impact
from app.projects.models import Project, ProjectMember, ProjectRole


async def register_and_login(client, email="eval@test.com"):
    """Register and login a user."""
    await client.post(
        "/api/v1/auth/register",
        json={"email": email, "name": "Eval User", "password": "testpass123"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": "testpass123"},
    )
    assert resp.status_code == 200


async def create_project(client, name="Eval Project"):
    """Create a project, return its ID."""
    resp = await client.post("/api/v1/projects", json={"name": name})
    assert resp.status_code == 201
    return resp.json()["id"]


async def create_eval_session(client, project_id):
    """Create an evaluation session, return the response data."""
    resp = await client.post(
        f"/api/v1/projects/{project_id}/evaluation/sessions",
        json={"search_queries": [{"query": "troponin", "type": "include"}]},
    )
    assert resp.status_code == 201
    return resp.json()


class TestSessionCRUD:
    """Session create, list, get, discard."""

    async def test_create_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"search_queries": [{"query": "troponin", "type": "include"}]},
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["status"] == "draft"
        assert data["project_id"] == pid
        assert len(data["search_queries"]) == 1

    async def test_list_sessions(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await create_eval_session(client, pid)

        resp = await client.get(f"/api/v1/projects/{pid}/evaluation/sessions")
        assert resp.status_code == 200
        sessions = resp.json()
        assert len(sessions) == 1

    async def test_get_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["id"] == session["id"]

    async def test_get_session_not_found(self, client):
        await register_and_login(client)
        pid = await create_project(client)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/nonexistent"
        )
        assert resp.status_code == 404

    async def test_discard_session(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.delete(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}"
        )
        assert resp.status_code == 200
        assert resp.json()["status"] == "discarded"

    async def test_create_blocked_by_existing_draft(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        await create_eval_session(client, pid)

        # Second create should fail
        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions",
            json={"search_queries": []},
        )
        assert resp.status_code == 409


class TestQueries:
    """Update and execute search queries."""

    @pytest.mark.parametrize("rows,status_code", [
        ([], 400), ([{"query": " ", "type": "include"}], 400),
        ([{"query": "DVT", "type": "exclude"}], 400),
        ([{"query": "DVT AND", "type": "include"}], 400),
        ([{"query": "DVT", "type": "invalid"}], 422),
        ([{"query": 123, "type": "include"}], 422),
    ])
    async def test_invalid_save_preserves_saved_query(self, client, rows, status_code):
        await register_and_login(client)
        project_id = await create_project(client)
        session = await create_eval_session(client, project_id)
        endpoint = f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}"
        response = await client.put(endpoint + "/queries", json={"search_queries": rows})
        assert response.status_code == status_code
        saved = await client.get(endpoint)
        assert saved.json()["search_queries"] == session["search_queries"]

    @pytest.mark.parametrize("locked_status", ["committed", "completed", "discarded", "running"])
    async def test_locked_query_and_prompt_edits_rejected(self, client, app, locked_status):
        await register_and_login(client)
        project_id = await create_project(client)
        session = await create_eval_session(client, project_id)
        endpoint = f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}"
        async with app.state.test_session_factory() as db:
            saved = await db.get(EvaluationSession, session["id"])
            if locked_status == "running":
                saved.metrics = {"llm_status": "running"}
            else:
                saved.status = locked_status
            await db.commit()
        query = await client.put(endpoint + "/queries", json={
            "search_queries": [{"query": "DVT", "type": "include"}]
        })
        assert query.status_code == 409
        execute = await client.post(endpoint + "/queries/execute")
        assert execute.status_code == 409
        prompt = await client.put(endpoint + "/event-config", json={
            "event_name": "Event", "event_description": "Description", "include_criteria": "DVT"
        })
        assert prompt.status_code == 409

    async def test_update_queries(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.put(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/queries",
            json={
                "search_queries": [
                    {"query": "MI OR myocardial", "type": "include"},
                    {"query": "ruled out", "type": "exclude"},
                ],
                "exclude_negated": False,
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["search_queries"] == [
            {"query": "(MI OR myocardial) AND !((ruled out))", "type": "include"}
        ]
        assert data["query_sections"] == [
            {"query": "MI OR myocardial", "type": "include"},
            {"query": "ruled out", "type": "exclude"},
        ]
        assert data["exclude_negated"] is False

        event = await client.put(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/event-config",
            json={
                "event_name": "Event",
                "event_description": "Description",
                "include_criteria": "MI",
            },
        )
        assert event.status_code == 200
        assert event.json()["query_sections"] == data["query_sections"]

        reloaded = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}"
        )
        assert reloaded.status_code == 200
        assert reloaded.json()["query_sections"] == data["query_sections"]

    async def test_execute_queries(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/queries/execute"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sample_patients" in data
        assert "matched_patients" in data


class TestEventConfig:
    """Event configuration update."""

    async def test_update_event_config(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.put(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/event-config",
            json={
                "event_name": "Myocardial Infarction",
                "event_description": "A heart attack event",
                "include_criteria": "troponin elevation, ST changes",
                "exclude_criteria": "ruled out",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["event_name"] == "Myocardial Infarction"


class TestResultsAndMetrics:
    """Results listing, funnel stats, and metrics."""

    async def test_get_results_empty(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/results"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["results"] == []
        assert data["total"] == 0

    async def test_get_funnel(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/funnel"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "sample_patients" in data
        assert "matched_patients" in data
        assert "filter_percent" in data

    async def test_get_metrics_empty(self, client):
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.get(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/metrics"
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_reviewed"] == 0
        assert data["accuracy"] == 0.0
        assert data["tp"] == 0


class TestCommit:
    """Session commit endpoint."""

    @pytest.mark.parametrize("rejection", [
        "missing", "unconfirmed", "stale_annotations", "stale_predictions",
        "stale_sentences", "busy", "review_lock", "stale_zero",
    ])
    async def test_guarded_commit_rejection_has_no_side_effects(self, client, app, rejection):
        project_id, session_id, endpoint, old_id, impact = await setup_guarded_commit(
            client, app, processed=rejection != "stale_zero",
        )
        confirmation = exact_confirmation(impact)
        body = {"reprocess": confirmation}
        if rejection == "missing":
            body = {}
        elif rejection == "unconfirmed":
            confirmation["confirmed"] = False
        elif rejection.startswith("stale_"):
            key = "sentences" if rejection == "stale_zero" else rejection.removeprefix("stale_")
            confirmation[f"expected_{key}"] += 1
        async with app.state.test_session_factory() as db:
            if rejection == "busy":
                db.add(BackgroundJob(
                    project_id=project_id, job_type=JobType.NLP, status=JobStatus.RUNNING,
                ))
            elif rejection == "review_lock":
                patient = (await db.execute(select(Patient))).scalar_one()
                session = await db.get(EvaluationSession, session_id)
                patient.locked_by = session.created_by
                patient.locked_at = now_utc()
                patient.status = PatientStatus.REVIEWING
            await db.commit()
            before = await commit_state(db, session_id)
        with patch("app.nlp.service.run_nlp_pipeline", new_callable=AsyncMock) as rebuild, \
             patch("app.evaluation.service.dispatch_full_pipeline_run", new_callable=AsyncMock) as dispatch:
            response = await client.post(endpoint, json=body)
            assert response.status_code == 409, response.text
            assert ("Confirm deletion" if rejection in {"missing", "unconfirmed"} else
                    "Finish active processing" if rejection in {"busy", "review_lock"} else
                    "counts changed") in response.json()["detail"]
            rebuild.assert_not_awaited()
            dispatch.assert_not_awaited()
        async with app.state.test_session_factory() as db:
            assert await commit_state(db, session_id) == before
            assert await get_reprocess_impact(db, project_id) == impact
            assert (await db.get(SearchQuery, old_id)).is_active

    @pytest.mark.parametrize("exclude_negated", [True, False])
    @pytest.mark.parametrize("processed", [True, False])
    async def test_commit_rebuilds_before_dispatch_without_keyword_annotations(
        self, client, app, exclude_negated, processed,
    ):
        from app.nlp.service import run_nlp_pipeline

        project_id, session_id, endpoint, old_id, impact = await setup_guarded_commit(
            client, app, processed=processed, exclude_negated=exclude_negated,
        )
        async with app.state.test_session_factory() as db:
            old_sentences = set((await db.execute(select(Sentence.id))).scalars())
            before_results = (await commit_state(db, session_id))[PatientResult.__tablename__]
            before_matches = (await commit_state(db, session_id))[SearchMatch.__tablename__]
        body = {"reprocess": exact_confirmation(impact)} if processed else {}

        async def dispatch_after_rebuild(db, session, **kwargs):
            assert session.status == SessionStatus.COMMITTED
            job = (await db.execute(select(NlpJob))).scalar_one()
            assert job.status == NlpJobStatus.COMPLETED
            assert job.processed_notes == 1
            sentences = (await db.execute(select(Sentence))).scalars().all()
            assert len(sentences) == 3
            assert not old_sentences.intersection(sentence.id for sentence in sentences)
            assert {sentence.text for sentence in sentences if sentence.is_target} == {
                "Troponin elevated.", "Confirmed DVT.",
            }
            assert await get_reprocess_impact(db, project_id) == {
                "annotations": 0, "predictions": 0, "sentences": 3,
            }
            patient = (await db.execute(select(Patient))).scalar_one()
            assert patient.status == (
                PatientStatus.NLP_COMPLETE if processed else PatientStatus.NEW
            )
            assert patient.reviewed_by is None
            assert patient.reviewed_at is None
            state = await commit_state(db, session_id)
            assert state[PatientResult.__tablename__] == before_results
            assert state[SearchMatch.__tablename__] == before_matches
            return SimpleNamespace(id="guarded-run", total_patients=1)

        with patch("app.nlp.service.run_nlp_pipeline", wraps=run_nlp_pipeline) as rebuild, \
             patch("app.evaluation.service.dispatch_full_pipeline_run", side_effect=dispatch_after_rebuild) as dispatch, \
             patch("litellm.acompletion", new_callable=AsyncMock) as llm:
            response = await client.post(endpoint, json=body)
            assert response.status_code == 200, response.text
            assert response.json()["pipeline_run_id"] == "guarded-run"
            rebuild.assert_awaited_once()
            assert rebuild.call_args.kwargs == {"create_annotations": False}
            dispatch.assert_awaited_once()
            llm.assert_not_awaited()
        async with app.state.test_session_factory() as db:
            session = await db.get(EvaluationSession, session_id)
            active = (await db.execute(select(SearchQuery).where(SearchQuery.is_active))).scalar_one()
            assert active.id != old_id
            assert active.exclude_negated is exclude_negated
            assert active.nlp_apply is False
            assert active.query == session.search_queries[0]["query"]
            assert session.committed_config["exclude_negated"] is exclude_negated
            assert session.committed_config["search_queries"] == session.search_queries
            assert session.committed_at is not None
            assert session.committed_by == session.created_by

    async def test_failed_rebuild_remains_editable_and_can_retry(self, client, app):
        project_id, session_id, endpoint, _, impact = await setup_guarded_commit(
            client, app, processed=True,
        )
        with patch("app.nlp.service._process_notes_into_sentences", side_effect=RuntimeError("test failure")), \
             patch("app.evaluation.service.dispatch_full_pipeline_run", new_callable=AsyncMock) as dispatch:
            response = await client.post(endpoint, json={"reprocess": exact_confirmation(impact)})
            assert response.status_code == 409, response.text
            assert "Sentence rebuild failed. Retry" in response.json()["detail"]
            dispatch.assert_not_awaited()
        async with app.state.test_session_factory() as db:
            session = await db.get(EvaluationSession, session_id)
            assert session.status == SessionStatus.REVIEWING
            assert session.committed_config is None
            assert session.committed_at is None
            assert session.committed_by is None
            job = (await db.execute(select(NlpJob))).scalar_one()
            assert job.status == NlpJobStatus.FAILED
            assert job.error_message
            assert await get_reprocess_impact(db, project_id) == {
                "annotations": 0, "predictions": 0, "sentences": 0,
            }
            results = (await db.execute(select(PatientResult))).scalars().all()
            assert len(results) == 1 and results[0].review_judgment == "correct"
            assert (await db.execute(select(func.count()).select_from(BackgroundJob))).scalar() == 0
        updated = await client.put(endpoint.removesuffix("/commit") + "/queries", json={
            "search_queries": [{"query": "DVT", "type": "include"}],
        })
        assert updated.status_code == 200, updated.text
        run = SimpleNamespace(id="retry-run", total_patients=1)
        with patch("app.evaluation.service.dispatch_full_pipeline_run", new_callable=AsyncMock, return_value=run) as dispatch:
            retried = await client.post(endpoint, json={})
            assert retried.status_code == 200, retried.text
            dispatch.assert_awaited_once()
        async with app.state.test_session_factory() as db:
            assert (await db.get(EvaluationSession, session_id)).status == SessionStatus.COMMITTED
            jobs = (await db.execute(select(NlpJob))).scalars().all()
            assert {job.status for job in jobs} == {NlpJobStatus.FAILED, NlpJobStatus.COMPLETED}
            assert await get_reprocess_impact(db, project_id) == {
                "annotations": 0, "predictions": 0, "sentences": 3,
            }

    async def test_commit_requires_reviewing_status(self, client):
        """DRAFT session cannot be committed."""
        await register_and_login(client)
        pid = await create_project(client)
        session = await create_eval_session(client, pid)

        resp = await client.post(
            f"/api/v1/projects/{pid}/evaluation/sessions/{session['id']}/commit",
            json={},
        )
        # Session is in DRAFT, should fail
        assert resp.status_code == 409


def exact_confirmation(impact):
    return {"confirmed": True, **{f"expected_{key}": value for key, value in impact.items()}}


async def commit_state(db, session_id):
    models = (
        SearchQuery, Sentence, Annotation, AnnotationPrediction, Patient, PatientResult,
        SearchMatch, BackgroundJob, NlpJob,
    )
    state = {
        model.__tablename__: [row.model_dump(warnings=False) for row in (
            await db.execute(select(model).order_by(model.id).execution_options(populate_existing=True))
        ).scalars()]
        for model in models
    }
    state["session"] = (await db.get(EvaluationSession, session_id)).model_dump(warnings=False)
    return state


async def setup_guarded_commit(client, app, *, processed=False, exclude_negated=True):
    project_id, session_id, _, old_id, impact = await setup_query_run(
        client, app, processed=processed,
    )
    async with app.state.test_session_factory() as db:
        project = await db.get(Project, project_id)
        project.llm_provider = "openai"
        project.llm_model = "gpt-4o"
        session = await db.get(EvaluationSession, session_id)
        session.status = SessionStatus.REVIEWING
        session.exclude_negated = exclude_negated
        patient = (await db.execute(select(Patient))).scalar_one()
        note = (await db.execute(select(Note))).scalar_one()
        db.add(PatientResult(
            session_id=session_id, patient_id=patient.id,
            status=PatientResultStatus.COMPLETED, finding_label="positive",
            finding_reasoning="Sample finding", predicted_score=0.95,
            review_judgment="correct", reviewed_by=session.created_by, reviewed_at=now_utc(),
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        ))
        db.add(SearchMatch(
            session_id=session_id, patient_id=patient.id, note_id=note.id,
            matched_tokens=["DVT"], match_positions=[{"start": 40, "end": 43}],
        ))
        await db.commit()
    endpoint = f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/commit"
    return project_id, session_id, endpoint, old_id, impact


async def setup_query_run(client, app, *, processed=False):
    await register_and_login(client)
    project_id = await create_project(client)
    evaluation = await create_eval_session(client, project_id)
    endpoint = f"/api/v1/projects/{project_id}/evaluation/sessions/{evaluation['id']}/queries"
    response = await client.put(endpoint, json={"search_queries": [
        {"type": "include", "query": "troponin AND elevated"},
        {"type": "include", "query": "DVT"},
        {"type": "exclude", "query": "suspected"},
    ]})
    assert response.status_code == 200
    async with app.state.test_session_factory() as db:
        patient = Patient(project_id=project_id, patient_id_ext="synthetic")
        db.add(patient)
        await db.flush()
        db.add(Note(
            project_id=project_id, patient_id=patient.id, text_id="synthetic-note",
            note_date=now_utc(),
            text="Troponin elevated. Suspected DVT. Confirmed DVT.",
        ))
        old_query = SearchQuery(project_id=project_id, query="DVT OR troponin")
        db.add(old_query)
        await db.commit()
        old_id = old_query.id
        if processed:
            await _process_notes_into_sentences(db, project_id)
            annotation = (await db.execute(select(Annotation).limit(1))).scalar_one()
            db.add(AnnotationPrediction(annotation_id=annotation.id, project_id=project_id))
            await db.commit()
        impact = await get_reprocess_impact(db, project_id)
    return project_id, evaluation["id"], endpoint + "/run-all", old_id, impact


class TestRunAllQueries:
    async def test_stale_confirmation_rejected_even_when_impact_is_now_zero(self, client, app):
        _, _, endpoint, old_id, _ = await setup_query_run(client, app)
        response = await client.post(endpoint, json={
            "confirmed": True, "expected_annotations": 1,
            "expected_predictions": 0, "expected_sentences": 1,
        })
        assert response.status_code == 409
        async with app.state.test_session_factory() as db:
            queries = (await db.execute(select(SearchQuery))).scalars().all()
            assert len(queries) == 1 and queries[0].id == old_id and queries[0].is_active
            assert (await db.execute(select(func.count()).select_from(BackgroundJob))).scalar() == 0

    @pytest.mark.parametrize("body", [{}, None])
    async def test_fresh_keyword_run_without_event_or_provider(self, client, app, body):
        project_id, session_id, endpoint, old_id, _ = await setup_query_run(client, app)
        with patch("app.jobs.nlp.execute_nlp_job", new_callable=AsyncMock) as scheduled, \
             patch("litellm.acompletion", new_callable=AsyncMock) as llm:
            response = await client.post(endpoint, json=body)
            assert response.status_code == 200, response.text
            data = response.json()
            assert data["job_id"]
            await execute_nlp_job(project_id, data["job_id"], app.state.test_session_factory)
            llm.assert_not_called()
            assert scheduled.call_count == 1
        async with app.state.test_session_factory() as db:
            queries = (await db.execute(select(SearchQuery))).scalars().all()
            assert len(queries) == 2
            active = [query for query in queries if query.is_active]
            assert len(active) == 1
            assert active[0].id != old_id
            assert active[0].nlp_apply is False
            session = await db.get(EvaluationSession, session_id)
            assert session.status == SessionStatus.DRAFT
            assert session.event_name is None
            assert session.committed_config is None
            assert active[0].query == session.search_queries[0]["query"]
            annotations = (await db.execute(select(Annotation))).scalars().all()
            assert {annotation.token for annotation in annotations} == {"Troponin", "elevated", "DVT"}
            assert all(annotation.predicted_label is None for annotation in annotations)
            assert (await db.execute(select(func.count()).select_from(AnnotationPrediction))).scalar() == 0
        status = await client.get(f"/api/v1/projects/{project_id}/nlp/job/status")
        assert status.json()["job_id"] == data["job_id"]
        assert status.json()["status"] == "completed"

    @pytest.mark.parametrize("rejection,expected_status", [
        ("missing", 400), ("unconfirmed", 400), ("changed", 409),
        ("busy", 409), ("review_lock", 409), ("locked_session", 409),
        ("invalid_query", 400),
    ])
    async def test_rejected_run_has_no_side_effects(self, client, app, rejection, expected_status):
        project_id, session_id, endpoint, old_id, impact = await setup_query_run(
            client, app, processed=True
        )
        body = {"confirmed": True, **{f"expected_{key}": value for key, value in impact.items()}}
        if rejection == "missing":
            body = {}
        elif rejection == "unconfirmed":
            body["confirmed"] = False
        elif rejection == "changed":
            body["expected_sentences"] += 1
        async with app.state.test_session_factory() as db:
            if rejection == "busy":
                db.add(BackgroundJob(project_id=project_id, job_type=JobType.NLP, status=JobStatus.RUNNING))
            elif rejection == "review_lock":
                patient = (await db.execute(select(Patient))).scalar_one()
                session = await db.get(EvaluationSession, session_id)
                patient.locked_by = session.created_by
                patient.locked_at = now_utc()
                patient.status = PatientStatus.REVIEWING
            elif rejection in ("locked_session", "invalid_query"):
                session = await db.get(EvaluationSession, session_id)
                if rejection == "locked_session":
                    session.status = SessionStatus.COMMITTED
                else:
                    session.search_queries = [{"type": "exclude", "query": "DVT"}]
            await db.commit()
            jobs_before = (await db.execute(select(func.count()).select_from(BackgroundJob))).scalar()
        response = await client.post(endpoint, json=body)
        assert response.status_code == expected_status, response.text
        async with app.state.test_session_factory() as db:
            assert await get_reprocess_impact(db, project_id) == impact
            queries = (await db.execute(select(SearchQuery))).scalars().all()
            assert len(queries) == 1
            assert queries[0].id == old_id and queries[0].is_active
            assert (await db.execute(select(func.count()).select_from(BackgroundJob))).scalar() == jobs_before
            assert (await db.execute(select(func.count()).select_from(NlpJob))).scalar() == 0

    async def test_confirmed_rerun_returns_existing_nlp_job_contract(self, client, app):
        project_id, session_id, endpoint, old_id, impact = await setup_query_run(
            client, app, processed=True
        )
        with patch("litellm.acompletion", new_callable=AsyncMock) as llm:
            response = await client.post(endpoint, json={
                "confirmed": True, **{f"expected_{key}": value for key, value in impact.items()}
            })
            assert response.status_code == 200, response.text
            llm.assert_not_called()
        data = response.json()
        assert data["id"] and data["status"] == "completed"
        assert data["processed_notes"] == 1
        job = await client.get(f"/api/v1/projects/{project_id}/nlp/job")
        assert job.json()["id"] == data["id"]
        async with app.state.test_session_factory() as db:
            assert (await db.get(SearchQuery, old_id)).is_active is False
            session = await db.get(EvaluationSession, session_id)
            assert session.status == SessionStatus.DRAFT
            counts = await get_reprocess_impact(db, project_id)
            assert counts == {"annotations": 3, "predictions": 0, "sentences": 3}

    @pytest.mark.parametrize("role", [ProjectRole.ANNOTATOR, ProjectRole.VIEWER])
    async def test_project_roles_cannot_run_all(self, client, app, role):
        project_id, _, endpoint, old_id, _ = await setup_query_run(client, app)
        async with app.state.test_session_factory() as db:
            member = (await db.execute(select(ProjectMember).where(
                ProjectMember.project_id == project_id
            ))).scalar_one()
            member.role = role
            await db.commit()
        response = await client.post(endpoint, json={})
        assert response.status_code == 403
        async with app.state.test_session_factory() as db:
            assert (await db.get(SearchQuery, old_id)).is_active

    async def test_session_is_project_scoped(self, client, app):
        project_id, _, endpoint, old_id, _ = await setup_query_run(client, app)
        other_project = await create_project(client, "Other project")
        response = await client.post(endpoint.replace(project_id, other_project), json={})
        assert response.status_code == 404
        async with app.state.test_session_factory() as db:
            assert (await db.get(SearchQuery, old_id)).is_active
