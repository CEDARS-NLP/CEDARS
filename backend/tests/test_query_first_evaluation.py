"""Query-first orchestration and REST contract regression tests."""

from unittest.mock import AsyncMock, patch

import pytest
from app.annotations.models import Annotation
from app.common.utils import now_utc
from app.connectors.models import Note, Patient
from app.evaluation import query_first as workflow
from app.evaluation.models import (
    EvaluationAttempt,
    EvaluationSession,
    LLMPromptRevision,
    PatientResult,
    PatientResultStatus,
    SearchMatch,
    SessionStatus,
)
from app.nlp.models import SearchQuery
from app.pipeline.classifier import ClassificationResult
from app.pipeline.models import PipelineRun
from app.projects.models import Project
from sqlalchemy import func, select

from tests.conftest import seed_project_and_user
from tests.test_eval_router import create_project, register_and_login


@pytest.fixture
async def seeded(app, session_factory):
    project_id, actor = await seed_project_and_user(app)
    async with session_factory() as db:
        patient = Patient(project_id=project_id, patient_id_ext="hit")
        miss = Patient(project_id=project_id, patient_id_ext="miss")
        deleted = Patient(project_id=project_id, patient_id_ext="deleted", deleted_at=now_utc())
        db.add_all([patient, miss, deleted])
        await db.flush()
        db.add_all(
            [
                Note(
                    project_id=project_id,
                    patient_id=patient.id,
                    text_id="hit-note",
                    note_date=now_utc(),
                    text="Suspected DVT yesterday. DVT confirmed today.",
                ),
                Note(
                    project_id=project_id,
                    patient_id=patient.id,
                    text_id="miss-note",
                    note_date=now_utc(),
                    text="Normal examination.",
                ),
                Note(
                    project_id=project_id,
                    patient_id=miss.id,
                    text_id="no-hit",
                    note_date=now_utc(),
                    text="Normal examination.",
                ),
            ]
        )
        session = EvaluationSession(
            project_id=project_id,
            created_by=actor,
            workflow_version=2,
            sample_patient_ids=[patient.id, miss.id],
            sample_size=2,
        )
        old = SearchQuery(project_id=project_id, query="old", created_by=actor)
        db.add_all([session, old])
        await db.commit()
        return project_id, actor, session.id, patient.id, miss.id, old.id


async def query(db, session, actor, term="DVT"):
    return await workflow.save_query(
        db,
        session,
        [
            {"query": term, "type": "include"},
            {"query": "suspected", "type": "exclude"},
        ],
        True,
        actor,
    )


async def prompt(db, session, actor, name="DVT"):
    project = await db.get(Project, session.project_id)
    project.llm_provider = "openai"
    project.llm_model = "test-model"
    project.llm_api_key = "runtime-secret"
    db.add(project)
    await db.flush()
    return await workflow.save_prompt(
        db,
        session,
        {
            "event_name": name,
            "event_description": "Confirmed event",
            "include_criteria": "Confirmed",
            "exclude_criteria": "Suspected",
        },
        actor,
    )


async def test_keyword_full_run_no_llm_and_same_run_replay(seeded, session_factory):
    project_id, actor, session_id, patient_id, miss_id, old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        await db.commit()
        assert (await db.get(SearchQuery, old_id)).is_active
        assert not revision.is_active
        attempt = await workflow.create_attempt(db, session, revision.id, actor, scope="full")
        await db.commit()
        with patch.object(workflow, "classify_patient", new_callable=AsyncMock) as classify:
            await workflow.execute_attempt(db, attempt.id)
            await workflow.execute_attempt(db, attempt.id)
            classify.assert_not_called()
        assert attempt.status == "completed", attempt.error_message
        rows = await workflow.results(db, attempt)
        assert {row["patient_id"] for row in rows} == {patient_id, miss_id}
        assert {row["status"] for row in rows} == {"completed", "no_match"}
        annotations = list((await db.execute(select(Annotation))).scalars())
        assert len(annotations) == 1
        annotation = annotations[0]
        assert annotation.sentence_text == "DVT confirmed today."
        assert (
            annotation.attempt_id == attempt.id and annotation.evaluation_session_id == session_id
        )
        assert annotation.predicted_score is None and annotation.predicted_label is None
        assert (
            await db.scalar(
                select(func.count())
                .select_from(SearchQuery)
                .where(SearchQuery.project_id == project_id, SearchQuery.is_active.is_(True))
            )
        ) == 1
        assert not (await db.get(SearchQuery, old_id)).is_active


async def test_matched_notes_distinct_sentence_exclusion_and_history(seeded, session_factory):
    project_id, actor, session_id, patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        attempt = await workflow.create_attempt(db, session, revision.id, actor)
        await db.commit()
        await workflow.execute_attempt(db, attempt.id)
        match = (await db.execute(select(SearchMatch))).scalar_one()
        db.add(
            SearchMatch(
                session_id=session.id,
                attempt_id=attempt.id,
                query_id=revision.id,
                patient_id=patient_id,
                note_id=match.note_id,
                matched_tokens=match.matched_tokens,
                match_positions=match.match_positions,
            )
        )
        await db.commit()
        response = await workflow.matched_notes(db, session, attempt)
        assert response["total_notes"] == 1
        assert response["page"] == 1 and response["total_pages"] == 1
        note = response["notes"][0]
        assert note["patient_id"] == patient_id
        assert note["text"] == "Suspected DVT yesterday. DVT confirmed today."
        assert [sentence["text"] for sentence in note["sentences"]] == ["DVT confirmed today."]
        assert note["matches"] == [{"token": "DVT", "note_start_index": 25, "note_end_index": 28}]
        current = await db.get(Note, match.note_id)
        current.text = "Changed historical note."
        current.note_date = now_utc()
        current.deleted_at = now_utc()
        db.add(current)
        await db.commit()
        assert await workflow.matched_notes(db, session, attempt) == response
        assert (await workflow.matched_notes(db, session, attempt, page=2))["notes"] == []


async def test_history_and_commit_selected_old_pair(seeded, session_factory):
    project_id, actor, session_id, patient_id, _miss_id, old_id = seeded
    calls = []

    async def classify(excerpts, config):
        calls.append((excerpts, config.name, config.llm_model, config.llm_api_key))
        return ClassificationResult("positive", 0.9, "Confirmed", evidence=[])

    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        first_query = await query(db, session, actor)
        first_prompt = await prompt(db, session, actor)
        assert "runtime-secret" not in str(first_prompt.model_dump())
        first = await workflow.create_attempt(
            db, session, first_query.id, actor, prompt_id=first_prompt.id
        )
        await db.commit()
        with patch.object(workflow, "classify_patient", side_effect=classify):
            await workflow.execute_attempt(db, first.id)
            first_results = await workflow.results(db, first)
            hit = next(row for row in first_results if row["patient_id"] == patient_id)
            await workflow.judge(db, first, hit["id"], "correct", None, actor)
            await db.commit()
            second_query = await query(db, session, actor, "examination")
            second_prompt = await prompt(db, session, actor, "Changed draft")
            second = await workflow.create_attempt(
                db, session, second_query.id, actor, prompt_id=second_prompt.id
            )
            await db.commit()
            await workflow.execute_attempt(db, second.id)
            assert (await db.get(SearchQuery, old_id)).is_active
            assert (await db.get(PatientResult, hit["id"])).review_judgment == "correct"
            assert first.metrics["total_reviewed"] == 1
            full = await workflow.commit_attempt(db, session, first.id, actor)
            await db.commit()
            await workflow.execute_attempt(db, full.id)
        assert full.query_id == first_query.id
        assert full.prompt_revision_id == first_prompt.id
        assert full.source_attempt_id == first.id
        assert full.status == "completed", full.error_message
        assert first.sequence == 1 and second.sequence == 2 and full.sequence == 3
        assert calls[0][0][0]["text"] == "Suspected DVT yesterday. DVT confirmed today."
        assert len(calls[0][0]) == 1
        assert calls[-1][1:] == ("DVT", "test-model", "runtime-secret")
        assert len(await workflow.results(db, first)) == 2
        assert (await db.scalar(select(PipelineRun.attempt_id))) == full.id


async def test_ownership_and_provider_guard(seeded, session_factory):
    from fastapi import HTTPException

    project_id, actor, session_id, _patient_id, _miss_id, old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        with pytest.raises(HTTPException) as exc:
            await workflow.create_attempt(db, session, old_id, actor)
        assert exc.value.status_code == 404
        revision = await query(db, session, actor)
        saved_prompt = await prompt(db, session, actor)
        project = await db.get(Project, project_id)
        project.llm_provider = "anthropic"
        db.add(project)
        await db.flush()
        with pytest.raises(HTTPException) as exc:
            await workflow.create_attempt(
                db, session, revision.id, actor, prompt_id=saved_prompt.id
            )
        assert exc.value.status_code == 409


async def test_failed_attempt_retries_without_duplicates(seeded, session_factory):
    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        saved_prompt = await prompt(db, session, actor)
        attempt = await workflow.create_attempt(
            db, session, revision.id, actor, prompt_id=saved_prompt.id, scope="full"
        )
        await db.commit()
        with patch.object(workflow, "classify_patient", side_effect=ValueError("secret error")):
            await workflow.execute_attempt(db, attempt.id)
        assert attempt.status == "failed"
        note = (await db.execute(select(Note).where(Note.text_id == "hit-note"))).scalar_one()
        note.text = "Changed data without keywords."
        db.add(note)
        await db.commit()
        with patch.object(
            workflow, "classify_patient", return_value=ClassificationResult("negative", 0.9, "No")
        ) as classify:
            await workflow.execute_attempt(db, attempt.id)
            assert (
                classify.call_args.args[0][0]["text"]
                == "Suspected DVT yesterday. DVT confirmed today."
            )
        assert attempt.status == "completed"
        assert await db.scalar(select(func.count()).select_from(Annotation)) == 1
        assert "secret" not in str(await workflow.results(db, attempt))


async def test_rest_contract_and_immutable_standalone_endpoints(client):
    await register_and_login(client, "query-first@test.com")
    project_id = await create_project(client)
    response = await client.post(f"/api/v1/projects/{project_id}/evaluation/sessions", json={})
    assert response.status_code == 201
    session = response.json()
    assert session["workflow_version"] == 2
    root = f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}/v2"
    saved = await client.put(
        root + "/queries",
        json={"search_queries": [{"query": "DVT", "type": "include"}], "exclude_negated": False},
    )
    assert saved.status_code == 200, saved.text
    revision = saved.json()
    for method, suffix, body in (
        ("put", "", {"query": "changed"}),
        ("delete", "", None),
        ("post", "/activate", None),
    ):
        response = await client.request(
            method, f"/api/v1/projects/{project_id}/nlp/queries/{revision['id']}{suffix}", json=body
        )
        assert response.status_code == 409
    preview = await client.post(root + "/preview", json={"query_id": revision["id"]})
    assert preview.status_code == 200, preview.text
    assert preview.json()["status"] == "completed"
    assert preview.json()["metrics"]["matched_notes"] == 0
    assert (await client.get(root + "/state")).json()["attempts"][0]["query_revision"][
        "id"
    ] == revision["id"]
    assert (await client.get(root + f"/attempts/{preview.json()['id']}/results")).json() == []
    assert (
        await client.put(
            root + "/queries", json={"search_queries": [{"query": "DVT", "type": "exclude"}]}
        )
    ).status_code == 422
    assert (
        await client.put(
            root.removesuffix("/v2") + "/queries", json={"search_queries": [{"query": "Changed"}]}
        )
    ).status_code == 409


async def test_matches_rest_pagination_ownership_bounds_and_fallback(client, session_factory):
    from app.projects.models import ProjectMember, ProjectRole

    await register_and_login(client, "matches-query-first@test.com")
    project_id = await create_project(client)
    session = (
        await client.post(f"/api/v1/projects/{project_id}/evaluation/sessions", json={})
    ).json()
    root = f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}/v2"
    async with session_factory() as db:
        saved = await db.get(EvaluationSession, session["id"])
        patient = Patient(project_id=project_id, patient_id_ext="pagination")
        db.add(patient)
        await db.flush()
        saved.sample_patient_ids = [patient.id]
        db.add(saved)
        db.add_all(
            [
                Note(
                    id="a-note",
                    project_id=project_id,
                    patient_id=patient.id,
                    text_id="a",
                    note_date=now_utc(),
                    text="Suspected DVT yesterday. DVT confirmed today.",
                ),
                Note(
                    id="b-note",
                    project_id=project_id,
                    patient_id=patient.id,
                    text_id="b",
                    note_date=now_utc(),
                    text="DVT confirmed again.",
                ),
                Note(
                    id="c-note",
                    project_id=project_id,
                    patient_id=patient.id,
                    text_id="c",
                    note_date=now_utc(),
                    text="Suspected DVT only.",
                ),
            ]
        )
        await db.commit()
    revision = (
        await client.put(
            root + "/queries",
            json={
                "search_queries": [
                    {"query": "DVT", "type": "include"},
                    {"query": "DVT", "type": "include"},
                    {"query": "suspected", "type": "exclude"},
                ]
            },
        )
    ).json()
    response = await client.post(root + "/preview", json={"query_id": revision["id"]})
    assert response.status_code == 200, response.text
    attempt_id = response.json()["id"]
    path = root + f"/attempts/{attempt_id}/matches"
    async with session_factory() as db:
        duplicate = await db.execute(select(SearchMatch).where(SearchMatch.note_id == "a-note"))
        duplicate = duplicate.scalar_one()
        db.add(
            SearchMatch(
                session_id=session["id"],
                attempt_id=attempt_id,
                query_id=revision["id"],
                note_id=duplicate.note_id,
                patient_id=duplicate.patient_id,
                match_positions=duplicate.match_positions,
                matched_tokens=duplicate.matched_tokens,
            )
        )
        other = EvaluationSession(
            project_id=project_id, created_by=session["created_by"], workflow_version=2
        )
        db.add(other)
        await db.commit()
        other_id = other.id
    response = await client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert set(body) == {"notes", "total_notes", "page", "total_pages"}
    assert body["total_notes"] == 2 and body["total_pages"] == 1 and body["page"] == 1
    assert [note["note_id"] for note in body["notes"]] == ["a-note", "b-note"]
    first = body["notes"][0]
    assert set(first) == {"note_id", "patient_id", "text", "note_date", "matches", "sentences"}
    assert first["text"] == "Suspected DVT yesterday. DVT confirmed today."
    assert first["note_date"]
    assert first["matches"] == [{"token": "DVT", "note_start_index": 25, "note_end_index": 28}]
    assert [sentence["text"] for sentence in first["sentences"]] == ["DVT confirmed today."]
    for page, expected in ((1, "a-note"), (2, "b-note")):
        paged = (await client.get(path, params={"page": page, "page_size": 1})).json()
        assert paged["total_notes"] == 2 and paged["total_pages"] == 2
        assert paged["page"] == page
        assert [note["note_id"] for note in paged["notes"]] == [expected]
    assert (await client.get(path, params={"page": 3, "page_size": 1})).json()["notes"] == []
    for params in (
        {"page": 0},
        {"page": -1},
        {"page": 1_000_001},
        {"page_size": 0},
        {"page_size": -1},
        {"page_size": 101},
    ):
        assert (await client.get(path, params=params)).status_code == 422
    other_root = f"/api/v1/projects/{project_id}/evaluation/sessions/{other_id}/v2"
    assert (await client.get(other_root + f"/attempts/{attempt_id}/matches")).status_code == 404
    assert (await client.get(root + "/attempts/nonexistent/matches")).status_code == 404
    async with session_factory() as db:
        result = (
            await db.execute(
                select(PatientResult).where(
                    PatientResult.attempt_id == attempt_id,
                )
            )
        ).scalar_one()
        result.input_snapshot = None
        db.add(result)
        member = (
            await db.execute(
                select(ProjectMember).where(
                    ProjectMember.project_id == project_id,
                )
            )
        ).scalar_one()
        member.role = ProjectRole.VIEWER
        db.add(member)
        await db.commit()
    fallback = await client.get(path)
    assert fallback.status_code == 200
    assert fallback.json()["notes"][0]["text"] == first["text"]
    assert fallback.json()["notes"][0]["sentences"] == first["sentences"]
    assert (
        await client.post(root + "/preview", json={"query_id": revision["id"]})
    ).status_code == 403


@pytest.fixture
async def judgment_api(client, session_factory):
    await register_and_login(client, "judgment-query-first@test.com")
    project_id = await create_project(client)
    response = await client.post(f"/api/v1/projects/{project_id}/evaluation/sessions", json={})
    assert response.status_code == 201, response.text
    session_id = response.json()["id"]
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, session.created_by)
        saved_prompt = await prompt(db, session, session.created_by)
        attempt = await workflow.create_attempt(
            db, session, revision.id, session.created_by, prompt_id=saved_prompt.id
        )
        attempt.status = "completed"
        db.add(attempt)
        result = PatientResult(
            session_id=session_id,
            attempt_id=attempt.id,
            patient_id="judgment-patient",
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
        )
        db.add(result)
        await db.commit()
        root = f"/api/v1/projects/{project_id}/evaluation/sessions/{session_id}/v2"
        return root, session_id, attempt.id, result.id


@pytest.mark.parametrize("status", ["committed", "completed", "discarded"])
async def test_judgment_api_rejects_locked_sessions(client, session_factory, judgment_api, status):
    root, session_id, attempt_id, result_id = judgment_api
    async with session_factory() as db:
        session = await db.get(EvaluationSession, session_id)
        session.status = SessionStatus(status)
        db.add(session)
        await db.commit()
    response = await client.post(
        root + f"/attempts/{attempt_id}/results/{result_id}/judge",
        json={"judgment": "correct"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "This session is read-only"
    async with session_factory() as db:
        result = await db.get(PatientResult, result_id)
        assert result.review_judgment is None
        assert result.reviewed_by is None and result.reviewed_at is None
        assert (await db.get(EvaluationAttempt, attempt_id)).metrics == {}


@pytest.mark.parametrize(
    ("mode", "scope", "status"),
    [
        ("llm", "full", "completed"),
        ("search", "sample", "completed"),
        ("search", "full", "completed"),
        ("llm", "sample", "queued"),
        ("llm", "sample", "running"),
        ("llm", "sample", "failed"),
        ("llm", "sample", "cancelled"),
    ],
)
async def test_judgment_api_rejects_nonreviewable_attempts(
    client, session_factory, judgment_api, mode, scope, status
):
    root, _session_id, attempt_id, result_id = judgment_api
    async with session_factory() as db:
        attempt = await db.get(EvaluationAttempt, attempt_id)
        attempt.mode = mode
        attempt.scope = scope
        attempt.status = status
        db.add(attempt)
        await db.commit()
    response = await client.post(
        root + f"/attempts/{attempt_id}/results/{result_id}/judge",
        json={"judgment": "correct"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Only completed sample LLM attempts can be judged"
    async with session_factory() as db:
        result = await db.get(PatientResult, result_id)
        assert result.review_judgment is None
        assert result.reviewed_by is None and result.reviewed_at is None
        assert (await db.get(EvaluationAttempt, attempt_id)).metrics == {}


@pytest.mark.parametrize("status", ["draft", "reviewing"])
async def test_judgment_api_allows_older_completed_attempts(
    client, session_factory, judgment_api, status
):
    root, session_id, attempt_id, result_id = judgment_api
    async with session_factory() as db:
        session = await db.get(EvaluationSession, session_id)
        revision = await query(db, session, session.created_by, "examination")
        saved_prompt = await prompt(db, session, session.created_by, "Changed draft")
        newer = await workflow.create_attempt(
            db, session, revision.id, session.created_by, prompt_id=saved_prompt.id
        )
        assert newer.sequence > (await db.get(EvaluationAttempt, attempt_id)).sequence
        session.status = SessionStatus(status)
        db.add(session)
        await db.commit()
        actor = session.created_by
        newer_id = newer.id
    response = await client.post(
        root + f"/attempts/{attempt_id}/results/{result_id}/judge",
        json={"judgment": "correct", "event_date_override": "2026-10-14"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["review_judgment"] == "correct"
    async with session_factory() as db:
        result = await db.get(PatientResult, result_id)
        assert result.review_judgment == "correct"
        assert result.reviewer_date_override == "2026-10-14"
        assert result.reviewed_by == actor and result.reviewed_at is not None
        assert (await db.get(EvaluationAttempt, attempt_id)).metrics["total_reviewed"] == 1
        assert (await db.get(EvaluationAttempt, newer_id)).metrics == {}
        assert (await db.get(EvaluationSession, session_id)).status == status


@pytest.mark.parametrize("status", ["queued", "processing", "failed", "no_match"])
async def test_judgment_api_preserves_completed_result_guard(
    client, session_factory, judgment_api, status
):
    root, _session_id, attempt_id, result_id = judgment_api
    async with session_factory() as db:
        result = await db.get(PatientResult, result_id)
        result.status = PatientResultStatus(status)
        db.add(result)
        await db.commit()
    response = await client.post(
        root + f"/attempts/{attempt_id}/results/{result_id}/judge",
        json={"judgment": "correct"},
    )
    assert response.status_code == 409, response.text
    assert response.json()["detail"] == "Only completed results can be judged"
    async with session_factory() as db:
        assert (await db.get(PatientResult, result_id)).review_judgment is None


async def test_direct_session_fixtures_stay_legacy(seeded, session_factory):
    project_id, actor, _session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        legacy = EvaluationSession(project_id=project_id, created_by=actor)
        db.add(legacy)
        await db.commit()
        assert legacy.workflow_version == 1
        assert await db.scalar(select(func.count()).select_from(LLMPromptRevision)) == 0
        assert await db.scalar(select(func.count()).select_from(EvaluationAttempt)) == 0


async def test_distinct_full_runs_keep_separate_annotations(seeded, session_factory):
    from app.pipeline.orchestrator import rerun

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        first = await workflow.create_attempt(db, session, revision.id, actor, scope="full")
        await db.commit()
        await workflow.execute_attempt(db, first.id)
        run = (
            await db.execute(select(PipelineRun).where(PipelineRun.attempt_id == first.id))
        ).scalar_one()
        second_run = await rerun(db, project_id, run.id, actor)
        assert second_run.attempt_id != first.id
        annotations = (await db.execute(select(Annotation))).scalars().all()
        assert len(annotations) == 2
        assert len({annotation.attempt_id for annotation in annotations}) == 2


async def test_rest_permissions_cancel_resume_clone(client, app):
    from app.projects.models import ProjectMember, ProjectRole

    await register_and_login(client, "roles-query-first@test.com")
    project_id = await create_project(client)
    session = (
        await client.post(f"/api/v1/projects/{project_id}/evaluation/sessions", json={})
    ).json()
    root = f"/api/v1/projects/{project_id}/evaluation/sessions/{session['id']}/v2"
    revision = (
        await client.put(
            root + "/queries", json={"search_queries": [{"query": "DVT", "type": "include"}]}
        )
    ).json()
    with patch.object(workflow, "dispatch", new_callable=AsyncMock):
        attempt = (await client.post(root + "/run-all", json={"query_id": revision["id"]})).json()
    cancelled = await client.post(root + f"/attempts/{attempt['id']}/cancel")
    assert cancelled.json()["status"] == "cancelled"
    resumed = await client.post(root + f"/attempts/{attempt['id']}/resume")
    assert resumed.json()["status"] == "completed"
    cloned = await client.post(root.removesuffix("/v2") + "/clone")
    assert cloned.status_code == 201, cloned.text
    assert cloned.json()["workflow_version"] == 2
    clone_root = f"/api/v1/projects/{project_id}/evaluation/sessions/{cloned.json()['id']}/v2"
    clone_state = (await client.get(clone_root + "/state")).json()
    assert clone_state["query_revision"]["id"] != revision["id"]
    assert clone_state["query_revision"]["source_queries"] == revision["source_queries"]
    assert clone_state["attempts"] == []
    async with app.state.test_session_factory() as db:
        member = (
            await db.execute(select(ProjectMember).where(ProjectMember.project_id == project_id))
        ).scalar_one()
        member.role = ProjectRole.VIEWER
        db.add(member)
        await db.commit()
    assert (await client.get(clone_root + "/state")).status_code == 200
    assert (
        await client.post(
            clone_root + "/preview", json={"query_id": clone_state["query_revision"]["id"]}
        )
    ).status_code == 403
    assert (
        await client.post(
            root + f"/attempts/{attempt['id']}/results/1/judge", json={"judgment": "correct"}
        )
    ).status_code == 403


async def test_zero_success_cannot_commit_and_get_does_not_touch_heartbeat(seeded, session_factory):
    from fastapi import HTTPException

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor, "missing")
        saved_prompt = await prompt(db, session, actor)
        attempt = await workflow.create_attempt(
            db, session, revision.id, actor, prompt_id=saved_prompt.id
        )
        await db.commit()
        with patch.object(workflow, "classify_patient", new_callable=AsyncMock) as classify:
            await workflow.execute_attempt(db, attempt.id)
            classify.assert_not_called()
        timestamp = attempt.updated_at
        await workflow.state(db, session)
        assert attempt.updated_at == timestamp
        with pytest.raises(HTTPException) as exc:
            await workflow.commit_attempt(db, session, attempt.id, actor)
        assert exc.value.status_code == 409


def test_additive_migration_roundtrip_preserves_legacy_query():
    import importlib.util
    from pathlib import Path

    import sqlalchemy as sa
    from alembic.migration import MigrationContext
    from alembic.operations import Operations

    path = Path(__file__).parents[1] / "migrations/versions/7c91d2e8f640_query_first_evaluation.py"
    spec = importlib.util.spec_from_file_location("query_first_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    metadata = sa.MetaData()
    for name in (
        "users",
        "projects",
        "notes",
        "evaluation_sessions_v2",
        "pipeline_runs",
        "search_matches",
    ):
        sa.Table(name, metadata, sa.Column("id", sa.String(), primary_key=True))
    sa.Table(
        "patient_results",
        metadata,
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("patient_id", sa.String()),
    )
    sa.Table(
        "annotations",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("note_id", sa.String()),
        sa.Column("sentence_start", sa.Integer()),
        sa.Column("sentence_end", sa.Integer()),
    )
    search = sa.Table(
        "search_queries",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("project_id", sa.String()),
        sa.Column("is_active", sa.Boolean()),
        sa.Column("deleted_at", sa.DateTime()),
    )
    sa.Index(
        "uq_search_queries_project_active",
        search.c.project_id,
        unique=True,
        sqlite_where=sa.text("is_active AND deleted_at IS NULL"),
    )
    metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(
            search.insert().values(id="legacy", project_id="project", is_active=True)
        )
        operations = Operations(MigrationContext.configure(connection))
        with patch.object(migration, "op", operations):
            migration.upgrade()
            assert connection.exec_driver_sql(
                "SELECT evaluation_session_id, syntax_version, is_active FROM search_queries"
            ).one() == (None, 1, 1)
            migration.downgrade()
            migration.upgrade()
        assert "uq_search_queries_project_active" in {
            index["name"] for index in sa.inspect(connection).get_indexes("search_queries")
        }
        assert connection.exec_driver_sql("SELECT count(*) FROM evaluation_attempts").scalar() == 0
    engine.dispose()


async def test_worker_receives_attempt_id_and_replay_is_idempotent(seeded, session_factory):
    from app.worker import run_query_first_attempt_job

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        attempt = await workflow.create_attempt(db, session, revision.id, actor, scope="full")
        await db.commit()
    with patch("app.common.database.async_session", session_factory):
        assert await run_query_first_attempt_job({}, attempt.id) == {"attempt_id": attempt.id}
        await run_query_first_attempt_job({}, attempt.id)
    async with session_factory() as db:
        assert await db.scalar(select(func.count()).select_from(Annotation)) == 1
        saved = await db.get(EvaluationAttempt, attempt.id)
        assert saved.status == "completed"


async def test_stale_claim_cannot_write_after_cancellation(seeded, session_factory):
    from sqlalchemy import update

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        saved_prompt = await prompt(db, session, actor)
        attempt = await workflow.create_attempt(
            db, session, revision.id, actor, prompt_id=saved_prompt.id, scope="full"
        )
        await db.commit()
        saved_id = attempt.id

        async def cancel_during_classification(excerpts, config):
            await db.execute(
                update(EvaluationAttempt)
                .where(EvaluationAttempt.id == saved_id)
                .values(status="cancelled", claim_token=None)
            )
            await db.commit()
            return ClassificationResult("positive", 0.9, "Late response")

        with patch.object(workflow, "classify_patient", side_effect=cancel_during_classification):
            await workflow.execute_attempt(db, saved_id)
    async with session_factory() as db:
        saved = await db.get(EvaluationAttempt, saved_id)
        assert saved.status == "cancelled"
        assert await db.scalar(select(func.count()).select_from(Annotation)) == 0


async def test_setup_failure_releases_attempt_for_retry(seeded, session_factory):
    from fastapi import HTTPException

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        attempt = await workflow.create_attempt(db, session, revision.id, actor, scope="full")
        saved_id = attempt.id
        await db.commit()
        with patch.object(workflow, "owned_query", side_effect=HTTPException(404, "Missing")):
            await workflow.execute_attempt(db, saved_id)
    async with session_factory() as db:
        attempt = await db.get(EvaluationAttempt, saved_id)
        assert attempt.status == "failed"
        assert attempt.error_message == "Attempt execution failed; retry this attempt"
        run = (await db.execute(select(PipelineRun))).scalar_one()
        assert run.status == "failed"
        await workflow.execute_attempt(db, saved_id)
        await db.refresh(attempt)
        assert attempt.status == "completed"


async def test_cancel_during_setup_does_not_restart_pipeline(seeded, session_factory):
    from app.pipeline.models import PipelineRunStatus
    from sqlalchemy import update

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        attempt = await workflow.create_attempt(db, session, revision.id, actor, scope="full")
        saved_id = attempt.id
        await db.commit()

        async def cancel_during_lookup(*args):
            await db.execute(
                update(EvaluationAttempt)
                .where(EvaluationAttempt.id == saved_id)
                .values(status="cancelled", claim_token=None)
            )
            await db.execute(
                update(PipelineRun)
                .where(PipelineRun.attempt_id == saved_id)
                .values(status=PipelineRunStatus.CANCELLED, is_cancelled=True)
            )
            await db.commit()
            return revision

        with patch.object(workflow, "owned_query", side_effect=cancel_during_lookup):
            await workflow.execute_attempt(db, saved_id)
    async with session_factory() as db:
        assert (await db.get(EvaluationAttempt, saved_id)).status == "cancelled"
        run = (await db.execute(select(PipelineRun))).scalar_one()
        assert run.status == PipelineRunStatus.CANCELLED
        assert await db.scalar(select(func.count()).select_from(SearchMatch)) == 0


async def test_worker_startup_recovers_sample_attempt(seeded, session_factory):
    from app.worker import on_worker_startup

    project_id, actor, session_id, _patient_id, _miss_id, _old_id = seeded
    async with session_factory() as db:
        session = await workflow.owned_session(db, project_id, session_id, writable=True)
        revision = await query(db, session, actor)
        attempt = await workflow.create_attempt(db, session, revision.id, actor)
        attempt.status = "running"
        attempt.claim_token = "previous-worker"
        db.add(attempt)
        await db.commit()
    redis = AsyncMock()
    with patch("app.common.database.async_session", session_factory):
        await on_worker_startup({"redis": redis})
    redis.enqueue_job.assert_awaited_once_with("run_query_first_attempt_job", attempt.id)
    async with session_factory() as db:
        saved = await db.get(EvaluationAttempt, attempt.id)
        assert saved.status == "queued" and saved.claim_token is None
