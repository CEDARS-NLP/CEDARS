"""Migration-backed regressions for review attribution and prediction completion."""

from dataclasses import asdict
from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlalchemy.dialects import postgresql
from sqlmodel.ext.asyncio.session import AsyncSession

from app.annotations.completion_service import complete_negative_llm_patients
from app.annotations.filters import reviewable_filter
from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
from app.annotations.review_service import (
    ReopenConflictError,
    reopen_patient,
)
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.export.service import export_annotations
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp.models import SearchQuery, Sentence
from app.predictors.base import PredictorError, TokenUsage
from app.predictors.models import PredictorConfig, PredictorType
from app.production.classifier import NoteClassification
from app.production.models import NotePrediction, ProductionRun, ProductionState
from app.production.service import execute_run, start_run
from app.projects.models import Project, ProjectMember, ProjectRole, ProjectUser


def _id() -> str:
    return str(uuid4())


async def _seed_project(
    session: AsyncSession,
    *,
    annotation_count: int = 1,
    patient_status: PatientStatus = PatientStatus.REVIEWING,
    review_source: str | None = None,
    note_text: str = "Patient has a target finding.",
):
    user_id, project_id, patient_id, note_id = (_id() for _ in range(4))
    user = User(id=user_id, email=f"{user_id}@test.invalid", name="Test", password_hash="x")
    session.add(user)
    await session.flush()

    project = Project(id=project_id, name="Regression project", owner_id=user_id)
    session.add(project)
    await session.flush()
    session.add(ProjectMember(project_id=project_id, user_id=user_id, role=ProjectRole.ADMIN))
    session.add(
        ProjectUser(
            global_user_id=user_id,
            project_id=project_id,
            email=user.email,
            name=user.name,
            role=ProjectRole.ADMIN,
            is_investigator=True,
        )
    )
    patient = Patient(
        id=patient_id,
        project_id=project_id,
        patient_id_ext=f"external-{patient_id}",
        status=patient_status,
        review_source=review_source,
        review_reason="seeded_review_reason" if review_source else None,
        reviewed_by=user_id if review_source == "human" else None,
        reviewed_at=datetime.now(UTC) if review_source else None,
    )
    session.add(patient)
    await session.flush()

    note = Note(
        id=note_id,
        project_id=project_id,
        patient_id=patient_id,
        patient_id_ext=patient.patient_id_ext,
        text_id=f"text-{note_id}",
        note_date=datetime(2026, 1, 1, tzinfo=UTC),
        text=note_text,
    )
    session.add(note)
    await session.flush()

    annotations = []
    for index in range(annotation_count):
        sentence = f"Sentence {index}."
        annotation = Annotation(
            project_id=project_id,
            text_id=note.text_id,
            patient_id=patient.patient_id_ext,
            patient_uuid=patient_id,
            note_uuid=note_id,
            sentence=sentence,
            token="target",
            isNegated=False,
            note_start_index=index * 10,
            note_end_index=index * 10 + 6,
            sentence_number=index,
            sentence_start=index * 10,
            sentence_end=index * 10 + len(sentence),
            text_date=note.note_date.date(),
            status="U",
        )
        session.add(annotation)
        annotations.append(annotation)

    config = PredictorConfig(
        id=_id(),
        project_id=project_id,
        predictor_type=PredictorType.LLM,
        name="Regression LLM",
        config={"provider": "ollama", "model": "test-model"},
        is_active=True,
        created_by=user_id,
    )
    job = BackgroundJob(
        id=_id(),
        project_id=project_id,
        job_type=JobType.PREDICTION,
    )
    session.add_all([config, job, SearchQuery(project_id=project_id, query="target")])
    await session.commit()
    return {
        "user_id": user_id,
        "project_id": project_id,
        "patient_id": patient_id,
        "note_id": note_id,
        "text_id": note.text_id,
        "patient_external_id": patient.patient_id_ext,
        "annotations": annotations,
        "config_id": config.id,
        "job_id": job.id,
    }


@pytest.mark.parametrize("writer", ["bulk", "worker"])
@pytest.mark.parametrize(
    "token_usage",
    [TokenUsage(prompt_tokens=11, completion_tokens=4, total_tokens=15), None],
)
async def test_prediction_writers_persist_optional_usage_and_complete_worker_job(
    session_factory, writer, token_usage
):
    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=0)

    result = NoteClassification(
        score=0.91,
        label=1,
        reasoning="positive full-note result",
        evidence_spans=[],
        token_usage=asdict(token_usage) if token_usage else None,
    )
    with patch("app.production.service.classify_note", new=AsyncMock(return_value=result)) as classify:
        if writer == "bulk":
            from app.annotations.prediction_service import run_bulk_predictions

            async with session_factory() as session:
                stats = await run_bulk_predictions(session, seeded["project_id"])
        else:
            async with session_factory() as session:
                run = await start_run(
                    session, seeded["project_id"], seeded["user_id"],
                    {"query": "target", "llm_config": {"provider": "ollama", "model": "test-model"}},
                )
                job = await session.get(BackgroundJob, seeded["job_id"])
                job.result_summary = {"production_run_id": run.id}
                await session.commit()
            from app.jobs.prediction import execute_prediction_job

            stats = await execute_prediction_job(
                seeded["project_id"], seeded["job_id"], session_factory
            )
    classify.assert_awaited_once()
    assert classify.await_args.args[0] == "Patient has a target finding."
    assert stats["predictions_made"] == 1

    async with session_factory() as session:
        prediction = (
            await session.execute(
                select(NotePrediction).where(
                    NotePrediction.project_id == seeded["project_id"]
                )
            )
        ).scalar_one()
        assert prediction.token_usage == (asdict(token_usage) if token_usage else None)
        assert prediction.label == 1
        assert prediction.status == "succeeded"
        assert prediction.text_id == seeded["text_id"]
        state = await session.get(ProductionState, seeded["project_id"])
        run = await session.get(ProductionRun, state.active_run_id)
        assert run.status == "completed"

        if writer == "worker":
            job = await session.get(BackgroundJob, seeded["job_id"])
            assert job.status == JobStatus.COMPLETED
            assert job.progress == 100


@pytest.mark.parametrize(
    ("labels", "expected_source"),
    [([0, 0], "llm"), ([0, None], None), ([0, 1], None)],
)
async def test_llm_completion_requires_every_visible_annotation_negative(
    session_factory, labels, expected_source
):
    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=2)
        config = await session.get(PredictorConfig, seeded["config_id"])
        for annotation, label in zip(seeded["annotations"], labels, strict=True):
            if label is not None:
                session.add(
                    AnnotationPrediction(
                        annotation_id=annotation.id,
                        project_id=seeded["project_id"],
                        predictor_config_id=config.id,
                        predictor_model="mock-model",
                        predicted_label=label,
                        predicted_score=0.8,
                    )
                )
        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        await session.commit()

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        assert (expected_source == "llm") is all(label == 0 for label in labels)
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None
        assert await session.scalar(select(NotePrediction)) is None


async def test_manual_override_prevents_llm_auto_completion(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        annotation.status = "R"
        annotation.reviewed_by = seeded["user_id"]
        annotation.reviewed_at = datetime.now(UTC)
        session.add(
            AnnotationPrediction(
                annotation_id=annotation.id,
                project_id=seeded["project_id"],
                predictor_config_id=seeded["config_id"],
                predicted_label=0,
                predicted_score=0.2,
            )
        )
        config = await session.get(PredictorConfig, seeded["config_id"])
        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        await session.commit()

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        annotation = await session.get(Annotation, seeded["annotations"][0].annotation_id)
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None
        assert annotation.status == "R"
        assert annotation.reviewed_by == seeded["user_id"]


async def test_prediction_error_does_not_auto_complete_patient(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=0)
        run = await start_run(
            session,
            seeded["project_id"],
            seeded["user_id"],
            {"query": "target", "llm_config": {"provider": "ollama", "model": "test-model"}},
        )

    with patch(
        "app.production.service.classify_note",
        new=AsyncMock(side_effect=PredictorError("mock provider failure")),
    ):
        async with session_factory() as session:
            run = await execute_run(session, run.id)

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        assert patient.status == PatientStatus.NLP_PROCESSING
        assert patient.review_source is None
        prediction = await session.scalar(select(NotePrediction))
        assert run.status == "failed"
        assert prediction.status == "failed"
        assert prediction.error == "mock provider failure"
        assert patient.event_date is None


async def test_automated_processing_preserves_human_provenance(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(
            session, patient_status=PatientStatus.REVIEWED, review_source="human",
            annotation_count=1,
        )
        annotation = seeded["annotations"][0]
        annotation.status = "R"
        annotation.review_reason = "human_event"
        annotation.reviewed_by = seeded["user_id"]
        annotation.reviewed_at = datetime.now(UTC)
        patient = await session.get(Patient, seeded["patient_id"])
        patient.event_date = date(2026, 1, 1)
        patient.event_annotation_id = annotation.annotation_id
        patient.event_reviewer = seeded["user_id"]
        session.add_all([annotation, _prediction(seeded, annotation, seeded["config_id"], 0)])
        await session.commit()

        config = await session.get(PredictorConfig, seeded["config_id"])
        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        await session.commit()

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        assert patient.status == PatientStatus.REVIEWED
        assert patient.review_source == "human"
        assert patient.review_reason == "seeded_review_reason"
        assert patient.reviewed_by == seeded["user_id"]
        assert patient.reviewed_at is not None
        assert patient.event_date == date(2026, 1, 1)
        assert patient.event_annotation_id == seeded["annotations"][0].annotation_id
        assert patient.event_reviewer == seeded["user_id"]
        annotation = await session.get(Annotation, seeded["annotations"][0].annotation_id)
        assert annotation.status == "R"
        assert annotation.review_reason == "human_event"


async def test_cedars_processing_creates_excluded_negated_annotation_and_keeps_no_match(
    session_factory,
):
    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=0, note_text="Patient is stable.")
        other_patient_id, other_note_id = _id(), _id()
        other_external_id = f"external-{other_patient_id}"
        other_text_id = f"text-{other_note_id}"
        session.add(
            Patient(
                id=other_patient_id,
                project_id=seeded["project_id"],
                patient_id_ext=other_external_id,
                status=PatientStatus.REVIEWING,
            )
        )
        await session.flush()
        session.add(
            Note(
                id=other_note_id,
                project_id=seeded["project_id"],
                patient_id=other_patient_id,
                patient_id_ext=other_external_id,
                text_id=other_text_id,
                note_date=datetime(2026, 1, 2, tzinfo=UTC),
                text="No evidence of DVT.",
            )
        )
        run = await start_run(
            session, seeded["project_id"], seeded["user_id"],
            {"query": "DVT", "exclude_negated": True},
        )
        run = await execute_run(session, run.id)
        annotations = (await session.scalars(select(Annotation))).all()
        assert run.status == "completed"
        assert len(annotations) == 1
        assert annotations[0].isNegated is True
        assert annotations[0].status == "R"
        assert annotations[0].review_reason == "negated"
        assert annotations[0].actor_type == "system"
        no_match_patient = await session.get(Patient, seeded["patient_id"])
        negated_patient = await session.get(Patient, other_patient_id)
        assert no_match_patient.review_reason == "production_complete"
        assert negated_patient.review_reason == "production_complete"


async def test_reopening_patient_restores_excluded_rows_and_preserves_predictions(
    session_factory,
):
    async with session_factory() as session:
        seeded = await _seed_project(
            session,
            annotation_count=2,
            patient_status=PatientStatus.REVIEWED,
            review_source="human",
        )
        event_annotation, excluded_annotation = seeded["annotations"]
        event_annotation.status = "R"
        event_annotation.review_reason = "human_event"
        event_annotation.reviewed_by = seeded["user_id"]
        event_annotation.reviewed_at = datetime.now(UTC)
        excluded_annotation.status = "R"
        excluded_annotation.review_reason = "duplicate"
        excluded_annotation.actor_type = "system"
        patient = await session.get(Patient, seeded["patient_id"])
        patient.event_date = date(2026, 1, 1)
        patient.event_annotation_id = event_annotation.annotation_id
        patient.event_reviewer = seeded["user_id"]
        patient.locked_by = seeded["user_id"]
        patient.locked_at = datetime.now(UTC)
        session.add_all([event_annotation, excluded_annotation, patient])
        assert await reopen_patient(
            session, seeded["project_id"], seeded["patient_id"], seeded["user_id"]
        )

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        event_annotation = await session.get(
            Annotation, seeded["annotations"][0].annotation_id
        )
        excluded_annotation = await session.get(
            Annotation, seeded["annotations"][1].annotation_id
        )
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None
        assert patient.review_reason is None
        assert patient.reviewed_by is None
        assert patient.reviewed_at is None
        assert patient.locked_by is None
        assert patient.locked_at is None
        assert patient.event_date == date(2026, 1, 1)
        assert patient.event_annotation_id == event_annotation.annotation_id
        assert patient.event_reviewer == seeded["user_id"]
        assert (event_annotation.status, event_annotation.review_reason) == ("R", "human_event")
        assert (excluded_annotation.status, excluded_annotation.review_reason) == (
            "R",
            "duplicate",
        )


async def test_reopening_reviewed_patient_without_annotations_conflicts(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(
            session,
            annotation_count=0,
            patient_status=PatientStatus.REVIEWED,
            review_source="llm",
        )
        with pytest.raises(ReopenConflictError):
            await reopen_patient(
                session, seeded["project_id"], seeded["patient_id"], seeded["user_id"]
            )


async def test_export_includes_manual_override_and_patient_review_attribution(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(
            session,
            patient_status=PatientStatus.REVIEWED,
            review_source="llm",
        )
        annotation = seeded["annotations"][0]
        annotation.status = "R"
        annotation.review_reason = "human_negative"
        session.add(annotation)
        await session.commit()

        rows = await export_annotations(session, seeded["project_id"])
        assert len(rows) == 1
        assert rows[0]["review_status"] == ReviewStatus.REVIEWED.value
        assert rows[0]["patient_review_source"] == "llm"
        assert rows[0]["patient_review_reason"] == "seeded_review_reason"
        assert rows[0]["patient_reviewed_by"] is None
        assert rows[0]["patient_reviewed_at"] is not None


async def test_reprocess_requires_matching_impact_and_deletes_confirmed_rows(
    auth_client, session_factory
):
    project_response = await auth_client.post(
        "/api/v1/projects", json={"name": "Reprocess regression project"}
    )
    assert project_response.status_code == 201
    project_id = project_response.json()["id"]

    async with session_factory() as session:
        user = (
            await session.execute(select(User).where(User.email == "test@example.com"))
        ).scalar_one()
        patient_id, note_id, sentence_id = _id(), _id(), _id()
        session.add(
            Patient(
                id=patient_id,
                project_id=project_id,
                patient_id_ext=f"external-{patient_id}",
                status=PatientStatus.NLP_COMPLETE,
            )
        )
        await session.flush()
        session.add(
            Note(
                id=note_id,
                project_id=project_id,
                patient_id=patient_id,
                patient_id_ext=f"external-{patient_id}",
                text_id=f"text-{note_id}",
                note_date=datetime(2026, 1, 3, tzinfo=UTC),
                text="No active NLP processing is needed.",
                deleted_at=datetime.now(UTC),
            )
        )
        await session.flush()
        session.add(
            Sentence(
                id=sentence_id,
                note_id=note_id,
                project_id=project_id,
                sentence_number=0,
                text="No active NLP processing is needed.",
                start_pos=0,
                end_pos=36,
            )
        )
        session.add(SearchQuery(project_id=project_id, query="NLP", created_by=user.id))
        await session.flush()
        annotation = Annotation(
            project_id=project_id,
            text_id=f"text-{note_id}",
            patient_id=f"external-{patient_id}",
            patient_uuid=patient_id,
            note_uuid=note_id,
            text_date=date(2026, 1, 3),
            sentence="No active NLP processing is needed.",
            token="NLP",
            isNegated=False,
            note_start_index=8,
            note_end_index=11,
            sentence_number=0,
            sentence_start=0,
            sentence_end=36,
        )
        session.add(annotation)
        await session.flush()
        production_run = ProductionRun(
            project_id=project_id,
            created_by=user.id,
            status="completed",
            config_snapshot={},
            total_notes=1,
        )
        session.add(production_run)
        await session.flush()
        session.add(NotePrediction(
            project_id=project_id,
            run_id=production_run.id,
            text_id=f"text-{note_id}",
            patient_id=f"external-{patient_id}",
            note_uuid=note_id,
            patient_uuid=patient_id,
            status="succeeded",
            label=1,
        ))
        await session.commit()

    endpoint = f"/api/v1/projects/{project_id}/nlp/reprocess"
    impact_response = await auth_client.get(
        f"/api/v1/projects/{project_id}/nlp/reprocess-impact"
    )
    assert impact_response.status_code == 200
    impact = impact_response.json()
    assert impact == {"annotations": 1, "predictions": 1, "sentences": 1}
    expected = {
        "expected_annotations": impact["annotations"],
        "expected_predictions": impact["predictions"],
        "expected_sentences": impact["sentences"],
    }

    missing_confirmation = await auth_client.post(endpoint, json={})
    assert missing_confirmation.status_code == 422
    unconfirmed = await auth_client.post(
        endpoint, json={"confirmed": False, **expected}
    )
    assert unconfirmed.status_code == 400
    mismatch = await auth_client.post(
        endpoint,
        json={"confirmed": True, **{**expected, "expected_annotations": 2}},
    )
    assert mismatch.status_code == 409
    unchanged = await auth_client.get(
        f"/api/v1/projects/{project_id}/nlp/reprocess-impact"
    )
    assert unchanged.json() == impact

    async with session_factory() as session:
        busy_job = BackgroundJob(project_id=project_id, job_type=JobType.PREDICTION)
        session.add(busy_job)
        await session.commit()
        busy_job_id = busy_job.id
    busy = await auth_client.post(endpoint, json={"confirmed": True, **expected})
    assert busy.status_code == 409
    async with session_factory() as session:
        busy_job = await session.get(BackgroundJob, busy_job_id)
        busy_job.status = JobStatus.COMPLETED
        await session.commit()

    confirmed = await auth_client.post(endpoint, json={"confirmed": True, **expected})
    assert confirmed.status_code == 200
    after = await auth_client.get(f"/api/v1/projects/{project_id}/nlp/reprocess-impact")
    assert after.status_code == 200
    assert after.json() == {"annotations": 0, "predictions": 0, "sentences": 0}

def _prediction(seeded, annotation, config_id, label):
    return AnnotationPrediction(
        annotation_id=annotation.id,
        project_id=seeded["project_id"],
        predictor_config_id=config_id,
        predictor_model="mock-model",
        predicted_label=label,
        predicted_score=0.8,
    )


async def test_llm_completion_closes_patient_with_human_and_negative_annotations(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=2)
        config = await session.get(PredictorConfig, seeded["config_id"])
        reviewed, hidden = seeded["annotations"]
        reviewed.status = "R"
        reviewed.review_reason = "human_negative"
        reviewed.reviewed_by = seeded["user_id"]
        session.add(reviewed)
        session.add(_prediction(seeded, hidden, config.id, 0))
        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        await session.commit()

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        annotations = list(await session.scalars(
            select(Annotation).where(Annotation.project_id == seeded["project_id"])
        ))
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None
        assert patient.event_annotation_id is None
        assert {row.status for row in annotations} == {"R", "U"}
        assert next(row for row in annotations if row.annotation_id == reviewed.annotation_id).review_reason == (
            "human_negative"
        )


async def test_unlock_closes_patient_whose_remaining_annotations_were_ruled_out(session_factory):
    from app.annotations.review_service import unlock_patient

    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=2)
        config = await session.get(PredictorConfig, seeded["config_id"])
        reviewed, hidden = seeded["annotations"]
        reviewed.status = "R"
        reviewed.review_reason = "human_negative"
        reviewed.reviewed_by = seeded["user_id"]
        session.add(reviewed)
        session.add(_prediction(seeded, hidden, config.id, 0))
        patient = await session.get(Patient, seeded["patient_id"])
        patient.locked_by = seeded["user_id"]
        patient.locked_at = datetime.now(UTC)
        session.add(patient)
        await session.commit()

        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        await session.commit()
        await session.refresh(patient)
        assert patient.status == PatientStatus.REVIEWING

        await unlock_patient(session, seeded["project_id"], seeded["patient_id"], seeded["user_id"])

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        annotations = list(await session.scalars(
            select(Annotation).where(Annotation.project_id == seeded["project_id"])
        ))
        assert patient.status == PatientStatus.REVIEWING
        assert patient.locked_by is None
        assert {row.status for row in annotations} == {"R", "U"}


@pytest.mark.parametrize(
    ("status", "age_hours", "busy"),
    [
        (PatientStatus.REVIEWING, 0, True),
        (PatientStatus.REVIEWED, 0, False),
        (PatientStatus.REVIEWING, 2, False),
    ],
)
async def test_reprocess_busy_ignores_finished_and_stale_locks(
    session_factory, status, age_hours, busy
):
    from datetime import timedelta

    from app.nlp.service import reprocess_is_busy

    async with session_factory() as session:
        seeded = await _seed_project(session, patient_status=status)
        patient = await session.get(Patient, seeded["patient_id"])
        patient.locked_by = seeded["user_id"]
        patient.locked_at = datetime.now(UTC) - timedelta(hours=age_hours)
        session.add(patient)
        job = await session.get(BackgroundJob, seeded["job_id"])
        job.status = JobStatus.COMPLETED
        session.add(job)
        await session.commit()

        assert await reprocess_is_busy(session, seeded["project_id"]) is busy


async def test_export_identifies_annotation_and_predictor_per_row(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        stale_run = ProductionRun(
            project_id=seeded["project_id"], created_by=seeded["user_id"],
            status="completed", config_snapshot={},
        )
        active_run = ProductionRun(
            project_id=seeded["project_id"], created_by=seeded["user_id"],
            status="completed", config_snapshot={},
        )
        session.add_all([stale_run, active_run])
        await session.flush()
        session.add(ProductionState(
            project_id=seeded["project_id"], active_run_id=active_run.id
        ))
        session.add(NotePrediction(
            project_id=seeded["project_id"],
            run_id=active_run.id,
            text_id=seeded["text_id"],
            patient_id=seeded["patient_external_id"],
            note_uuid=seeded["note_id"],
            patient_uuid=seeded["patient_id"],
            status="succeeded",
            label=1,
            score=0.8,
        ))
        await session.commit()

        rows = await export_annotations(session, seeded["project_id"])
        assert len(rows) == 1
        assert {row["annotation_id"] for row in rows} == {annotation.annotation_id}
        assert rows[0]["predictor_config_id"] is None
        assert rows[0]["predicted_label"] == 1
        assert rows[0]["predicted_score"] == 0.8


async def test_purge_data_source_removes_predictions(session_factory):
    from app.audit.models import AuditAction, AuditEntry
    from app.connectors.models import DataSource
    from app.connectors.service import purge_data_source

    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        source = DataSource(
            id=_id(), project_id=seeded["project_id"], name="src", connector_type="file_upload",
        )
        session.add(source)
        await session.flush()
        note = await session.get(Note, seeded["note_id"])
        note.data_source_id = source.id
        session.add(note)
        patient = await session.get(Patient, seeded["patient_id"])
        patient.data_source_id = source.id
        session.add(patient)
        session.add(_prediction(seeded, annotation, seeded["config_id"], 1))
        session.add(
            AuditEntry(
                project_id=seeded["project_id"], patient_id=seeded["patient_id"],
                user_id=seeded["user_id"], action=AuditAction.PATIENT_UNLOCKED,
            )
        )
        await session.commit()

        assert await purge_data_source(session, seeded["project_id"], source.id) == 1
        await session.commit()
        remaining = await session.execute(select(AnnotationPrediction))
        assert remaining.scalars().all() == []
        audit = (await session.execute(select(AuditEntry))).scalars().all()
        unlocks = [a for a in audit if a.action == AuditAction.PATIENT_UNLOCKED]
        assert len(unlocks) == 1 and unlocks[0].patient_id is None


async def test_bulk_prediction_skips_excluded_annotations(session_factory):
    from app.annotations.prediction_service import _unscored_annotations_stmt

    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=2)
        excluded = seeded["annotations"][0]
        excluded.status = "R"
        excluded.review_reason = "duplicate"
        session.add(excluded)
        await session.commit()

        rows = (
            await session.execute(
                _unscored_annotations_stmt(seeded["project_id"], seeded["config_id"])
            )
        ).scalars().all()
        assert [annotation.annotation_id for annotation in rows] == [
            seeded["annotations"][1].annotation_id
        ]


# ---------------------------------------------------------------------------
# Active-predictor-only verdicts (Phase 1: review queue filter)
# ---------------------------------------------------------------------------

async def test_reviewable_filter_ignores_inactive_predictors(session_factory):
    """Only the active production run's note prediction controls eligibility."""
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        stale_run = ProductionRun(
            project_id=seeded["project_id"], created_by=seeded["user_id"],
            status="completed", config_snapshot={},
        )
        active_run = ProductionRun(
            project_id=seeded["project_id"], created_by=seeded["user_id"],
            status="completed", config_snapshot={},
        )
        session.add_all([stale_run, active_run])
        await session.flush()
        session.add(ProductionState(
            project_id=seeded["project_id"], active_run_id=active_run.id
        ))
        prediction = NotePrediction(
            project_id=seeded["project_id"],
            run_id=stale_run.id,
            text_id=seeded["text_id"],
            patient_id=seeded["patient_external_id"],
            note_uuid=seeded["note_id"],
            patient_uuid=seeded["patient_id"],
            status="succeeded",
            label=0,
            score=0.8,
        )
        session.add(prediction)
        await session.commit()

        cond = reviewable_filter(active_predictor_id=seeded["config_id"])
        rows = (
            await session.execute(
                select(Annotation).where(
                    Annotation.annotation_id == annotation.annotation_id, cond
                )
            )
        ).scalars().all()
        assert len(rows) == 1

        prediction.run_id = active_run.id
        session.add(prediction)
        await session.commit()
        rows = (
            await session.execute(
                select(Annotation).where(
                    Annotation.annotation_id == annotation.annotation_id, cond
                )
            )
        ).scalars().all()
        assert len(rows) == 0

        prediction.label = 1
        session.add(prediction)
        await session.commit()
        rows = (
            await session.execute(
                select(Annotation).where(
                    Annotation.annotation_id == annotation.annotation_id, cond
                )
            )
        ).scalars().all()
        assert len(rows) == 1


def test_reviewable_filter_correlates_active_run_lookup_for_postgresql():
    statement = select(Annotation).where(reviewable_filter())
    sql = " ".join(str(statement.compile(dialect=postgresql.dialect())).split())

    assert (
        'FROM production_states WHERE production_states.project_id = "Annotations".project_id'
        in sql
    )
    assert 'FROM production_states, "Annotations"' not in sql


async def test_reviewable_filter_no_active_predictor_keeps_legacy_behavior(session_factory):
    """With no active production run, a keyword-only annotation stays reviewable."""
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        cond = reviewable_filter(active_predictor_id=None)
        rows = (
            await session.execute(
                select(Annotation).where(
                    Annotation.annotation_id == annotation.annotation_id, cond
                )
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_reviewable_filter_no_active_keeps_any_prediction_ruling_out(session_factory):
    """Legacy annotation predictions do not rule out without an active production run."""
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        session.add(_prediction(seeded, annotation, seeded["config_id"], 0))
        await session.commit()

        cond = reviewable_filter(active_predictor_id=None)
        rows = (
            await session.execute(
                select(Annotation).where(
                    Annotation.annotation_id == annotation.annotation_id, cond
                )
            )
        ).scalars().all()
        assert len(rows) == 1


async def test_reviewable_filter_manual_override_wins_regardless(session_factory):
    """A human-negative reason is not treated as a production-model exclusion."""
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        annotation.status = "R"
        annotation.review_reason = "human_negative"
        annotation.reviewed_by = seeded["user_id"]
        run = ProductionRun(
            project_id=seeded["project_id"], created_by=seeded["user_id"],
            status="completed", config_snapshot={},
        )
        session.add(run)
        await session.flush()
        session.add(ProductionState(project_id=seeded["project_id"], active_run_id=run.id))
        session.add(NotePrediction(
            project_id=seeded["project_id"],
            run_id=run.id,
            text_id=seeded["text_id"],
            patient_id=seeded["patient_external_id"],
            note_uuid=seeded["note_id"],
            patient_uuid=seeded["patient_id"],
            status="succeeded",
            label=1,
            score=0.8,
        ))
        session.add(annotation)
        await session.commit()

        cond = reviewable_filter(active_predictor_id=seeded["config_id"])
        rows = (
            await session.execute(
                select(Annotation).where(
                    Annotation.annotation_id == annotation.annotation_id, cond
                )
            )
        ).scalars().all()
        assert len(rows) == 1
