"""Tests for evaluation service: session CRUD and search execution."""

from datetime import UTC, datetime, timedelta
from unittest.mock import patch

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool
from sqlmodel import SQLModel

from app.annotations.models import Annotation  # noqa: F401
from app.audit.models import AuditEntry  # noqa: F401

# Import ALL models so SQLModel.metadata.create_all creates all tables
from app.auth.models import User  # noqa: F401
from app.connectors.models import DataSource, Note, Patient  # noqa: F401
from app.evaluation import service as eval_service
from app.evaluation.models import (
    EvaluationSession,
    EvaluationSessionQuerySection,
    PatientResult,
    PatientResultStatus,
    SearchMatch,
    SessionStatus,
)
from app.evaluation.query_expression import normalize_queries
from app.jobs.models import BackgroundJob  # noqa: F401
from app.llm.usage import add_usage
from app.nlp.models import NlpJob, SearchQuery, Sentence  # noqa: F401
from app.pipeline.models import EventConfig as _EC  # noqa: F401
from app.pipeline.models import Evidence as _Ev
from app.pipeline.models import PatientTask as _PT
from app.pipeline.models import PipelineRun as _PR
from app.production.models import NotePrediction, ProductionRun
from app.predictors.models import PredictorConfig  # noqa: F401
from app.projects.models import Project, ProjectMember  # noqa: F401


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
        llm_provider="openai",
        llm_model="gpt-4o",
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
    async def test_normalizes_draft_without_creating_search_query_records(self, seeded_db):
        from sqlalchemy import select

        session = await eval_service.create_session(
            seeded_db, "proj-1", "user-1", search_queries=[
                {"query": " DVT ", "type": "include"},
                {"query": "thromb*", "type": "include"},
                {"query": "family history", "type": "exclude"},
                {"query": "  ", "type": "include"},
            ]
        )
        expected = [{"query": "((DVT) OR (thromb*)) AND !((family history))", "type": "include"}]
        assert session.search_queries == expected
        assert normalize_queries(expected) == expected
        updated = await eval_service.update_queries(seeded_db, session.id, expected)
        assert updated.search_queries == expected
        assert (await seeded_db.execute(select(SearchQuery))).scalars().all() == []

    @pytest.mark.parametrize("rows", [
        [{"query": "DVT", "type": "other"}], [{"query": 1, "type": "include"}],
        [{"query": "DVT", "type": "exclude"}], [{"query": "DVT AND", "type": "include"}],
    ])
    async def test_invalid_creation_does_not_persist(self, seeded_db, rows):
        with pytest.raises(ValueError):
            await eval_service.create_session(seeded_db, "proj-1", "user-1", search_queries=rows)
        assert await eval_service.list_sessions(seeded_db, "proj-1") == []

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
        )
        await eval_service.update_queries(
            seeded_db,
            source.id,
            search_queries=[
                {"query": "troponin", "type": "include"},
                {"query": "history", "type": "exclude"},
            ],
            exclude_negated=False,
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
        assert cloned.search_queries == [
            {"query": "(troponin) AND !((history))", "type": "include"}
        ]
        assert await eval_service.get_query_sections(seeded_db, cloned.id) == [
            {"query": "troponin", "type": "include"},
            {"query": "history", "type": "exclude"},
        ]
        assert cloned.event_name == "MI"
        assert cloned.exclude_negated is False


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
    async def test_sample_uses_own_combined_expression_not_active_query(self, seeded_db):
        from sqlalchemy import select

        session = await eval_service.create_session(seeded_db, "proj-1", "user-1")
        session.search_queries = [
            {"query": "troponin elevation", "type": "include"},
            {"query": "suspected", "type": "exclude"},
        ]
        note = await seeded_db.get(Note, "note-1-1")
        note.text = "Suspected troponin elevation. Confirmed troponin elevation."
        active = SearchQuery(project_id="proj-1", query="headache")
        seeded_db.add(active)
        await seeded_db.commit()
        await eval_service.execute_search_queries(seeded_db, session.id)
        matches = (await seeded_db.execute(select(SearchMatch))).scalars().all()
        assert len(matches) == 5
        assert {match.query_index for match in matches} == {0}
        first = next(match for match in matches if match.note_id == note.id)
        assert first.match_positions[0]["text"] == "Confirmed troponin elevation."
        queries = (await seeded_db.execute(select(SearchQuery))).scalars().all()
        assert len(queries) == 1 and queries[0].id == active.id and queries[0].is_active
        assert len(session.search_queries) == 1

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

    async def test_query_index_counts_excluded_queries(self, seeded_db):
        """Matches reference the merged saved expression, not the draft row index."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[
                {"query": "aspirin", "type": "exclude"},
                {"query": "troponin", "type": "include"},
            ],
        )

        with patch.object(eval_service, "parse_query", side_effect=_mock_parse_query), \
             patch.object(eval_service, "process_note", side_effect=_mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        matches = result.scalars().all()
        assert len(matches) == 5
        assert session.search_queries == [
            {"query": "(troponin) AND !((aspirin))", "type": "include"}
        ]
        assert {match.query_index for match in matches} == {0}

    async def test_query_index_is_zero_after_exclude_normalization(self, seeded_db):
        """An exclude-first draft becomes one include expression at index zero."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[
                {"query": "aspirin", "type": "exclude"},
                {"query": "troponin", "type": "include"},
            ],
        )

        with patch.object(eval_service, "parse_query", side_effect=_mock_parse_query), \
             patch.object(eval_service, "process_note", side_effect=_mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        matches = result.scalars().all()
        assert len(matches) == 5
        assert {m.query_index for m in matches} == {0}
        assert session.search_queries == [
            {"query": "(troponin) AND !((aspirin))", "type": "include"}
        ]

    async def test_execute_search_no_queries(self, seeded_db):
        """Empty creation is allowed, but execution requires a saved include query."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[],
        )
        with pytest.raises(ValueError, match="include search query"):
            await eval_service.execute_search_queries(seeded_db, session.id)

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        assert len(result.scalars().all()) == 0

    async def test_execute_search_drops_negated_by_default(self, seeded_db):
        """Default sessions drop negated matches — the pre-existing behavior."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        assert session.exclude_negated is True

        def negated_process_note(note_text, query_groups):
            if "troponin" in note_text.lower():
                return [{
                    "sentence_number": 0,
                    "text": note_text,
                    "start_pos": 0,
                    "end_pos": len(note_text),
                    "is_target": True,
                    "is_negated": True,
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

        with patch.object(eval_service, "parse_query", side_effect=_mock_parse_query), \
             patch.object(eval_service, "process_note", side_effect=negated_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        assert len(result.scalars().all()) == 0

    async def test_update_queries_persists_exclude_negated(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        assert session.exclude_negated is True

        updated = await eval_service.update_queries(
            seeded_db,
            session.id,
            search_queries=[{"query": "troponin", "type": "include"}],
            exclude_negated=False,
        )
        assert updated.exclude_negated is False

        refetched = await eval_service.get_session(seeded_db, session.id)
        assert refetched.exclude_negated is False

    async def test_execute_search_stores_negated_when_kept(self, seeded_db):
        """exclude_negated=False stores negated matches with is_negated=True."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await eval_service.update_queries(
            seeded_db,
            session.id,
            search_queries=[{"query": "troponin", "type": "include"}],
            exclude_negated=False,
        )

        def negated_process_note(note_text, query_groups):
            if "troponin" in note_text.lower():
                return [{
                    "sentence_number": 0,
                    "text": note_text,
                    "start_pos": 0,
                    "end_pos": len(note_text),
                    "is_target": True,
                    "is_negated": True,
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

        with patch.object(eval_service, "parse_query", side_effect=_mock_parse_query), \
             patch.object(eval_service, "process_note", side_effect=negated_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        from sqlalchemy import select as sa_select
        result = await seeded_db.execute(
            sa_select(SearchMatch).where(SearchMatch.session_id == session.id)
        )
        matches = result.scalars().all()
        assert len(matches) == 5
        assert all(match.is_negated is True for match in matches)


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
    async def test_get_query_sections_falls_back_for_legacy_session(self, seeded_db):
        session = await eval_service.create_session(seeded_db, "proj-1", "user-1")
        session.search_queries = [{"query": "DVT OR PE", "type": "include"}]
        seeded_db.add(session)
        await seeded_db.commit()

        assert await eval_service.get_query_sections(seeded_db, session.id) == [
            {"query": "DVT OR PE", "type": "include"}
        ]

    async def test_update_queries_persists_display_sections_separately(self, seeded_db):
        sections = [
            {"query": "DVT OR embol*", "type": "include"},
            {"query": "suspected", "type": "exclude"},
        ]
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )

        updated = await eval_service.update_queries(seeded_db, session.id, sections)

        assert updated.search_queries == [
            {"query": "(DVT OR embol*) AND !((suspected))", "type": "include"}
        ]
        assert await eval_service.get_query_sections(seeded_db, session.id) == sections

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
            include_criteria="Troponin elevation",
            exclude_criteria="Rule-out MI",
        )

        assert updated.event_name == "MI Detection"
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


# ── Helpers for LLM tests ────────────────────────────────────────

from unittest.mock import AsyncMock

from app.pipeline.classifier import ClassificationResult


def _mock_parse_query(query_str):
    """Return a fake query group matching 'troponin'."""
    return [[{"pattern": [{"LOWER": "troponin"}], "negated": False, "text": "troponin"}]]


def _mock_process_note(note_text, query_groups):
    """Return a match if 'troponin' appears in note text."""
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


async def _create_session_with_search(seeded_db):
    """Helper: create session, configure LLM, execute search. Returns session."""
    session = await eval_service.create_session(
        seeded_db,
        project_id="proj-1",
        user_id="user-1",
        search_queries=[{"query": "troponin", "type": "include"}],
    )
    await eval_service.update_llm_config(
        seeded_db,
        session.id,
        event_name="MI Detection",
        event_description="Myocardial infarction",
        include_criteria="Troponin elevation",
        exclude_criteria="Rule-out MI",
    )
    with patch.object(eval_service, "parse_query", side_effect=_mock_parse_query), \
         patch.object(eval_service, "process_note", side_effect=_mock_process_note):
        await eval_service.execute_search_queries(seeded_db, session.id)

    # Refresh to pick up updated fields
    refreshed = await eval_service.get_session(seeded_db, session.id)
    return refreshed


class TestLlmRun:
    async def test_run_llm_creates_patient_results(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive",
            confidence=0.95,
            reasoning="Troponin elevation detected",
            event_date="2024-01-15",
            evidence=[{"note_id": "note-1-1", "text": "troponin elevation"}],
            token_usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150},
        )

        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            stats = await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        assert stats["patients_classified"] == 5  # all 5 patients matched troponin
        assert stats["patients_no_match"] == 0
        assert stats["patients_failed"] == 0
        assert stats["token_usage"]["total_tokens"] == 750  # 150 * 5

        # Session should be REVIEWING now
        updated = await eval_service.get_session(seeded_db, session.id)
        assert updated.status == SessionStatus.REVIEWING

    async def test_run_llm_handles_failures(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        async def failing_classify(*args, **kwargs):
            raise ValueError("LLM API error")

        with patch.object(eval_service, "classify_patient", side_effect=failing_classify):
            stats = await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        assert stats["patients_classified"] == 0
        assert stats["patients_failed"] == 5

    async def test_run_llm_creates_no_match_results(self, seeded_db):
        """When search has no matches, all sample patients get NO_MATCH."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "nonexistent_term", "type": "include"}],
        )
        # Execute search with no results
        def no_match_process(note_text, query_groups):
            return [{
                "sentence_number": 0, "text": note_text,
                "start_pos": 0, "end_pos": len(note_text),
                "is_target": False, "is_negated": False, "matched_tokens": [],
            }]

        with patch.object(eval_service, "parse_query", return_value=[[{"pattern": [], "negated": False, "text": "x"}]]), \
             patch.object(eval_service, "process_note", side_effect=no_match_process):
            await eval_service.execute_search_queries(seeded_db, session.id)

        await eval_service.update_llm_config(
            seeded_db, session.id,
            event_name="Test",
        )

        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock):
            stats = await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        assert stats["patients_classified"] == 0
        assert stats["patients_no_match"] == 5

    async def test_run_llm_records_notes_searched_vs_matched(self, seeded_db):
        """notes_searched is every note the search read, not just the matches.

        Each seeded patient has 2 notes and only 1 mentions troponin, so the
        review panel should read "2 notes searched · 1 matched". Setting both to
        the matched count made every patient look like the queries skipped
        nothing.
        """
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        listing = await eval_service.list_patient_results(seeded_db, session.id)
        assert listing["results"]
        for pr in listing["results"]:
            assert pr.notes_searched == 2
            assert pr.notes_matched == 1

    async def test_run_llm_rejects_concurrent_run(self, seeded_db):
        """A run that is genuinely in flight blocks a second one."""
        session = await _create_session_with_search(seeded_db)
        session.metrics = {"llm_status": "running", "llm_total": 5, "llm_completed": 2}
        session.updated_at = datetime.now(UTC)
        seeded_db.add(session)
        await seeded_db.commit()

        with pytest.raises(ValueError, match="already running"):
            await eval_service.run_llm_on_sample(seeded_db, session.id, "proj-1")

    async def test_run_llm_restarts_stalled_run(self, seeded_db):
        """A killed worker must not lock the session out of classification.

        There is no UI path to clear llm_status, so a run with no progress for
        longer than _STALLED_LLM_RUN is treated as dead and may be restarted.
        """
        session = await _create_session_with_search(seeded_db)
        session.metrics = {"llm_status": "running", "llm_total": 5, "llm_completed": 2}
        session.updated_at = datetime.now(UTC) - eval_service._STALLED_LLM_RUN - timedelta(minutes=1)
        seeded_db.add(session)
        await seeded_db.commit()

        mock_pool = AsyncMock()
        with patch("arq.create_pool", new_callable=AsyncMock, return_value=mock_pool):
            stats = await eval_service.run_llm_on_sample(seeded_db, session.id, "proj-1")

        assert stats["status"] == "started"
        assert stats["matched_patients"] == 5
        mock_pool.enqueue_job.assert_awaited_once()

        restarted = await eval_service.get_session(seeded_db, session.id)
        assert restarted.metrics["llm_status"] == "running"
        assert restarted.metrics["llm_completed"] == 0


class TestListPatientResults:
    async def test_list_patient_results_paginated(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        result = await eval_service.list_patient_results(
            seeded_db, session.id, page=1, page_size=3,
        )
        assert result["total"] == 5
        assert len(result["results"]) == 3
        assert result["total_pages"] == 2

    async def test_list_patient_results_filter_by_label(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        call_count = 0

        async def alternating_classify(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            label = "positive" if call_count % 2 == 0 else "negative"
            return ClassificationResult(
                label=label, confidence=0.8, reasoning="Test",
                token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            )

        with patch.object(eval_service, "classify_patient", side_effect=alternating_classify):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        pos = await eval_service.list_patient_results(
            seeded_db, session.id, label_filter="positive",
        )
        neg = await eval_service.list_patient_results(
            seeded_db, session.id, label_filter="negative",
        )
        assert pos["total"] + neg["total"] == 5


class TestReviewQueue:
    async def test_queue_empties_and_ignores_pipeline_results(self, seeded_db):
        """The sample queue stays empty after sample judgments and production work."""
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        first = await eval_service.get_next_unreviewed_result(seeded_db, session.id)
        assert first is not None
        assert first["total_results"] == 5
        assert first["total_unreviewed"] == 5

        listing = await eval_service.list_patient_results(seeded_db, session.id)
        for pr in listing["results"]:
            await eval_service.submit_judgment(
                seeded_db, patient_result_id=pr.id,
                judgment="correct", user_id="user-1",
            )

        assert await eval_service.get_next_unreviewed_result(seeded_db, session.id) is None

        # A completed production note prediction must not reopen the sample queue.
        run = ProductionRun(
            project_id="proj-1",
            created_by="user-1",
            status="completed",
            config_snapshot={"evaluation_session_id": session.id},
            total_notes=1,
            completed_notes=1,
        )
        seeded_db.add(run)
        await seeded_db.flush()
        seeded_db.add(NotePrediction(
            project_id="proj-1",
            run_id=run.id,
            text_id="TXT-1-1",
            patient_id="EXT-1",
            note_uuid="note-1-1",
            patient_uuid="pat-1",
            status="succeeded",
            label=1,
            score=0.9,
            token_usage={
                "prompt_tokens": 1000,
                "completion_tokens": 100,
                "total_tokens": 1100,
            },
        ))
        await seeded_db.commit()

        assert await eval_service.get_next_unreviewed_result(seeded_db, session.id) is None


class TestReview:
    async def test_submit_judgment(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.95, reasoning="Troponin found",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        # Get the first result
        listing = await eval_service.list_patient_results(seeded_db, session.id)
        first_result = listing["results"][0]

        judged = await eval_service.submit_judgment(
            seeded_db,
            patient_result_id=first_result.id,
            judgment="correct",
            user_id="user-1",
        )
        assert judged.review_judgment == "correct"
        assert judged.reviewed_by == "user-1"
        assert judged.reviewed_at is not None

    async def test_submit_judgment_with_date_override(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        listing = await eval_service.list_patient_results(seeded_db, session.id)
        first_result = listing["results"][0]

        judged = await eval_service.submit_judgment(
            seeded_db,
            patient_result_id=first_result.id,
            judgment="correct",
            user_id="user-1",
            event_date_override="2024-01-20",
        )
        assert judged.reviewer_date_override == "2024-01-20"

    async def test_compute_metrics(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.95, reasoning="Troponin found",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        # Judge all results as correct
        listing = await eval_service.list_patient_results(seeded_db, session.id)
        for pr in listing["results"]:
            if pr.finding_label:  # skip NO_MATCH
                await eval_service.submit_judgment(
                    seeded_db, patient_result_id=pr.id,
                    judgment="correct", user_id="user-1",
                )

        metrics = await eval_service.compute_metrics(seeded_db, session.id)
        assert metrics["total_reviewed"] == 5
        assert metrics["tp"] == 5  # all positive + correct
        assert metrics["accuracy"] == 1.0
        assert metrics["precision"] == 1.0
        assert metrics["recall"] == 1.0
        assert metrics["f1"] == 1.0

    async def test_compute_metrics_mixed(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        listing = await eval_service.list_patient_results(seeded_db, session.id)
        results = listing["results"]

        # Judge some correct, some wrong
        for i, pr in enumerate(results):
            if pr.finding_label:
                judgment = "correct" if i < 3 else "wrong"
                await eval_service.submit_judgment(
                    seeded_db, patient_result_id=pr.id,
                    judgment=judgment, user_id="user-1",
                )

        metrics = await eval_service.compute_metrics(seeded_db, session.id)
        assert metrics["total_reviewed"] == 5
        assert metrics["tp"] == 3  # positive + correct
        assert metrics["fp"] == 2  # positive + wrong
        assert metrics["accuracy"] > 0

    async def test_compute_metrics_counts_pending(self, seeded_db):
        """total_pending is the unjudged remainder, not a constant."""
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        await eval_service.update_llm_config(
            seeded_db, session.id, event_name="MI Detection",
        )
        with patch.object(eval_service, "parse_query", side_effect=_mock_parse_query), \
             patch.object(eval_service, "process_note", side_effect=_mock_process_note):
            await eval_service.execute_search_queries(seeded_db, session.id)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        metrics = await eval_service.compute_metrics(seeded_db, session.id)
        assert metrics["total_reviewed"] == 0
        assert metrics["total_pending"] == 5

        listing = await eval_service.list_patient_results(seeded_db, session.id)
        await eval_service.submit_judgment(
            seeded_db, patient_result_id=listing["results"][0].id,
            judgment="correct", user_id="user-1",
        )

        metrics = await eval_service.compute_metrics(seeded_db, session.id)
        assert metrics["total_reviewed"] == 1
        assert metrics["total_pending"] == 4

    async def test_compute_metrics_preserves_llm_progress(self, seeded_db):
        """Metrics must not erase the record that the sample run finished.

        compute_metrics used to replace session.metrics wholesale, dropping
        llm_status and llm_completed — so the UI lost track of whether the
        sample had been classified as soon as anyone was judged.
        """
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        before = await eval_service.get_session(seeded_db, session.id)
        assert before.metrics["llm_status"] == "completed"

        listing = await eval_service.list_patient_results(seeded_db, session.id)
        await eval_service.submit_judgment(
            seeded_db, patient_result_id=listing["results"][0].id,
            judgment="correct", user_id="user-1",
        )
        await eval_service.compute_metrics(seeded_db, session.id)

        after = await eval_service.get_session(seeded_db, session.id)
        assert after.metrics["llm_status"] == "completed"
        assert after.metrics["llm_completed"] == before.metrics["llm_completed"]
        assert after.metrics["token_usage"] == before.metrics["token_usage"]
        assert after.metrics["total_reviewed"] == 1


class TestCommit:
    @pytest.mark.parametrize("artifact", ["sentences", "annotations", "predictions"])
    @pytest.mark.parametrize("confirmation_kind", ["missing", "unconfirmed", "stale"])
    async def test_each_processed_artifact_requires_exact_confirmation(
        self, seeded_db, artifact, confirmation_kind,
    ):
        from sqlalchemy import select

        from app.nlp.schemas import ReprocessRequest
        from app.nlp.service import get_reprocess_impact
        from app.production.models import NotePrediction, ProductionRun

        session = await eval_service.create_session(
            seeded_db, "proj-1", "user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        session.status = SessionStatus.REVIEWING
        seeded_db.add(PatientResult(
            session_id=session.id,
            patient_id="pat-1",
            status=PatientResultStatus.COMPLETED,
            finding_label="positive",
        ))
        old_query = SearchQuery(project_id="proj-1", query="aspirin")
        seeded_db.add(old_query)
        if artifact == "sentences":
            seeded_db.add(Sentence(
                project_id="proj-1", note_id="note-1-1", sentence_number=0,
                text="Old sentence", start_pos=0, end_pos=12,
            ))
        else:
            annotation = Annotation(
                project_id="proj-1",
                text_id="TXT-1-1",
                patient_id="EXT-1",
                text_date=datetime(2024, 1, 15, tzinfo=UTC).date(),
                sentence="Old annotation",
                token="annotation",
                isNegated=False,
                note_start_index=0,
                note_end_index=15,
                sentence_number=0,
                sentence_start=0,
                sentence_end=15,
                patient_uuid="pat-1",
                note_uuid="note-1-1",
            )
            seeded_db.add(annotation)
            if artifact == "predictions":
                await seeded_db.flush()
                run = ProductionRun(
                    project_id="proj-1",
                    created_by="user-1",
                    status="completed",
                    config_snapshot={},
                    total_notes=1,
                )
                seeded_db.add(run)
                await seeded_db.flush()
                seeded_db.add(NotePrediction(
                    project_id="proj-1",
                    run_id=run.id,
                    text_id="TXT-1-1",
                    patient_id="EXT-1",
                    patient_uuid="pat-1",
                    note_uuid="note-1-1",
                    status="succeeded",
                    label=1,
                ))
        await seeded_db.commit()
        impact = await get_reprocess_impact(seeded_db, "proj-1")
        assert impact == {
            "sentences": int(artifact == "sentences"),
            "annotations": int(artifact != "sentences"),
            "predictions": int(artifact == "predictions"),
        }
        confirmation = None
        if confirmation_kind != "missing":
            expected = dict(impact)
            if confirmation_kind == "stale":
                expected[artifact] += 1
            confirmation = ReprocessRequest(
                confirmed=confirmation_kind != "unconfirmed",
                **{f"expected_{key}": value for key, value in expected.items()},
            )
        with patch("app.nlp.service.run_nlp_pipeline", new_callable=AsyncMock) as rebuild:
            with pytest.raises(ValueError, match=(
                "counts changed" if confirmation_kind == "stale" else "Confirm deletion"
            )):
                await eval_service.commit_session(
                    seeded_db, session.id, "user-1", confirmation=confirmation,
                )
            rebuild.assert_not_awaited()
        await seeded_db.refresh(session)
        await seeded_db.refresh(old_query)
        assert session.status == SessionStatus.REVIEWING
        assert session.committed_config is None
        assert session.committed_at is None
        assert session.committed_by is None
        assert old_query.is_active
        assert (await seeded_db.execute(select(SearchQuery))).scalars().all() == [old_query]
        assert await get_reprocess_impact(seeded_db, "proj-1") == impact

    @pytest.mark.parametrize("exclude_negated", [True, False])
    async def test_commit_activates_one_merged_legacy_expression(self, seeded_db, exclude_negated):
        from sqlalchemy import select
        from app.nlp.schemas import ReprocessRequest

        session = await eval_service.create_session(seeded_db, "proj-1", "user-1")
        session.status = SessionStatus.REVIEWING
        session.exclude_negated = exclude_negated
        session.search_queries = [
            {"query": "DVT", "type": "include"},
            {"query": "troponin", "type": "include"},
            {"query": "suspected", "type": "exclude"},
        ]
        old = SearchQuery(project_id="proj-1", query="aspirin")
        seeded_db.add(old)
        sentence = Sentence(
            project_id="proj-1", note_id="note-1-1", sentence_number=0,
            text="Existing source sentence", start_pos=0, end_pos=24,
        )
        seeded_db.add(sentence)
        await seeded_db.commit()
        committed = await eval_service.commit_session(
            seeded_db,
            session.id,
            "user-1",
            confirmation=ReprocessRequest(
                confirmed=True,
                expected_annotations=0,
                expected_predictions=0,
                expected_sentences=1,
            ),
        )
        queries = (await seeded_db.execute(select(SearchQuery))).scalars().all()
        assert queries == [old]
        assert old.is_active
        assert (await seeded_db.execute(select(Sentence))).scalars().all() == [sentence]
        assert committed.committed_config["exclude_negated"] is exclude_negated
        assert committed.search_queries == [
            {"query": "DVT", "type": "include"},
            {"query": "troponin", "type": "include"},
            {"query": "suspected", "type": "exclude"},
        ]
        assert committed.committed_config["search_queries"] == committed.search_queries
        assert (await seeded_db.execute(select(ProductionRun))).scalars().all() == []
        assert (await seeded_db.execute(select(NotePrediction))).scalars().all() == []

    async def test_commit_session(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        committed = await eval_service.commit_session(
            seeded_db, session.id, user_id="user-1",
        )
        assert committed.status == SessionStatus.COMMITTED
        assert committed.committed_config is not None
        assert committed.committed_config["event_name"] == "MI Detection"
        assert committed.committed_config["llm_provider"] == "openai"
        assert committed.committed_at is not None
        assert committed.committed_by == "user-1"

    async def test_commit_session_with_threshold(self, seeded_db):
        session = await _create_session_with_search(seeded_db)

        mock_result = ClassificationResult(
            label="positive", confidence=0.9, reasoning="Match",
            token_usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        )
        with patch.object(eval_service, "classify_patient", new_callable=AsyncMock, return_value=mock_result):
            await eval_service.execute_sample_llm(session.id, "proj-1", db_session=seeded_db)

        committed = await eval_service.commit_session(
            seeded_db, session.id, user_id="user-1", confidence_threshold=0.8,
        )
        assert committed.committed_config["confidence_threshold"] == 0.8

    async def test_commit_draft_session_fails(self, seeded_db):
        session = await eval_service.create_session(
            seeded_db,
            project_id="proj-1",
            user_id="user-1",
        )
        with pytest.raises(ValueError, match="Cannot commit session"):
            await eval_service.commit_session(seeded_db, session.id, user_id="user-1")


class TestCostSummary:
    USAGE = {"prompt_tokens": 1000, "completion_tokens": 100, "total_tokens": 1100}

    async def _session_with_matches(self, db):
        session = await eval_service.create_session(
            db, project_id="proj-1", user_id="user-1",
            search_queries=[{"query": "troponin", "type": "include"}],
        )
        for i in range(1, 6):
            db.add(SearchMatch(
                session_id=session.id, patient_id=f"pat-{i}", note_id=f"note-{i}-1",
                matched_tokens=["troponin"], match_positions=[], is_negated=False,
            ))
        await db.commit()
        return session

    def _classified(self, db, session, patient, *, usage=None, source=None):
        """A sample result plus (optionally) the ledger row its call produced."""
        db.add(PatientResult(
            session_id=session.id, patient_id=patient,
            status=PatientResultStatus.COMPLETED,
            token_usage=self.USAGE if usage is None else usage,
        ))
        if source:
            add_usage(db, project_id="proj-1", source=source, provider="openai",
                      model="gpt-4o", usage=self.USAGE, ref_id=session.id)

    async def test_projection_uses_measured_sample_tokens(self, seeded_db):
        session = await self._session_with_matches(seeded_db)
        for i in (1, 2):  # two sample patients classified, 1000 in / 100 out each
            self._classified(seeded_db, session, f"pat-{i}", source="evaluation_sample")
        await seeded_db.commit()

        cost = await eval_service.get_cost_summary(seeded_db, session.id)

        assert cost["spent_prompt_tokens"] == 2000
        assert cost["spent_completion_tokens"] == 200
        assert cost["spent_cost"] == pytest.approx(0.007)  # gpt-4o: $2.50 in / $10 out per 1M
        proj = cost["projection"]
        assert proj["basis"] == "sample"
        assert proj["sample_patients_classified"] == 2
        # 5 of 5 sample patients matched and the project has 5 patients, so 5 will be
        # classified; the 2 already done are reused, leaving 3 to pay for.
        assert proj["projected_matched_patients"] == 5
        assert proj["patients_to_classify"] == 3
        assert proj["tokens_per_patient"] == 1100  # 1000 in + 100 out, measured
        assert (proj["prompt_tokens"], proj["completion_tokens"]) == (3000, 300)
        assert proj["estimated_cost"] == pytest.approx(0.0105)

    async def test_projection_falls_back_to_heuristic_before_sample_run(self, seeded_db):
        session = await self._session_with_matches(seeded_db)

        cost = await eval_service.get_cost_summary(seeded_db, session.id)

        assert cost["spent_cost"] == 0
        assert cost["projection"]["basis"] == "heuristic"
        assert cost["projection"]["estimated_cost"] > 0

    async def test_commit_copies_do_not_double_count_spend(self, seeded_db):
        session = await self._session_with_matches(seeded_db)
        # Sample results stay evaluation-owned; the full run has one note prediction
        # and an independently attributed production usage row.
        self._classified(seeded_db, session, "pat-1", source="evaluation_sample")
        run = ProductionRun(
            project_id="proj-1",
            created_by="user-1",
            status="completed",
            config_snapshot={"evaluation_session_id": session.id},
            total_notes=1,
            completed_notes=1,
        )
        seeded_db.add(run)
        await seeded_db.flush()
        seeded_db.add(NotePrediction(
            project_id="proj-1",
            run_id=run.id,
            text_id="TXT-1-1",
            patient_id="EXT-1",
            note_uuid="note-1-1",
            patient_uuid="pat-1",
            status="succeeded",
            label=1,
            score=0.9,
            token_usage=self.USAGE,
        ))
        add_usage(
            seeded_db,
            project_id="proj-1",
            source="production_run",
            provider="openai",
            model="gpt-4o",
            usage=self.USAGE,
            ref_id=run.id,
        )
        await seeded_db.commit()

        cost = await eval_service.get_cost_summary(seeded_db, session.id)

        assert cost["spent_prompt_tokens"] == 2000  # sample call plus production note call
        assert cost["projection"]["sample_patients_classified"] == 1  # copies aren't the sample

    async def test_failed_patients_do_not_dilute_the_sample_average(self, seeded_db):
        session = await self._session_with_matches(seeded_db)
        self._classified(seeded_db, session, "pat-1", source="evaluation_sample")
        seeded_db.add(PatientResult(  # failed: no call made, token_usage stored as JSON null
            session_id=session.id, patient_id="pat-2",
            status=PatientResultStatus.FAILED, token_usage=None,
        ))
        await seeded_db.commit()

        cost = await eval_service.get_cost_summary(seeded_db, session.id)

        assert cost["projection"]["sample_patients_classified"] == 1
        # 1000 tokens per patient x (5 projected - 1 already classified), not diluted by the failure.
        assert cost["projection"]["prompt_tokens"] == 4000
