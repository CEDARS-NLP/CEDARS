"""Tests for get_patient_matched_notes, including the annotation fallback.

SearchMatch rows only exist for the sample/preview phase. Patients processed by
the full pipeline have no SearchMatch rows, so the endpoint must fall back to
reconstructing matched notes from the patient's annotations.
"""

from datetime import UTC, date, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.annotations.models import Annotation, ReviewStatus  # noqa: F401
from app.annotations.query_service import get_patient_matched_notes
from app.audit.models import AuditEntry  # noqa: F401

# Import ALL models so SQLModel.metadata.create_all creates every table.
from app.auth.models import User  # noqa: F401
from app.common.model_registry import create_all_metadata, drop_all_metadata
from app.connectors.models import DataSource, Note, Patient  # noqa: F401
from app.evaluation.models import (  # noqa: F401
    EvaluationSession,
    PatientResult,
    SearchMatch,
    SessionStatus,
)
from app.jobs.models import BackgroundJob  # noqa: F401
from app.nlp.models import NlpJob, SearchQuery, Sentence  # noqa: F401
from app.pipeline.models import EventConfig, Evidence, PatientTask, PipelineRun  # noqa: F401
from app.predictors.models import PredictorConfig  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(create_all_metadata)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(drop_all_metadata)
    await engine.dispose()


async def _seed_full_pipeline_patient(db: AsyncSession):
    """A patient processed by the full pipeline: has an Annotation, NO SearchMatch."""
    note_text = "Findings: marked splenomegaly. Impression: small splenic infarct noted."
    db.add(User(id="u1", email="a@b.com", name="A", password_hash="x"))
    db.add(Project(id="proj-1", name="P", owner_id="u1"))
    db.add(Patient(id="pat-1", project_id="proj-1", patient_id_ext="EXT-1"))
    db.add(Note(
        id="note-1",
        project_id="proj-1",
        patient_id="pat-1",
        patient_id_ext="EXT-1",
        text_id="TXT-1",
        note_date=datetime(2022, 4, 27, tzinfo=UTC),
        text=note_text,
    ))
    first_sentence = "Findings: marked splenomegaly."
    first_token = "splenomegaly"
    first_start = note_text.index(first_token)
    second_sentence = "Impression: small splenic infarct noted."
    second_token = "splenic"
    second_sentence_start = note_text.index(second_sentence)
    second_start = note_text.index(second_token, second_sentence_start)
    for sentence_number, sentence, sentence_start, token, token_start in (
        (0, first_sentence, 0, first_token, first_start),
        (1, second_sentence, second_sentence_start, second_token, second_start),
    ):
        db.add(Annotation(
            project_id="proj-1",
            text_id="TXT-1",
            patient_id="EXT-1",
            patient_uuid="pat-1",
            note_uuid="note-1",
            text_date=date(2022, 4, 27),
            sentence=sentence,
            token=token,
            isNegated=False,
            note_start_index=token_start,
            note_end_index=token_start + len(token),
            sentence_number=sentence_number,
            sentence_start=sentence_start,
            sentence_end=sentence_start + len(sentence),
            status="U",
        ))
    await db.commit()


class TestMatchedNotesAnnotationFallback:
    async def test_falls_back_to_annotations_without_pipeline_run(self, db):
        await _seed_full_pipeline_patient(db)

        notes = await get_patient_matched_notes(db, "proj-1", "pat-1", pipeline_run_id=None)

        assert len(notes) == 1
        n = notes[0]
        assert n["note_id"] == "note-1"
        assert n["text_id"] == "TXT-1"
        assert "splenomegaly" in n["text"]
        # Each row retains its exact matched token and source offset.
        assert set(n["search_keywords"]) == {"splenomegaly", "splenic"}
        assert len(n["matched_sentences"]) == 2
        assert {pos["text"] for pos in n["match_positions"]} == {"splenomegaly", "splenic"}
        assert len(n["match_positions"]) == 2
        for pos in n["match_positions"]:
            assert 0 <= pos["start"] < pos["end"] <= len(n["text"])
            assert n["text"][pos["start"]:pos["end"]] == pos["text"]

    async def test_returns_empty_when_no_annotations(self, db):
        db.add(User(id="u1", email="a@b.com", name="A", password_hash="x"))
        db.add(Project(id="proj-1", name="P", owner_id="u1"))
        db.add(Patient(id="pat-1", project_id="proj-1", patient_id_ext="EXT-1"))
        await db.commit()

        notes = await get_patient_matched_notes(db, "proj-1", "pat-1", pipeline_run_id=None)
        assert notes == []

    async def test_prefers_search_match_when_available(self, db):
        """When SearchMatch rows exist (sample phase), use them, not the fallback."""
        await _seed_full_pipeline_patient(db)

        # Create an eval session + PatientResult tying a pipeline_run to the session,
        # plus a SearchMatch for the patient.
        db.add(EvaluationSession(
            id="sess-1",
            project_id="proj-1",
            created_by="u1",
            status=SessionStatus.REVIEWING,
            search_queries=[{"query": "splenomegaly", "type": "include"}],
        ))
        db.add(PatientResult(
            session_id="sess-1",
            patient_id="pat-1",
            pipeline_run_id="run-1",
            status="completed",
        ))
        db.add(SearchMatch(
            session_id="sess-1",
            patient_id="pat-1",
            note_id="note-1",
            matched_tokens=["splenomegaly"],
            match_positions=[{"start": 10, "end": 22, "text": "splenomegaly sentence"}],
            is_negated=False,
        ))
        await db.commit()

        notes = await get_patient_matched_notes(db, "proj-1", "pat-1", pipeline_run_id="run-1")
        assert len(notes) == 1
        # Sentence text comes from the SearchMatch position payload.
        assert notes[0]["matched_sentences"] == ["splenomegaly sentence"]
