import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.evaluation.models import (
    EvaluationSession,
    PatientResult,
    PatientResultStatus,
    SearchMatch,
    SessionStatus,
)


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.drop_all)
    await engine.dispose()


class TestEvaluationSession:
    async def test_create_draft_session(self, session):
        es = EvaluationSession(
            project_id="proj-1",
            created_by="user-1",
            status=SessionStatus.DRAFT,
            search_queries=[{"query": "troponin OR MI", "type": "include"}],
            sample_size=100,
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)

        assert es.id is not None
        assert es.status == SessionStatus.DRAFT
        assert es.search_queries[0]["query"] == "troponin OR MI"
        assert es.sample_size == 100
        assert es.event_name is None
        assert es.committed_config is None

    async def test_default_status_is_draft(self, session):
        es = EvaluationSession(
            project_id="proj-1",
            created_by="user-1",
            sample_size=100,
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)
        assert es.status == SessionStatus.DRAFT

    async def test_session_with_llm_config(self, session):
        es = EvaluationSession(
            project_id="proj-1",
            created_by="user-1",
            sample_size=100,
            event_name="Myocardial Infarction",
            event_description="Confirmed MI",
            include_criteria="Troponin elevation",
            exclude_criteria="Rule-out",
            llm_provider="openai",
            llm_model="gpt-4o-mini",
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)
        assert es.event_name == "Myocardial Infarction"
        assert es.llm_provider == "openai"


class TestSearchMatch:
    async def test_create_search_match(self, session):
        # Need an EvaluationSession first
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)

        sm = SearchMatch(
            session_id=es.id,
            query_index=0,
            patient_id="pat-1",
            note_id="note-1",
            matched_tokens=["troponin", "MI"],
            match_positions=[{"start": 10, "end": 18, "token": "troponin"}],
            is_negated=False,
        )
        session.add(sm)
        await session.commit()
        await session.refresh(sm)

        assert sm.id is not None
        assert sm.matched_tokens == ["troponin", "MI"]
        assert sm.is_negated is False


class TestPatientResult:
    async def test_create_patient_result(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()
        await session.refresh(es)

        pr = PatientResult(
            session_id=es.id,
            patient_id="pat-1",
            status=PatientResultStatus.QUEUED,
        )
        session.add(pr)
        await session.commit()
        await session.refresh(pr)

        assert pr.id is not None
        assert pr.status == PatientResultStatus.QUEUED
        assert pr.finding_label is None

    async def test_transition_queued_to_processing(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()

        pr = PatientResult(session_id=es.id, patient_id="pat-1")
        pr.transition_status(PatientResultStatus.PROCESSING)
        assert pr.status == PatientResultStatus.PROCESSING

    async def test_invalid_transition_raises(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()

        pr = PatientResult(session_id=es.id, patient_id="pat-1")
        pr.transition_status(PatientResultStatus.PROCESSING)
        pr.transition_status(PatientResultStatus.COMPLETED)

        with pytest.raises(ValueError, match="Cannot transition"):
            pr.transition_status(PatientResultStatus.QUEUED)

    async def test_patient_result_with_llm_results(self, session):
        es = EvaluationSession(
            project_id="proj-1", created_by="user-1", sample_size=100
        )
        session.add(es)
        await session.commit()

        pr = PatientResult(
            session_id=es.id,
            patient_id="pat-1",
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
            finding_reasoning="Troponin elevated",
            finding_evidence=[{"note_id": "n1", "text": "troponin 2.4", "note_date": "2024-01-15"}],
            event_date="2024-01-15",
            predicted_score=0.94,
            token_usage={"prompt_tokens": 500, "completion_tokens": 50},
        )
        session.add(pr)
        await session.commit()
        await session.refresh(pr)

        assert pr.finding_label == "positive"
        assert pr.event_date == "2024-01-15"
        assert pr.predicted_score == 0.94
