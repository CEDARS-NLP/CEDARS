"""Migration-backed regressions for review attribution and prediction completion."""

from dataclasses import asdict
from datetime import UTC, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy import select
from sqlmodel.ext.asyncio.session import AsyncSession

from app.annotations.completion_service import complete_negative_llm_patients
from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
from app.annotations.review_service import (
    ReopenConflictError,
    get_patient_annotations,
    reopen_patient,
    review_annotation,
)
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.export.service import export_annotations
from app.jobs.models import BackgroundJob, JobStatus, JobType
from app.nlp.models import SearchQuery, Sentence
from app.predictors.base import PredictionResult, PredictorError, TokenUsage
from app.predictors.models import PredictorConfig, PredictorType
from app.projects.models import Project, ProjectMember, ProjectRole


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
        text_id=f"text-{note_id}",
        note_date=datetime(2026, 1, 1, tzinfo=UTC),
        text=note_text,
    )
    session.add(note)
    await session.flush()

    sentence_ids = []
    annotations = []
    for index in range(annotation_count):
        sentence_id = _id()
        sentence_ids.append(sentence_id)
        session.add(
            Sentence(
                id=sentence_id,
                note_id=note_id,
                project_id=project_id,
                sentence_number=index,
                text=f"Sentence {index}.",
                start_pos=index * 10,
                end_pos=index * 10 + 10,
                is_target=True,
                matched_tokens=["target"],
            )
        )
    await session.flush()

    for index, sentence_id in enumerate(sentence_ids):
        annotation = Annotation(
            id=_id(),
            project_id=project_id,
            patient_id=patient_id,
            note_id=note_id,
            sentence_id=sentence_id,
            sentence_text=f"Sentence {index}.",
            matched_tokens="target",
            token="target",
            sentence_number=index,
            sentence_start=index * 10,
            sentence_end=index * 10 + 10,
            text_date=note.note_date,
            review_status=ReviewStatus.UNREVIEWED,
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
    session.add_all([config, job])
    await session.commit()
    return {
        "user_id": user_id,
        "project_id": project_id,
        "patient_id": patient_id,
        "note_id": note_id,
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
        seeded = await _seed_project(session)

    predictor = AsyncMock()
    predictor.predict = AsyncMock(
        return_value=PredictionResult(
            score=0.91,
            label=1,
            model="mock-model",
            reasoning="positive test result",
            token_usage=token_usage,
        )
    )
    module = (
        "app.annotations.prediction_service"
        if writer == "bulk"
        else "app.jobs.prediction"
    )
    with patch(f"{module}.create_predictor", return_value=predictor):
        if writer == "bulk":
            from app.annotations.prediction_service import run_bulk_predictions

            async with session_factory() as session:
                await run_bulk_predictions(session, seeded["project_id"])
        else:
            from app.jobs.prediction import execute_prediction_job

            await execute_prediction_job(
                seeded["project_id"], seeded["job_id"], session_factory
            )

    async with session_factory() as session:
        prediction = (
            await session.execute(
                select(AnnotationPrediction).where(
                    AnnotationPrediction.annotation_id == seeded["annotations"][0].id
                )
            )
        ).scalar_one()
        assert prediction.token_usage == (asdict(token_usage) if token_usage else None)
        assert prediction.predicted_label == 1

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
        if expected_source:
            assert patient.status == PatientStatus.REVIEWED
            assert patient.review_source == "llm"
            assert patient.review_reason == "all_keyword_predictions_negative"
            assert patient.reviewed_by is None
            assert patient.reviewed_at is not None
        else:
            assert patient.status == PatientStatus.REVIEWING
            assert patient.review_source is None


async def test_manual_override_prevents_llm_auto_completion(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(session)
        annotation = seeded["annotations"][0]
        annotation.manual_review_override = True
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
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None


async def test_prediction_error_does_not_auto_complete_patient(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(session)

    predictor = AsyncMock()
    predictor.predict = AsyncMock(side_effect=PredictorError("mock provider failure"))
    with patch("app.annotations.prediction_service.create_predictor", return_value=predictor):
        from app.annotations.prediction_service import run_bulk_predictions

        async with session_factory() as session:
            stats = await run_bulk_predictions(session, seeded["project_id"])
    assert stats["errors"] == 1

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None
        assert not (
            await session.execute(select(AnnotationPrediction))
        ).scalars().all()


async def test_automated_processing_preserves_human_provenance(session_factory):
    async with session_factory() as session:
        seeded = await _seed_project(
            session, patient_status=PatientStatus.REVIEWED, review_source="human"
        )
        annotation = seeded["annotations"][0]
        annotation.review_status = ReviewStatus.REVIEWED
        annotation.reviewed_by = seeded["user_id"]
        session.add(
            AnnotationPrediction(
                annotation_id=annotation.id, project_id=seeded["project_id"],
                predictor_config_id=seeded["config_id"], predicted_label=0,
            )
        )
        await session.commit()
        config = await session.get(PredictorConfig, seeded["config_id"])
        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        session.add(
            Note(
                project_id=seeded["project_id"], patient_id=seeded["patient_id"],
                text_id=_id(), note_date=datetime(2026, 1, 4, tzinfo=UTC),
                text="Patient is stable.",
            )
        )
        await session.commit()
        from app.nlp.service import _process_notes_into_sentences

        await _process_notes_into_sentences(session, seeded["project_id"])
        patient = await session.get(Patient, seeded["patient_id"])
        await session.refresh(patient)
        assert patient.status == PatientStatus.REVIEWED
        assert patient.review_source == "human"
        assert patient.reviewed_by == seeded["user_id"]


async def test_cedars_processing_creates_excluded_negated_annotation_and_keeps_no_match(
    session_factory,
):
    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=0, note_text="Patient is stable.")
        other_patient_id, other_note_id = _id(), _id()
        session.add(
            Patient(
                id=other_patient_id,
                project_id=seeded["project_id"],
                patient_id_ext=f"external-{other_patient_id}",
                status=PatientStatus.REVIEWING,
            )
        )
        await session.flush()
        session.add(
            Note(
                id=other_note_id,
                project_id=seeded["project_id"],
                patient_id=other_patient_id,
                text_id=f"text-{other_note_id}",
                note_date=datetime(2026, 1, 2, tzinfo=UTC),
                text="No evidence of DVT.",
            )
        )
        session.add(
            SearchQuery(
                project_id=seeded["project_id"],
                query="DVT",
                exclude_negated=True,
            )
        )
        await session.commit()

        from app.nlp.service import _process_notes_into_sentences

        stats = await _process_notes_into_sentences(session, seeded["project_id"])
        await session.commit()
        assert stats["total_notes"] == 2
        assert stats["annotations_created"] == 1

        annotations = (await session.execute(select(Annotation))).scalars().all()
        assert len(annotations) == 1
        assert annotations[0].is_negated is True
        assert annotations[0].review_excluded is True
        assert annotations[0].review_status == ReviewStatus.REVIEWED
        sentences = (await session.execute(select(Sentence))).scalars().all()
        assert len(sentences) == 2
        assert any(sentence.is_target is False for sentence in sentences)
        no_match_patient = await session.get(Patient, seeded["patient_id"])
        negated_patient = await session.get(Patient, other_patient_id)
        assert no_match_patient.review_source == "cedars"
        assert no_match_patient.review_reason == "no_keyword_matches"
        assert negated_patient.review_source == "cedars"
        assert negated_patient.review_reason == "negated_matches_only"
        assert no_match_patient.reviewed_by is None
        assert negated_patient.reviewed_by is None


async def test_reopening_patient_restores_excluded_rows_and_preserves_predictions(
    session_factory,
):
    async with session_factory() as session:
        seeded = await _seed_project(
            session,
            patient_status=PatientStatus.REVIEWED,
            review_source="llm",
        )
        annotation = seeded["annotations"][0]
        annotation.review_excluded = True
        annotation.review_status = ReviewStatus.REVIEWED
        prediction = AnnotationPrediction(
            annotation_id=annotation.id,
            project_id=seeded["project_id"],
            predictor_config_id=seeded["config_id"],
            predictor_model="saved-model",
            predicted_score=0.1,
            predicted_label=0,
            token_usage={"prompt_tokens": 7, "completion_tokens": 2, "total_tokens": 9},
        )
        session.add(prediction)
        await session.commit()

        assert await reopen_patient(
            session, seeded["project_id"], seeded["patient_id"], seeded["user_id"]
        )

    async with session_factory() as session:
        annotation = await session.get(Annotation, seeded["annotations"][0].id)
        patient = await session.get(Patient, seeded["patient_id"])
        prediction = (
            await session.execute(
                select(AnnotationPrediction).where(
                    AnnotationPrediction.annotation_id == annotation.id
                )
            )
        ).scalar_one()
        assert annotation.review_excluded is False
        assert annotation.manual_review_override is True
        assert annotation.review_status == ReviewStatus.UNREVIEWED
        assert annotation.predicted_label is None
        assert prediction.predicted_label == 0
        assert prediction.predictor_model == "saved-model"
        assert patient.status == PatientStatus.REVIEWING
        assert patient.review_source is None
        assert patient.review_reason is None
        visible = await get_patient_annotations(
            session, seeded["project_id"], seeded["patient_id"]
        )
        assert len(visible) == 1
        assert visible[0]["predicted_label"] == 0
        await review_annotation(
            session, seeded["project_id"], annotation.id, seeded["user_id"]
        )
        await session.refresh(patient)
        assert patient.status == PatientStatus.REVIEWED
        assert patient.review_source == "human"
        assert patient.reviewed_by == seeded["user_id"]


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
        annotation.review_excluded = True
        annotation.manual_review_override = True
        session.add(annotation)
        await session.commit()

        rows = await export_annotations(session, seeded["project_id"])
        assert len(rows) == 1
        assert rows[0]["review_excluded"] is True
        assert rows[0]["manual_review_override"] is True
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
        await session.flush()
        annotation = Annotation(
            project_id=project_id,
            patient_id=patient_id,
            note_id=note_id,
            sentence_id=sentence_id,
            sentence_text="No active NLP processing is needed.",
            token="NLP",
        )
        session.add(annotation)
        await session.flush()
        config = PredictorConfig(
            project_id=project_id,
            predictor_type=PredictorType.LLM,
            name="Reprocess test config",
            config={"provider": "ollama", "model": "test-model"},
            created_by=user.id,
        )
        session.add(config)
        await session.flush()
        session.add(
            AnnotationPrediction(
                annotation_id=annotation.id,
                project_id=project_id,
                predictor_config_id=config.id,
                predicted_label=1,
            )
        )
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
        reviewed.review_status = ReviewStatus.REVIEWED
        reviewed.reviewed_by = seeded["user_id"]
        session.add(reviewed)
        session.add(_prediction(seeded, hidden, config.id, 0))
        await complete_negative_llm_patients(
            session, seeded["project_id"], [seeded["patient_id"]], config
        )
        await session.commit()

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        assert patient.status == PatientStatus.REVIEWED
        assert patient.review_source == "human"
        assert patient.review_reason == "manual_review"
        assert patient.reviewed_by == seeded["user_id"]


async def test_unlock_closes_patient_whose_remaining_annotations_were_ruled_out(session_factory):
    from app.annotations.review_service import unlock_patient

    async with session_factory() as session:
        seeded = await _seed_project(session, annotation_count=2)
        config = await session.get(PredictorConfig, seeded["config_id"])
        reviewed, hidden = seeded["annotations"]
        reviewed.review_status = ReviewStatus.REVIEWED
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
        assert patient.status == PatientStatus.REVIEWING  # locked: skipped

        await unlock_patient(session, seeded["project_id"], seeded["patient_id"], seeded["user_id"])

    async with session_factory() as session:
        patient = await session.get(Patient, seeded["patient_id"])
        assert patient.status == PatientStatus.REVIEWED
        assert patient.locked_by is None


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
        other = PredictorConfig(
            id=_id(), project_id=seeded["project_id"], predictor_type=PredictorType.LLM,
            name="Second", config={}, is_active=False, created_by=seeded["user_id"],
        )
        session.add(other)
        await session.flush()
        session.add(_prediction(seeded, annotation, seeded["config_id"], 1))
        session.add(_prediction(seeded, annotation, other.id, 0))
        await session.commit()

        rows = await export_annotations(session, seeded["project_id"])
        assert len(rows) == 2
        assert {r["annotation_id"] for r in rows} == {annotation.id}
        assert {r["predictor_config_id"] for r in rows} == {seeded["config_id"], other.id}


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
        excluded.review_excluded = True
        session.add(excluded)
        await session.commit()

        rows = (
            await session.execute(
                _unscored_annotations_stmt(seeded["project_id"], seeded["config_id"])
            )
        ).scalars().all()
        assert [a.id for a in rows] == [seeded["annotations"][1].id]
