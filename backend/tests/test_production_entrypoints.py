from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.annotations.models import Annotation, AnnotationPrediction
from app.annotations.prediction_service import run_bulk_predictions
from app.auth.models import User
from app.connectors.models import ConnectorType, DataSource, Note, Patient
from app.connectors.service import _ingest_rows, _refresh_project_results
from app.nlp.models import SearchQuery
from app.nlp.service import (
    _process_notes_into_sentences,
    clear_sentences,
    dispatch_nlp_job,
    run_nlp_pipeline,
)
from app.predictors.models import PredictorConfig, PredictorType
from app.production.classifier import NoteClassification
from app.production.models import NotePrediction, ProductionResult, ProductionRun
from app.projects.models import Project
from app.projects.stats import get_project_stats


async def _seed_project(session):
    user = User(email="entrypoints@test.example", name="Entrypoints", password_hash="unused")
    session.add(user)
    await session.flush()
    project = Project(name="Entrypoint test", owner_id=user.id)
    session.add(project)
    await session.flush()
    patient = Patient(project_id=project.id, patient_id_ext="patient-ext")
    session.add(patient)
    await session.flush()
    note = Note(
        project_id=project.id,
        patient_id=patient.id,
        patient_id_ext=patient.patient_id_ext,
        text_id="note-ext",
        note_date=datetime(2025, 4, 3, tzinfo=UTC),
        text="History of pulmonary embolism.",
    )
    session.add(note)
    session.add(
        SearchQuery(
            project_id=project.id,
            query="pulmonary embolism",
            is_active=True,
            hide_duplicates=True,
            exclude_negated=True,
        )
    )
    await session.commit()
    return user, project, patient, note


@pytest.mark.asyncio
async def test_nlp_reprocess_uses_confirmed_production_reset(session_factory):
    async with session_factory() as session:
        user, project, patient, note = await _seed_project(session)
        old = Annotation(
            project_id=project.id,
            text_id=note.text_id,
            patient_id=patient.patient_id_ext,
            patient_uuid=patient.id,
            note_uuid=note.id,
            text_date=date(2025, 4, 3),
            sentence="Old event.",
            token="event",
            isNegated=False,
            note_start_index=4,
            note_end_index=9,
            sentence_number=0,
            sentence_start=0,
            sentence_end=11,
            status="R",
        )
        session.add(old)
        await session.flush()
        session.add(
            ProductionResult(
                project_id=project.id,
                patient_uuid=patient.id,
                patient_id=patient.patient_id_ext,
                processing_status="completed",
            )
        )
        await session.commit()

        await clear_sentences(session, project.id, commit=True)
        job = await run_nlp_pipeline(session, project.id)

        assert job.status.value == "completed"
        assert await session.scalar(
            select(Annotation).where(Annotation.project_id == project.id)
        ) is not None
        assert await session.scalar(
            select(ProductionRun).where(
                ProductionRun.project_id == project.id,
                ProductionRun.status == "completed",
            )
        ) is not None


@pytest.mark.asyncio
async def test_nlp_dispatch_does_not_bypass_required_reset_confirmation(session_factory):
    from app.production.service import ProductionConfirmationRequired

    async with session_factory() as session:
        user, project, patient, _ = await _seed_project(session)
        session.add(
            ProductionResult(
                project_id=project.id,
                patient_uuid=patient.id,
                patient_id=patient.patient_id_ext,
            )
        )
        await session.commit()

        with pytest.raises(ProductionConfirmationRequired):
            await dispatch_nlp_job(session, project.id, user.id)


@pytest.mark.asyncio
async def test_cache_only_nlp_does_not_write_production_annotations(session_factory):
    async with session_factory() as session:
        _, project, _, _ = await _seed_project(session)

        result = await _process_notes_into_sentences(
            session, project.id, create_annotations=False
        )

        assert result["processed_notes"] == 1
        assert await session.scalar(select(Annotation)) is None
        assert await session.scalar(select(NotePrediction)) is None
        assert await session.scalar(select(ProductionResult)) is None


@pytest.mark.asyncio
async def test_bulk_prediction_classifies_complete_notes_through_production(
    session_factory, monkeypatch
):
    received = []

    async def classify(note_text, config, api_key=None):
        received.append((note_text, config["text_id"]))
        return NoteClassification(
            label=1,
            score=0.97,
            reasoning="The complete note documents the event.",
            evidence_spans=[],
        )

    monkeypatch.setattr("app.production.service.classify_note", classify)
    async with session_factory() as session:
        user, project, _, note = await _seed_project(session)
        session.add(
            PredictorConfig(
                project_id=project.id,
                predictor_type=PredictorType.LLM,
                name="test LLM",
                config={
                    "provider": "openai",
                    "model": "test-model",
                    "event_definition": {"name": "Pulmonary embolism"},
                },
                is_active=True,
                created_by=user.id,
            )
        )
        await session.commit()

        result = await run_bulk_predictions(session, project.id)

        prediction = await session.scalar(
            select(NotePrediction).where(NotePrediction.project_id == project.id)
        )
        assert received == [(note.text, note.text_id)]
        assert prediction is not None and prediction.label == 1
        assert result["predictions_made"] == 1
        assert set(result) == {
            "total_sentences", "predictions_made", "annotations_created", "errors", "token_usage"
        }
        assert await session.scalar(select(AnnotationPrediction)) is None


@pytest.mark.asyncio
async def test_ingestion_refreshes_external_note_identity_and_all_patient_results(session_factory):
    async with session_factory() as session:
        _, project, _, _ = await _seed_project(session)
        data_source = DataSource(
            project_id=project.id,
            name="Upload",
            connector_type=ConnectorType.FILE_UPLOAD,
            config={},
        )
        session.add(data_source)
        await session.commit()

        inserted = await _ingest_rows(
            session,
            project.id,
            data_source.id,
            [
                {
                    "patient_id": "new-patient",
                    "text_id": "new-note",
                    "text": "Pulmonary embolism.",
                    "note_date": "2025-05-04T00:00:00+00:00",
                }
            ],
            {
                "patient_id": "patient_id",
                "text_id": "text_id",
                "text": "text",
                "note_date": "note_date",
            },
        )
        await _refresh_project_results(session, project.id)
        await session.commit()

        ingested_note = await session.scalar(
            select(Note).where(Note.project_id == project.id, Note.text_id == "new-note")
        )
        patients = list(
            await session.scalars(select(Patient).where(Patient.project_id == project.id))
        )
        results = list(
            await session.scalars(
                select(ProductionResult).where(ProductionResult.project_id == project.id)
            )
        )
        assert inserted == 1
        assert ingested_note is not None and ingested_note.patient_id_ext == "new-patient"
        assert {result.patient_uuid for result in results} == {patient.id for patient in patients}
        assert next(result for result in results if result.patient_id == "new-patient").notes_total == 1


@pytest.mark.asyncio
async def test_project_stats_count_patient_owned_events(session_factory):
    async with session_factory() as session:
        user, project, patient, note = await _seed_project(session)
        annotation = Annotation(
            project_id=project.id,
            text_id=note.text_id,
            patient_id=patient.patient_id_ext,
            patient_uuid=patient.id,
            note_uuid=note.id,
            text_date=date(2025, 4, 3),
            sentence="Pulmonary embolism.",
            token="embolism",
            isNegated=False,
            note_start_index=10,
            note_end_index=19,
            sentence_number=0,
            sentence_start=0,
            sentence_end=20,
            status="R",
            reviewed_by=user.id,
        )
        session.add(annotation)
        await session.flush()
        patient.event_date = date(2025, 4, 3)
        patient.event_annotation_id = annotation.annotation_id
        patient.event_reviewer = user.id
        await session.commit()

        stats = await get_project_stats(session, project.id)

        assert stats["annotations"]["events_found"] == 1
        assert stats["annotations"]["reviewed"] == 1
        assert stats["annotators"][0]["events_found"] == 1
