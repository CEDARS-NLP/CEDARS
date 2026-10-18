"""Literal query input survives the evaluation service lifecycle."""

from unittest.mock import AsyncMock, patch

import pytest
import spacy
from sqlalchemy import select

from app.connectors.models import Note
from app.evaluation import service as eval_service
from app.evaluation.models import (
    EvaluationSession,
    EvaluationSessionQuerySection,
    SearchMatch,
    SessionStatus,
)
from app.nlp.engine import parse_query, process_note
from app.nlp.models import NlpJob, NlpJobStatus, SearchQuery, Sentence
from tests.test_eval_service import db, seeded_db  # noqa: F401


@pytest.fixture(autouse=True)
def literal_nlp():
    nlp = spacy.blank("en")
    nlp.add_pipe("sentencizer", config={"punct_chars": ["."]})
    with patch("app.nlp.engine._nlp", nlp), patch("app.nlp.engine._has_parser", False):
        yield


@pytest.fixture
async def literal_notes(seeded_db):
    async def seed(literal):
        texts = {
            "note-1-1": f"Routine visit. Marker {literal} detected.",
            "note-2-1": f"Marker {literal.replace('!', '') or 'ordinary'} detected.",
            "note-3-1": f"Marker {literal} detected with family history.",
            "note-4-1": f"No {literal} detected.",
            "note-5-1": "Unrelated clinical finding.",
        }
        for note_id, text in texts.items():
            note = await seeded_db.get(Note, note_id)
            note.text = text
        await seeded_db.commit()
        return texts

    return seed


def raw_sections(literal):
    return [
        {"query": literal, "type": "include"},
        {"query": "family history", "type": "exclude"},
    ]


async def assert_sample_matches(database, session, texts):
    await eval_service.execute_search_queries(database, session.id)
    matches = (
        await database.execute(select(SearchMatch).where(SearchMatch.session_id == session.id))
    ).scalars().all()
    assert {match.note_id for match in matches} == {"note-1-1", "note-4-1"}
    assert len(matches) == 2
    assert next(match for match in matches if match.note_id == "note-4-1").is_negated
    for match in matches:
        assert match.query_index == 0
        for position in match.match_positions:
            assert texts[match.note_id][position["start"]:position["end"]] == position["text"]
    positive = next(match for match in matches if match.note_id == "note-1-1")
    assert positive.match_positions[0]["start"] > 0


@pytest.mark.parametrize("literal", ["!troponin", "troponin!", "tro!ponin", "!troponin!", "!"])
async def test_create_raw_literal_and_exclusion_execute_without_changing_sections(
    seeded_db, literal_notes, literal,
):
    texts = await literal_notes(literal)
    sections = raw_sections(literal)
    session = await eval_service.create_session(
        seeded_db, "proj-1", "user-1", search_queries=sections,
    )
    assert await eval_service.get_query_sections(seeded_db, session.id) == sections
    assert session.search_queries == [{
        "query": f"({literal.replace('!', r'\!')}) AND !((family history))",
        "type": "include",
    }]
    await eval_service.update_queries(
        seeded_db, session.id, session.search_queries, exclude_negated=False,
    )
    await assert_sample_matches(seeded_db, session, texts)
    assert await eval_service.get_query_sections(seeded_db, session.id) == sections


async def test_raw_update_canonical_echo_and_discard_clone_preserve_sections(
    seeded_db, literal_notes,
):
    texts = await literal_notes("!troponin!")
    session = await eval_service.create_session(
        seeded_db, "proj-1", "user-1", search_queries=[{"query": "troponin", "type": "include"}],
    )
    sections = raw_sections("!troponin!")
    updated = await eval_service.update_queries(
        seeded_db, session.id, sections, exclude_negated=False,
    )
    canonical = [dict(row) for row in updated.search_queries]
    await assert_sample_matches(seeded_db, updated, texts)
    echoed = await eval_service.update_queries(
        seeded_db, session.id, canonical, exclude_negated=False,
    )
    assert echoed.search_queries == canonical
    assert await eval_service.get_query_sections(seeded_db, session.id) == sections
    assert not (
        await seeded_db.execute(select(SearchMatch).where(SearchMatch.session_id == session.id))
    ).scalars().all()
    await assert_sample_matches(seeded_db, echoed, texts)
    await eval_service.discard_session(seeded_db, session.id)
    cloned = await eval_service.create_session(
        seeded_db, "proj-1", "user-1", cloned_from_id=session.id,
    )
    assert cloned.cloned_from_id == session.id
    assert cloned.search_queries == canonical
    assert cloned.exclude_negated is False
    assert await eval_service.get_query_sections(seeded_db, cloned.id) == sections
    await assert_sample_matches(seeded_db, cloned, texts)


async def test_legacy_canonical_clone_without_raw_rows_preserves_generated_exclusion(
    seeded_db, literal_notes,
):
    texts = await literal_notes("!troponin!")
    canonical = [{"query": r"(\!troponin\!) AND !((family history))", "type": "include"}]
    source = EvaluationSession(
        project_id="proj-1", created_by="user-1", status=SessionStatus.DISCARDED,
        search_queries=canonical, exclude_negated=False,
    )
    seeded_db.add(source)
    await seeded_db.commit()
    assert not (
        await seeded_db.execute(select(EvaluationSessionQuerySection).where(
            EvaluationSessionQuerySection.session_id == source.id,
        ))
    ).scalars().all()
    cloned = await eval_service.create_session(
        seeded_db, "proj-1", "user-1", cloned_from_id=source.id,
    )
    assert cloned.search_queries == canonical
    assert cloned.exclude_negated is False
    await assert_sample_matches(seeded_db, cloned, texts)


@pytest.mark.parametrize("legacy", [False, True])
async def test_supplied_raw_queries_override_clone_rows(seeded_db, literal_notes, legacy):
    texts = await literal_notes("!troponin!")
    if legacy:
        source = EvaluationSession(
            project_id="proj-1", created_by="user-1", status=SessionStatus.DISCARDED,
            search_queries=[{"query": "(aspirin) AND !((history))", "type": "include"}],
            exclude_negated=False,
        )
        seeded_db.add(source)
        await seeded_db.commit()
    else:
        source = await eval_service.create_session(
            seeded_db, "proj-1", "user-1", search_queries=raw_sections("aspirin!"),
        )
        await eval_service.update_queries(
            seeded_db, source.id, source.search_queries, exclude_negated=False,
        )
        await eval_service.discard_session(seeded_db, source.id)
    sections = raw_sections("!troponin!")
    cloned = await eval_service.create_session(
        seeded_db, "proj-1", "user-1", cloned_from_id=source.id, search_queries=sections,
    )
    assert cloned.search_queries == [{
        "query": r"(\!troponin\!) AND !((family history))", "type": "include",
    }]
    assert await eval_service.get_query_sections(seeded_db, cloned.id) == sections
    assert cloned.exclude_negated is False
    await assert_sample_matches(seeded_db, cloned, texts)


async def test_run_all_and_final_commit_preserve_literal_meaning_and_keep_negation(
    seeded_db, literal_notes,
):
    texts = await literal_notes("!troponin!")
    sections = raw_sections("!troponin!")
    session = await eval_service.create_session(
        seeded_db, "proj-1", "user-1", search_queries=sections,
    )
    await eval_service.update_queries(
        seeded_db, session.id, session.search_queries, exclude_negated=False,
    )
    canonical = [dict(row) for row in session.search_queries]
    with patch("app.nlp.service.dispatch_nlp_job", new_callable=AsyncMock) as dispatch:
        await eval_service.run_session_queries(seeded_db, session, "user-1")
        dispatch.assert_awaited_once_with(seeded_db, "proj-1", "user-1")
    active = (await seeded_db.execute(select(SearchQuery).where(SearchQuery.is_active))).scalar_one()
    assert active.query == canonical[0]["query"]
    assert active.exclude_negated is False
    groups = parse_query(active.query)
    assert {
        note_id for note_id, text in texts.items()
        if any(sentence["is_target"] for sentence in process_note(text, groups))
    } == {"note-1-1", "note-4-1"}
    assert session.status == SessionStatus.DRAFT
    session.status = SessionStatus.REVIEWING
    await seeded_db.commit()
    committed = await eval_service.commit_session(seeded_db, session.id, "user-1")
    assert committed.status == SessionStatus.COMMITTED
    assert committed.search_queries == canonical
    assert committed.committed_config["search_queries"] == canonical
    assert committed.committed_config["exclude_negated"] is False
    assert await eval_service.get_query_sections(seeded_db, committed.id) == sections
    active = (await seeded_db.execute(select(SearchQuery).where(SearchQuery.is_active))).scalar_one()
    assert active.query == canonical[0]["query"]
    assert active.exclude_negated is False
    sentences = (await seeded_db.execute(select(Sentence).where(Sentence.is_target))).scalars().all()
    assert {sentence.note_id for sentence in sentences} == {"note-1-1", "note-4-1"}
    assert any(sentence.is_negated for sentence in sentences)
    job = (await seeded_db.execute(select(NlpJob))).scalar_one()
    assert job.status == NlpJobStatus.COMPLETED