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


class TestCommit:
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
