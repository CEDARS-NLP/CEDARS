"""Tests for the keyword-only workflow: spaCy matching straight to annotation."""

from datetime import UTC, datetime

from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
from app.annotations.query_service import get_annotation_stats
from app.annotations.review_service import get_next_patient_for_review
from app.common.database import get_session
from app.connectors.models import Note, Patient, PatientStatus
from app.nlp.engine import parse_query, process_note
from app.nlp.models import SearchQuery
from app.nlp.service import _process_notes_into_sentences
from tests.conftest import seed_project_and_user


async def _session(app):
    async for session in app.dependency_overrides[get_session]():
        return session
    raise AssertionError("no session")


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
                text_id=f"note-{patient_ext}",
                text=text,
                note_date=datetime(2024, 1, 15, tzinfo=UTC),
            )
        )
        ids[patient_ext] = patient.id
    await session.commit()
    return ids


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
        session.add(SearchQuery(project_id=pid, query="troponin"))
        await session.commit()

        stats = await _process_notes_into_sentences(session, pid)
        assert stats["annotations_created"] == 2
        assert stats["patients_with_matches"] == 1

        annotations = (await session.execute(Annotation.__table__.select())).all()
        assert len(annotations) == 2

    async def test_records_v1_fields(self, app):
        pid, _ = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "No findings. Troponin elevated.")])

        session = await _session(app)
        session.add(SearchQuery(project_id=pid, query="troponin"))
        await session.commit()
        await _process_notes_into_sentences(session, pid)

        ann = (await session.execute(Annotation.__table__.select())).one()
        assert ann.token == "Troponin"
        assert ann.note_start_index == 13
        assert ann.note_end_index == 21
        assert ann.sentence_number == 1
        assert ann.sentence_start == 13
        assert ann.text_date is not None
        assert ann.review_status == ReviewStatus.UNREVIEWED.value
        assert ann.predicted_label is None

    async def test_patient_without_matches_is_auto_reviewed(self, app):
        pid, _ = await seed_project_and_user(app)
        ids = await _seed_notes(
            app, pid, [("P1", "Troponin elevated."), ("P2", "Patient has a headache.")]
        )

        session = await _session(app)
        session.add(SearchQuery(project_id=pid, query="troponin"))
        await session.commit()
        stats = await _process_notes_into_sentences(session, pid)

        assert stats["patients_auto_completed"] == 1
        matched = await session.get(Patient, ids["P1"])
        unmatched = await session.get(Patient, ids["P2"])
        await session.refresh(matched)
        await session.refresh(unmatched)
        assert matched.status == PatientStatus.NLP_COMPLETE
        assert unmatched.status == PatientStatus.REVIEWED


class TestReviewWithoutPredictor:
    async def test_next_patient_returned_without_any_prediction(self, app):
        pid, uid = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "Troponin elevated.")])

        session = await _session(app)
        session.add(SearchQuery(project_id=pid, query="troponin"))
        await session.commit()
        await _process_notes_into_sentences(session, pid)

        result = await get_next_patient_for_review(session, pid, uid)
        assert result.patient_id is not None
        assert result.unreviewed_annotations == 1

    async def test_negative_prediction_removes_annotation_from_queue(self, app):
        pid, uid = await seed_project_and_user(app)
        await _seed_notes(app, pid, [("P1", "Troponin elevated.")])

        session = await _session(app)
        session.add(SearchQuery(project_id=pid, query="troponin"))
        await session.commit()
        await _process_notes_into_sentences(session, pid)

        annotation = (await session.execute(Annotation.__table__.select())).one()
        session.add(
            AnnotationPrediction(
                annotation_id=annotation.id,
                project_id=pid,
                predicted_label=0,
                predicted_score=0.1,
            )
        )
        await session.commit()

        result = await get_next_patient_for_review(session, pid, uid)
        assert result.patient_id is None
        assert result.all_complete is True

        stats = await get_annotation_stats(session, pid)
        assert stats.total == 0
