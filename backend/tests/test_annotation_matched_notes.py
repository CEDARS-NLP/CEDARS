"""Tests for get_patient_matched_notes, including the annotation fallback.

SearchMatch rows only exist for the sample/preview phase. Patients processed by
the full pipeline have no SearchMatch rows, so the endpoint must fall back to
reconstructing matched notes from the patient's annotations.
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

# Import ALL models so SQLModel.metadata.create_all creates every table.
from app.auth.models import User  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.connectors.models import DataSource, Patient, Note  # noqa: F401
from app.predictors.models import PredictorConfig  # noqa: F401
from app.nlp.models import Sentence, SearchQuery, NlpJob  # noqa: F401
from app.annotations.models import Annotation, ReviewStatus  # noqa: F401
from app.evaluation.models import (  # noqa: F401
    EvaluationSession,
    PatientResult,
    SearchMatch,
    SessionStatus,
)
from app.jobs.models import BackgroundJob  # noqa: F401
from app.pipeline.models import EventConfig, PipelineRun, PatientTask, Evidence  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401

from app.annotations.query_service import get_patient_matched_notes


@pytest.fixture
async def db():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as session:
        yield session
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


async def _seed_full_pipeline_patient(db: AsyncSession):
    """A patient processed by the full pipeline: has an Annotation, NO SearchMatch."""
    db.add(User(id="u1", email="a@b.com", name="A", password_hash="x"))
    db.add(Project(id="proj-1", name="P", owner_id="u1"))
    db.add(Patient(id="pat-1", project_id="proj-1", patient_id_ext="EXT-1"))
    db.add(Note(
        id="note-1",
        project_id="proj-1",
        patient_id="pat-1",
        text_id="TXT-1",
        note_date=datetime(2022, 4, 27, tzinfo=UTC),
        text="Findings: marked splenomegaly. Impression: small splenic infarct noted.",
    ))
    db.add(Annotation(
        id="ann-1",
        project_id="proj-1",
        patient_id="pat-1",
        note_id="note-1",
        sentence_text="marked splenomegaly; small splenic infarct noted",
        matched_tokens="splenomegaly,splenic",
        predicted_score=0.95,
        predicted_label=1,
        predictor_model="test-model",
        review_status=ReviewStatus.UNREVIEWED,
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
        # Keywords derived from comma-separated matched_tokens.
        assert set(n["search_keywords"]) == {"splenomegaly", "splenic"}
        # Sentences split from the "; "-joined sentence_text.
        assert len(n["matched_sentences"]) == 2
        # Positions computed by locating keywords in the full note text.
        assert len(n["match_positions"]) >= 2
        for pos in n["match_positions"]:
            assert 0 <= pos["start"] < pos["end"] <= len(n["text"])

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
