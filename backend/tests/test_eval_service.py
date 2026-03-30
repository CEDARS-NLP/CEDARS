"""Tests for evaluation service: session CRUD and search execution."""

from datetime import UTC, datetime
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

# Import ALL models so SQLModel.metadata.create_all creates all tables
from app.auth.models import User  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401
from app.connectors.models import DataSource, Patient, Note  # noqa: F401
from app.predictors.models import PredictorConfig  # noqa: F401
from app.nlp.models import Sentence, SearchQuery, NlpJob  # noqa: F401
from app.annotations.models import Annotation  # noqa: F401
from app.evaluation.models import (
    EvaluationSession,
    PatientResult,
    SearchMatch,
    SessionStatus,
)
from app.jobs.models import BackgroundJob  # noqa: F401
from app.pipeline.models import EventConfig as _EC, PipelineRun as _PR, PatientTask as _PT, Evidence as _Ev  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401

from app.evaluation import service as eval_service


@pytest.fixture
async def db():
    """In-memory SQLite database with all tables created."""
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


@pytest.fixture
async def seeded_db(db):
    """Database seeded with 1 user, 1 project, 5 patients, 2 notes each.

    Patient notes:
    - Note 1: contains "troponin elevation" (should match troponin queries)
    - Note 2: contains "Follow-up visit, no complaints" (should NOT match)
    """
    user = User(
        id="user-1",
        email="test@example.com",
        name="Test User",
        password_hash="fakehash",
    )
    db.add(user)

    project = Project(
        id="proj-1",
        name="Test Project",
        owner_id="user-1",
    )
    db.add(project)

    for i in range(1, 6):
        patient = Patient(
            id=f"pat-{i}",
            project_id="proj-1",
            patient_id_ext=f"EXT-{i}",
        )
        db.add(patient)

        note1 = Note(
            id=f"note-{i}-1",
            project_id="proj-1",
            patient_id=f"pat-{i}",
            text_id=f"TXT-{i}-1",
            note_date=datetime(2024, 1, 15, tzinfo=UTC),
            text=f"Patient {i} labs show troponin elevation consistent with acute MI.",
        )
        db.add(note1)

        note2 = Note(
            id=f"note-{i}-2",
            project_id="proj-1",
            patient_id=f"pat-{i}",
            text_id=f"TXT-{i}-2",
            note_date=datetime(2024, 1, 16, tzinfo=UTC),
            text=f"Follow-up visit for patient {i}, no complaints.",
        )
        db.add(note2)

    await db.commit()
    return db


class TestCreateSession:
    async def test_create_session_samples_patients(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        assert session.id is not None
        assert session.status == SessionStatus.DRAFT
        assert session.project_id == "proj-1"
        assert session.created_by == "user-1"
        assert session.search_queries == [{"query": "troponin", "type": "include"}]
        # Should sample min(100, 5) = 5 patients
        assert len(session.sample_patient_ids) == 5
        assert session.sample_size == 5
        # All sampled IDs should be valid patient IDs
        valid_ids = {f"pat-{i}" for i in range(1, 6)}
        assert set(session.sample_patient_ids) == valid_ids

    async def test_create_session_blocks_if_active_exists(self, seeded_db):
        # Create first session
        await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        # Second session should be blocked
        with pytest.raises(ValueError, match="already has a draft session"):
            await eval_service.create_session(
                seeded_db,
                project_id="proj-1",
                user_id="user-1",
                search_queries=[{"query": "MI", "type": "include"}],
            )

    async def test_create_session_blocks_if_committed_exists(self, seeded_db):
        # Create and commit a session
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )
        session.status = SessionStatus.COMMITTED
        seeded_db.add(session)
        await seeded_db.commit()

        with pytest.raises(ValueError, match="already has a committed session"):
            await eval_service.create_session(
                seeded_db,
                project_id="proj-1",
                user_id="user-1",
            )

    async def test_create_session_allowed_after_discard(self, seeded_db):
        # Create and discard a session
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )
        await eval_service.discard_session(seeded_db, session.id)

        # New session should now be allowed
        new_session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )
        assert new_session.id is not None
        assert new_session.id != session.id

    async def test_create_session_clones_from_existing(self, seeded_db):
        # Create source session with LLM config
        source = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await eval_service.update_llm_config(
            seeded_db,
            source.id,
            event_name="MI",
            llm_provider="openai",
            llm_model="gpt-4o",
        )
        # Discard so we can create a new one
        await eval_service.discard_session(seeded_db, source.id)

        # Clone from discarded session
        cloned = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            cloned_from_id=source.id,
        )
        assert cloned.cloned_from_id == source.id
        assert cloned.search_queries == [{"query": "troponin", "type": "include"}]
        assert cloned.event_name == "MI"
        assert cloned.llm_provider == "openai"
        assert cloned.llm_model == "gpt-4o"


class TestDiscardSession:
    async def test_discard_session(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )
        assert session.status == SessionStatus.DRAFT

        discarded = await eval_service.discard_session(seeded_db, session.id)
        assert discarded.status == SessionStatus.DISCARDED

    async def test_discard_committed_session_fails(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )
        session.status = SessionStatus.COMMITTED
        seeded_db.add(session)
        await seeded_db.commit()

        with pytest.raises(ValueError, match="Cannot discard"):
            await eval_service.discard_session(seeded_db, session.id)


class TestListSessions:
    async def test_list_sessions(self, seeded_db):
        # Create two sessions (discard first to allow second)
        s1 = await eval_service.create_session(
            seeded_db, project_id="proj-1", user_id="user-1"
        )
        await eval_service.discard_session(seeded_db, s1.id)
        s2 = await eval_service.create_session(
            seeded_db, project_id="proj-1", user_id="user-1"
        )

        sessions = await eval_service.list_sessions(seeded_db, "proj-1")
        assert len(sessions) == 2
        # Most recent first
        assert sessions[0].id == s2.id
        assert sessions[1].id == s1.id

    async def test_list_sessions_empty(self, seeded_db):
        sessions = await eval_service.list_sessions(seeded_db, "proj-1")
        assert sessions == []


class TestGetSession:
    async def test_get_session(self, seeded_db):
        created = await eval_service.create_session(
            seeded_db, project_id="proj-1", user_id="user-1"
        )
        fetched = await eval_service.get_session(seeded_db, created.id)
        assert fetched is not None
        assert fetched.id == created.id

    async def test_get_session_not_found(self, seeded_db):
        result = await eval_service.get_session(seeded_db, "nonexistent-id")
        assert result is None


class TestExecuteSearchQueries:
    async def test_execute_search_creates_matches(self, seeded_db):
        """Verify that executing search queries creates SearchMatch records."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        # Mock parse_query and process_note to avoid spaCy dependency
        mock_query_groups = [[{"pattern": [{"LOWER": "troponin"}], "negated": False, "text": "troponin"}]]

        def mock_process_note(note_text, query_groups):
            if "troponin" in note_text.lower():
                return [
                    {
                        "sentence_number": 0,
                        "text": note_text,
                        "start_pos": 0,
                        "end_pos": len(note_text),
                        "is_target": True,
                        "is_negated": False,
                        "matched_tokens": ["troponin"],
                    }
                ]
            return [
                {
                    "sentence_number": 0,
                    "text": note_text,
                    "start_pos": 0,
                    "end_pos": len(note_text),
                    "is_target": False,
                    "is_negated": False,
                    "matched_tokens": [],
                }
            ]

        with patch.object(eval_service, "parse_query", return_value=mock_query_groups), \
             patch.object(eval_service, "process_note", side_effect=mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        # Check matches were created — 5 patients x 1 matching note each = 5 matches
        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        matches = result.scalars().all()
        assert len(matches) == 5

        # Verify match properties
        for match in matches:
            assert match.matched_tokens == ["troponin"]
            assert match.is_negated is False
            assert match.query_index == 0

    async def test_execute_search_no_queries(self, seeded_db):
        """Session with no queries should produce no matches."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[],
        )
        await eval_service.execute_search_queries(seeded_db, session.id)

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        assert len(result.scalars().all()) == 0


class TestFunnelStats:
    async def test_funnel_stats(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        # Mock and execute search
        mock_query_groups = [[{"pattern": [{"LOWER": "troponin"}], "negated": False, "text": "troponin"}]]

        def mock_process_note(note_text, query_groups):
            if "troponin" in note_text.lower():
                return [{
                    "sentence_number": 0,
                    "text": note_text,
                    "start_pos": 0,
                    "end_pos": len(note_text),
                    "is_target": True,
                    "is_negated": False,
                    "matched_tokens": ["troponin"],
                }]
            return [{
                "sentence_number": 0,
                "text": note_text,
                "start_pos": 0,
                "end_pos": len(note_text),
                "is_target": False,
                "is_negated": False,
                "matched_tokens": [],
            }]

        with patch.object(eval_service, "parse_query", return_value=mock_query_groups), \
             patch.object(eval_service, "process_note", side_effect=mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        stats = await eval_service.get_funnel_stats(seeded_db, session.id)

        assert stats["sample_patients"] == 5
        assert stats["sample_notes"] == 10  # 5 patients x 2 notes each
        assert stats["matched_patients"] == 5  # all patients have a matching note
        assert stats["matched_notes"] == 5  # one matching note per patient
        # 50% of notes filtered
        assert stats["filter_percent"] == 50.0
        assert stats["llm_stats"]["completed"] == 0
        assert stats["llm_stats"]["pending"] == 0
        assert stats["llm_stats"]["failed"] == 0


class TestGetQueryMatches:
    async def test_get_query_matches_returns_highlighted_notes(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        mock_query_groups = [[{"pattern": [{"LOWER": "troponin"}], "negated": False, "text": "troponin"}]]

        def mock_process_note(note_text, query_groups):
            if "troponin" in note_text.lower():
                return [{
                    "sentence_number": 0,
                    "text": note_text,
                    "start_pos": 0,
                    "end_pos": len(note_text),
                    "is_target": True,
                    "is_negated": False,
                    "matched_tokens": ["troponin"],
                }]
            return [{
                "sentence_number": 0,
                "text": note_text,
                "start_pos": 0,
                "end_pos": len(note_text),
                "is_target": False,
                "is_negated": False,
                "matched_tokens": [],
            }]

        with patch.object(eval_service, "parse_query", return_value=mock_query_groups), \
             patch.object(eval_service, "process_note", side_effect=mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        result = await eval_service.get_query_matches(
            seeded_db, session.id, query_index=0, page=1, page_size=3
        )

        assert result["total"] == 5
        assert result["page"] == 1
        assert result["page_size"] == 3
        assert len(result["matches"]) == 3  # limited by page_size

        # Verify match structure
        match = result["matches"][0]
        assert "note_id" in match
        assert "patient_id" in match
        assert match["matched_tokens"] == ["troponin"]
        assert "note_text" in match
        assert "troponin" in match["note_text"].lower()
        assert len(match["highlights"]) > 0
        assert "text" in match["highlights"][0]

    async def test_get_query_matches_pagination(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        mock_query_groups = [[{"pattern": [{"LOWER": "troponin"}], "negated": False, "text": "troponin"}]]

        def mock_process_note(note_text, query_groups):
            if "troponin" in note_text.lower():
                return [{
                    "sentence_number": 0,
                    "text": note_text,
                    "start_pos": 0,
                    "end_pos": len(note_text),
                    "is_target": True,
                    "is_negated": False,
                    "matched_tokens": ["troponin"],
                }]
            return [{
                "sentence_number": 0,
                "text": note_text,
                "start_pos": 0,
                "end_pos": len(note_text),
                "is_target": False,
                "is_negated": False,
                "matched_tokens": [],
            }]

        with patch.object(eval_service, "parse_query", return_value=mock_query_groups), \
             patch.object(eval_service, "process_note", side_effect=mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        page2 = await eval_service.get_query_matches(
            seeded_db, session.id, query_index=0, page=2, page_size=3
        )
        assert page2["total"] == 5
        assert len(page2["matches"]) == 2  # 5 total, page_size 3, page 2 = 2 remaining


class TestUpdateQueries:
    async def test_update_queries_clears_matches(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )

        # Create a match manually
        match = SearchMatch(
            session_id=session.id,
            query_index=0,
            patient_id="pat-1",
            note_id="note-1-1",
            matched_tokens=["troponin"],
        )
        seeded_db.add(match)
        await seeded_db.commit()

        # Update queries — should clear matches
        updated = await eval_service.update_queries(
            seeded_db,
            session.id,
            search_queries=[{"query": "MI", "type": "include"}],
        )
        assert updated.search_queries == [{"query": "MI", "type": "include"}]

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        assert len(result.scalars().all()) == 0


class TestUpdateLlmConfig:
    async def test_update_llm_config(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )

        updated = await eval_service.update_llm_config(
            seeded_db,
            session.id,
            event_name="MI Detection",
            llm_provider="openai",
            llm_model="gpt-4o",
            include_criteria="Troponin elevation",
            exclude_criteria="Rule-out MI",
        )

        assert updated.event_name == "MI Detection"
        assert updated.llm_provider == "openai"
        assert updated.llm_model == "gpt-4o"
        assert updated.include_criteria == "Troponin elevation"
        assert updated.exclude_criteria == "Rule-out MI"

    async def test_update_llm_config_ignores_unknown_fields(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )

        updated = await eval_service.update_llm_config(
            seeded_db,
            session.id,
            event_name="Test",
            bogus_field="should be ignored",
        )
        assert updated.event_name == "Test"
        assert not hasattr(updated, "bogus_field") or getattr(updated, "bogus_field", None) is None
