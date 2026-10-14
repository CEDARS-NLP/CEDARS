"""Tests for the unified evaluation session router."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import func, select

from app.annotations.models import Annotation, AnnotationPrediction
from app.common.utils import now_utc
from app.connectors.models import Note, Patient, PatientStatus
from app.evaluation.models import EvaluationSession, SessionStatus
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.jobs.nlp import execute_nlp_job
from app.nlp.models import NlpJob, SearchQuery
from app.nlp.service import _process_notes_into_sentences, get_reprocess_impact
from app.projects.models import ProjectMember, ProjectRole


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
        assert data["exclude_negated"] is False

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
