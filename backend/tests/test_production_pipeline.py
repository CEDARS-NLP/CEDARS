from datetime import UTC, date, datetime

import pytest
from sqlalchemy import select

from app.annotations.models import Annotation
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.production.classifier import NoteClassification, classify_note
from app.production.models import NotePrediction, ProductionResult
from app.production.service import (
    ProductionConfirmationRequired,
    ProductionError,
    execute_run,
    start_run,
)
from app.projects.models import Project


async def _seed(session):
    user = User(email="production@test.example", name="Production", password_hash="unused")
    session.add(user)
    await session.flush()
    project = Project(name="Production test", owner_id=user.id)
    session.add(project)
    await session.flush()
    patient = Patient(project_id=project.id, patient_id_ext="patient-ext")
    session.add(patient)
    await session.flush()
    note = Note(
        project_id=project.id,
        patient_id=patient.id,
        patient_id_ext="patient-ext",
        text_id="note-ext",
        note_date=datetime(2025, 4, 3, tzinfo=UTC),
        text="History of pulmonary embolism. No fever.",
    )
    session.add(note)
    await session.commit()
    return user, project, patient, note


@pytest.mark.asyncio
async def test_keyword_only_run_creates_actual_match_and_completes_patient(session_factory):
    async with session_factory() as session:
        user, project, patient, note = await _seed(session)
        run = await start_run(
            session,
            project.id,
            user.id,
            {"query": "pulmonary embolism", "exclude_negated": True},
        )
        await execute_run(session, run.id)

        annotation = await session.scalar(
            select(Annotation).where(Annotation.production_run_id == run.id)
        )
        await session.refresh(patient)
        assert annotation is not None
        assert annotation.text_id == note.text_id
        assert annotation.patient_id == patient.patient_id_ext
        assert annotation.token == "pulmonary embolism"
        assert annotation.note_start_index == note.text.index("pulmonary embolism")
        assert annotation.status == "U"
        assert patient.status == PatientStatus.NLP_COMPLETE
        assert await session.scalar(select(NotePrediction).where(NotePrediction.run_id == run.id)) is None


@pytest.mark.asyncio
async def test_no_match_run_completes_patient_and_refreshes_results(session_factory):
    async with session_factory() as session:
        user, project, patient, _ = await _seed(session)
        run = await start_run(session, project.id, user.id, {"query": "not present"})
        await execute_run(session, run.id)

        await session.refresh(patient)
        result = await session.scalar(
            select(ProductionResult).where(ProductionResult.patient_uuid == patient.id)
        )
        assert patient.status == PatientStatus.REVIEWED
        assert result is not None
        assert result.processing_status == "completed"
        assert result.notes_processed == 1


@pytest.mark.asyncio
async def test_run_cannot_be_claimed_twice(session_factory):
    async with session_factory() as session:
        user, project, _, _ = await _seed(session)
        run = await start_run(session, project.id, user.id, {"query": "embolism"})
        await execute_run(session, run.id)

        with pytest.raises(ProductionError, match="already claimed"):
            await execute_run(session, run.id)


@pytest.mark.asyncio
async def test_duplicate_occurrences_keep_spans_and_link_to_first_match(session_factory, monkeypatch):
    from app.production.service import _match_key

    def process_repeated_sentence(*_args):
        return [
            {
                "text": "event event",
                "start_pos": 0,
                "end_pos": 11,
                "sentence_number": 0,
                "is_target": True,
                "is_negated": False,
                "matches": [
                    {"token": "event", "note_start_index": 0, "note_end_index": 5},
                    {"token": "event", "note_start_index": 6, "note_end_index": 11},
                ],
            }
        ]

    monkeypatch.setattr("app.production.service.process_note", process_repeated_sentence)
    async with session_factory() as session:
        user, project, patient, note = await _seed(session)
        note.text = "event event"
        await session.commit()
        run = await start_run(session, project.id, user.id, {"query": "event"})
        await execute_run(session, run.id)

        annotations = list(
            await session.scalars(
                select(Annotation)
                .where(Annotation.production_run_id == run.id)
                .order_by(Annotation.annotation_id)
            )
        )
        assert _match_key(" Event  Here \n") == "event  here"
        assert len(annotations) == 2
        assert annotations[0].status == "U"
        assert annotations[1].status == "R"
        assert annotations[1].review_reason == "duplicate"
        assert annotations[1].duplicate_of == annotations[0].annotation_id
        assert [item.note_start_index for item in annotations] == [0, 6]


@pytest.mark.asyncio
async def test_existing_production_data_requires_confirmation_and_is_reset(session_factory):
    async with session_factory() as session:
        user, project, patient, note = await _seed(session)
        old_annotation = Annotation(
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
            review_reason="human_event",
        )
        session.add(old_annotation)
        await session.flush()
        patient.event_date = date(2025, 4, 3)
        patient.event_annotation_id = old_annotation.annotation_id
        patient.event_reviewer = user.id
        session.add(
            ProductionResult(
                project_id=project.id,
                patient_uuid=patient.id,
                patient_id=patient.patient_id_ext,
                processing_status="completed",
            )
        )
        await session.commit()

        with pytest.raises(ProductionConfirmationRequired):
            await start_run(session, project.id, user.id, {"query": "embolism"})

        replacement = await start_run(
            session,
            project.id,
            user.id,
            {"query": "embolism"},
            confirmed=True,
        )
        await session.refresh(patient)
        assert patient.event_date is None
        assert patient.event_annotation_id is None
        assert patient.event_reviewer is None
        assert await session.scalar(
            select(Annotation).where(Annotation.project_id == project.id)
        ) is None
        assert await session.scalar(
            select(ProductionResult).where(ProductionResult.project_id == project.id)
        ) is not None
        assert replacement.status == "queued"


@pytest.mark.asyncio
async def test_llm_run_classifies_each_matching_note_and_marks_negative_matches_reviewed(
    session_factory, monkeypatch
):
    calls = []

    async def classify(full_note, config, *, api_key=None):
        calls.append((full_note, config["text_id"], api_key))
        return NoteClassification(
            label=0,
            score=0.91,
            reasoning="No confirmed event in this note.",
            evidence_spans=[],
            token_usage={"prompt_tokens": 12, "completion_tokens": 6},
        )

    monkeypatch.setattr("app.production.service.classify_note", classify)
    async with session_factory() as session:
        user, project, patient, first_note = await _seed(session)
        project.llm_api_key = "runtime-secret"
        second_note = Note(
            project_id=project.id,
            patient_id=patient.id,
            patient_id_ext=patient.patient_id_ext,
            text_id="note-second",
            note_date=datetime(2025, 5, 3, tzinfo=UTC),
            text="Possible pulmonary embolism, later ruled out.",
        )
        session.add(second_note)
        await session.commit()
        run = await start_run(
            session,
            project.id,
            user.id,
            {
                "query": "pulmonary embolism",
                "llm_config": {"provider": "openai", "model": "test-model"},
                "event_definition": {"name": "Pulmonary embolism"},
            },
        )
        await execute_run(session, run.id)

        predictions = list(
            await session.scalars(select(NotePrediction).where(NotePrediction.run_id == run.id))
        )
        annotations = list(
            await session.scalars(
                select(Annotation).where(Annotation.production_run_id == run.id)
            )
        )
        await session.refresh(patient)
        assert {prediction.text_id for prediction in predictions} == {
            first_note.text_id,
            second_note.text_id,
        }
        assert all(prediction.status == "succeeded" and prediction.label == 0 for prediction in predictions)
        assert len(calls) == 2
        assert {text_id for _, text_id, _ in calls} == {first_note.text_id, second_note.text_id}
        assert all(note_text in {first_note.text, second_note.text} for note_text, _, _ in calls)
        assert {api_key for _, _, api_key in calls} == {"runtime-secret"}
        assert "runtime-secret" not in str((await session.get(type(run), run.id)).config_snapshot)
        assert all(len(prediction.model_fingerprint) == 64 for prediction in predictions)
        from app.llm.usage import LlmUsage

        usage_rows = list(
            await session.scalars(
                select(LlmUsage).where(
                    LlmUsage.project_id == project.id,
                    LlmUsage.ref_id == run.id,
                    LlmUsage.source == "production_run",
                )
            )
        )
        assert len(usage_rows) == 2
        assert all(row.prompt_tokens == 12 and row.completion_tokens == 6 for row in usage_rows)
        assert annotations and all(
            annotation.status == "R" and annotation.review_reason == "llm_negative"
            for annotation in annotations
        )
        assert patient.status == PatientStatus.REVIEWED


@pytest.mark.asyncio
@pytest.mark.parametrize("fail_first", [False, True])
async def test_multi_note_run_releases_transaction_and_persists_results(
    session_factory, monkeypatch, fail_first
):
    calls = []

    async with session_factory() as session:
        user, project, patient, first_note = await _seed(session)
        second_note = Note(
            project_id=project.id,
            patient_id=patient.id,
            patient_id_ext=patient.patient_id_ext,
            text_id="second-external-note",
            note_date=datetime(2025, 5, 3, tzinfo=UTC),
            text="Possible pulmonary embolism, later ruled out.",
        )
        session.add(second_note)
        await session.commit()
        project_id = project.id
        patient_uuid = patient.id
        source_notes = {
            note.text_id: (note.id, note.text, note.patient_id, note.patient_id_ext)
            for note in (first_note, second_note)
        }

        async def classify(full_note, config, *, api_key=None):
            assert not session.in_transaction()
            calls.append(config["text_id"])
            if fail_first and len(calls) == 1:
                raise RuntimeError("Temporary classifier failure")
            return NoteClassification(
                label=0,
                score=0.91,
                reasoning="No confirmed event.",
                evidence_spans=[],
                token_usage={"prompt_tokens": 12, "completion_tokens": 6},
            )

        monkeypatch.setattr("app.production.service.classify_note", classify)
        run = await start_run(
            session,
            project_id,
            user.id,
            {
                "query": "pulmonary embolism",
                "llm_config": {"provider": "openai", "model": "test-model"},
            },
        )
        run_id = run.id
        completed = await execute_run(session, run_id)
        assert completed.status == ("failed" if fail_first else "completed")
        assert completed.completed_notes == (1 if fail_first else 2)
        assert completed.failed_notes == int(fail_first)
        assert project.id == project_id
        assert patient.id == patient_uuid
        assert set(calls) == set(source_notes)
        assert len(calls) == 2
        assert first_note.text_id in source_notes
        assert second_note.text_id in source_notes

    async with session_factory() as session:
        notes = list(await session.scalars(select(Note).where(Note.project_id == project_id)))
        assert {
            note.text_id: (note.id, note.text, note.patient_id, note.patient_id_ext)
            for note in notes
        } == source_notes
        predictions = list(
            await session.scalars(select(NotePrediction).where(NotePrediction.run_id == run_id))
        )
        assert len(predictions) == 2
        for prediction in predictions:
            assert prediction.patient_uuid == patient_uuid
            assert prediction.patient_id == "patient-ext"
            assert prediction.note_uuid == source_notes[prediction.text_id][0]
            assert prediction.attempts == 1
        result = await session.scalar(
            select(ProductionResult).where(ProductionResult.patient_uuid == patient_uuid)
        )
        assert result is not None
        assert result.patient_id == "patient-ext"
        assert result.processing_status == ("failed" if fail_first else "completed")
        assert result.notes_total == result.total_notes == 2
        assert result.notes_processed == (1 if fail_first else 2)
        assert result.notes_failed == result.failure_count == int(fail_first)
        assert result.annotations_total == result.total_sentences == 2
        assert result.annotations_pending == int(fail_first)
        assert result.annotations_reviewed == (1 if fail_first else 2)
        assert result.reason_counts == {"llm_negative": 1 if fail_first else 2}
        assert result.max_score == 0.91
        assert result.max_score_note_id in source_notes
        assert result.event_date is None
        assert result.event_annotation_id is None
        assert result.last_error == ("Temporary classifier failure" if fail_first else None)


@pytest.mark.asyncio
async def test_classifier_requires_valid_exact_evidence_span(monkeypatch):
    async def fake_complete_json(**kwargs):
        assert kwargs["api_key"] == "runtime-secret"
        return {
            "label": "positive",
            "score": 0.93,
            "reasoning": "The note documents the event.",
            "evidence_spans": [{"start": 11, "end": 29, "text": "pulmonary embolism"}],
            "event_date": "2025-01-01",
        }, {"completion_tokens": 20}

    monkeypatch.setattr("app.production.classifier.complete_json", fake_complete_json)
    result = await classify_note(
        "History of pulmonary embolism.",
        {
            "query": "embolism",
            "llm_config": {"provider": "openai", "model": "test-model"},
            "event_definition": {"name": "Pulmonary embolism"},
        },
        api_key="runtime-secret",
    )
    assert result.label == 1
    assert result.score == 0.93
    assert result.evidence_spans == [{"start": 11, "end": 29, "text": "pulmonary embolism"}]
    assert not hasattr(result, "event_date")

    async def invalid_complete_json(**kwargs):
        return {
            "label": "positive",
            "score": 0.9,
            "reasoning": "Mismatch.",
            "evidence_spans": [{"start": 0, "end": 4, "text": "wrong"}],
        }, None

    monkeypatch.setattr("app.production.classifier.complete_json", invalid_complete_json)
    with pytest.raises(ValueError, match="Evidence span"):
        await classify_note(
            "A note.",
            {"provider": "openai", "model": "test-model"},
        )
