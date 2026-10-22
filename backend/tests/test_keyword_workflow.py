"""Tests for the keyword-only workflow: spaCy matching straight to annotation."""

from datetime import UTC, datetime

from sqlalchemy import select

from app.annotations.models import Annotation
from app.annotations.query_service import get_annotation_stats
from app.annotations.review_service import get_next_patient_for_review
from app.auth.models import User
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.engine import parse_query, process_note
from app.production.models import NotePrediction, ProductionState
from app.production.service import execute_run, start_run
from tests.conftest import seed_project_and_user


async def _session(app):
    return app.state.test_session_factory()


async def _seed_notes(app, project_id: str, notes: list[tuple[str, str]]) -> dict[str, str]:
    """Insert one patient per (patient_ext, text) pair. Returns ext -> patient id."""
    session = await _session(app)
    ids = {}
    for patient_ext, text in notes:
        patient = Patient(project_id=project_id, patient_id_ext=patient_ext)
        session.add(patient)
        await session.flush()
        session.add(
            Note(
                project_id=project_id,
                patient_id=patient.id,
                patient_id_ext=patient_ext,
                text_id=f"note-{patient_ext}",
                text=text,
                note_date=datetime(2024, 1, 15, tzinfo=UTC),
            )
        )
        ids[patient_ext] = patient.id
    await session.commit()
    return ids


async def _run_keyword_pipeline(session, project_id: str, query: str) -> None:
    user = await session.get(User, "user-1")
    run = await start_run(session, project_id, user.id, {"query": query})
    await execute_run(session, run.id)


class TestMatchSpans:
    def test_emits_one_match_per_token(self):
        text = "Troponin elevated. Repeat troponin also elevated."
        sentences = process_note(text, parse_query("troponin"))
        targets = [s for s in sentences if s["is_target"]]
        assert len(targets) == 2
        assert [m["token"] for m in targets[0]["matches"]] == ["Troponin"]

    def test_offsets_are_note_relative(self):
        text = "No findings. Troponin elevated."
        sentences = process_note(text, parse_query("troponin"))
        match = next(s for s in sentences if s["is_target"])["matches"][0]
        assert text[match["note_start_index"]:match["note_end_index"]] == "Troponin"

    def test_non_target_sentence_has_no_matches(self):
        sentences = process_note("Patient has a headache.", parse_query("troponin"))
        assert sentences[0]["matches"] == []


class TestNlpProducesAnnotations:
    async def test_creates_annotation_per_match(self, app):
        pid, _ = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "Troponin elevated. Repeat troponin high.")])

        session = await _session(app)
        await _run_keyword_pipeline(session, pid, "troponin")

        annotations = list(await session.scalars(select(Annotation)))
        assert len(annotations) == 2
        assert {ann.token.lower() for ann in annotations} == {"troponin"}
        assert all(ann.status == "U" for ann in annotations)

    async def test_records_v1_fields(self, app):
        pid, _ = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "No findings. Troponin elevated.")])

        session = await _session(app)
        await _run_keyword_pipeline(session, pid, "troponin")

        ann = await session.scalar(select(Annotation))
        assert ann.token == "Troponin"
        assert ann.note_start_index == 13
        assert ann.note_end_index == 21
        assert ann.sentence_number == 1
        assert ann.sentence_start == 13
        assert ann.text_date is not None
        assert ann.status == "U"
        assert ann.patient_id == "P1"
        assert ann.text_id == "note-P1"
        assert await session.scalar(select(NotePrediction)) is None

    async def test_patient_without_matches_is_auto_reviewed(self, app):
        pid, _ = await seed_project_and_user(app)
        ids = await _seed_notes(
            app, pid, [("P1", "Troponin elevated."), ("P2", "Patient has a headache.")]
        )

        session = await _session(app)
        await _run_keyword_pipeline(session, pid, "troponin")

        matched = await session.get(Patient, ids["P1"])
        unmatched = await session.get(Patient, ids["P2"])
        await session.refresh(matched)
        await session.refresh(unmatched)
        assert matched.status == PatientStatus.NLP_COMPLETE
        assert unmatched.status == PatientStatus.REVIEWED
        assert unmatched.review_reason == "production_complete"


class TestReviewWithoutPredictor:
    async def test_next_patient_returned_without_any_prediction(self, app):
        pid, uid = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "Troponin elevated.")])

        session = await _session(app)
        await _run_keyword_pipeline(session, pid, "troponin")

        result = await get_next_patient_for_review(session, pid, uid)
        assert result.patient_id is not None
        assert result.unreviewed_annotations == 1

    async def test_negative_prediction_removes_annotation_from_queue(self, app):
        pid, uid = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "Troponin elevated.")])

        session = await _session(app)
        from app.production.classifier import NoteClassification

        run = await start_run(
            session,
            pid,
            uid,
            {
                "query": "troponin",
                "llm_config": {"provider": "openai", "model": "test-model"},
            },
        )
        async def classify_note(_full_note, _config, *, api_key=None):
            return NoteClassification(
                label=0,
                score=0.1,
                reasoning="No event is documented.",
                evidence_spans=[],
            )

        from unittest.mock import patch

        with patch("app.production.service.classify_note", side_effect=classify_note):
            await execute_run(session, run.id)

        result = await get_next_patient_for_review(session, pid, uid)
        assert result.patient_id is None
        assert result.all_complete is True

        prediction = await session.scalar(select(NotePrediction))
        annotation = await session.scalar(select(Annotation))
        active_run_id = await session.scalar(
            select(ProductionState.active_run_id).where(ProductionState.project_id == pid)
        )
        assert prediction is not None
        assert prediction.status == "succeeded"
        assert prediction.label == 0
        assert prediction.run_id == active_run_id
        assert annotation is not None
        assert annotation.status == "R"
        assert annotation.review_reason == "llm_negative"

        stats = await get_annotation_stats(session, pid)
        assert stats.total == 0
