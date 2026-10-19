"""Raw evaluation input and canonical query normalization regressions."""

import pytest

from app.evaluation.query_expression import normalize_queries
from app.nlp.engine import parse_query, process_note


@pytest.mark.parametrize("query", ["!DVT", "DVT!", "DVT!!", "DVT!PE", "!"])
def test_raw_include_exclamation_is_literal(query):
    rows = [{"query": query, "type": "include"}]
    normalized = normalize_queries(rows, raw_input=True)
    condition = parse_query(normalized[0]["query"])[0][0]
    assert condition["text"] == query
    assert condition["negated"] is False
    assert rows == [{"query": query, "type": "include"}]


@pytest.mark.parametrize("query", ["!suspected", "suspected!", "!!", r"path\!"])
def test_raw_exclude_exclamation_is_literal_with_generated_negation(query):
    normalized = normalize_queries(
        [{"query": "DVT"}, {"query": query, "type": "exclude"}], raw_input=True
    )
    conditions = parse_query(normalized[0]["query"])[0]
    assert [(condition["text"], condition["negated"]) for condition in conditions] == [
        ("DVT", False), (query, True)
    ]


@pytest.mark.parametrize("query", [r"path\!", r"path\\!", r"path\name", "path\\"])
def test_raw_backslashes_are_literal(query):
    normalized = normalize_queries([{"query": query}], raw_input=True)
    assert parse_query(normalized[0]["query"])[0][0]["text"] == query
    assert normalize_queries(normalized) == normalized


def test_canonical_normalization_is_idempotent():
    normalized = normalize_queries(
        [
            {"query": "DVT!"},
            {"query": "embol*"},
            {"query": "!suspected", "type": "exclude"},
            {"query": "family history", "type": "exclude"},
        ],
        raw_input=True,
    )
    assert normalize_queries(normalized) == normalized
    assert normalize_queries(normalized, raw_input=False) == normalized


def test_legacy_canonical_exclusion_is_preserved():
    rows = [{"query": "(DVT OR embol*) AND !suspected", "type": "include"}]
    assert normalize_queries(rows) == rows
    sentences = process_note(
        "Suspected DVT. Confirmed DVT. Confirmed embolism.", parse_query(rows[0]["query"])
    )
    assert [sentence["is_target"] for sentence in sentences] == [False, True, True]


def test_raw_include_and_exclude_match_literal_punctuation():
    normalized = normalize_queries(
        [{"query": "DVT!"}, {"query": "suspected!", "type": "exclude"}], raw_input=True
    )
    groups = parse_query(normalized[0]["query"])
    assert process_note("DVT!", groups)[0]["is_target"] is True
    assert process_note("DVT.", groups)[0]["is_target"] is False
    assert process_note("Suspected DVT!", groups)[0]["is_target"] is True
    assert process_note("Suspected! DVT!", groups)[1]["is_target"] is True
    excluded = normalize_queries(
        [{"query": "DVT"}, {"query": "suspected!", "type": "exclude"}], raw_input=True
    )
    excluded_groups = parse_query(excluded[0]["query"])
    assert process_note("DVT suspected!", excluded_groups)[0]["is_target"] is False
    assert process_note("DVT suspected.", excluded_groups)[0]["is_target"] is True


def test_raw_mode_preserves_boolean_and_wildcard_syntax():
    normalized = normalize_queries(
        [{"query": "(DVT OR embol*) AND confirmed"}], raw_input=True
    )
    sentences = process_note(
        "Confirmed DVT. Confirmed embolism. Suspected DVT.",
        parse_query(normalized[0]["query"]),
    )
    assert [sentence["is_target"] for sentence in sentences] == [True, True, False]
