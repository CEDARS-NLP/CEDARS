"""Tests for the ported nlpprocessor query parser (pure) and the end-to-end flow."""

from app.nlp.processor import get_lemma_dict, get_negated_dict, get_regex_dict, query_to_patterns


def test_single_lemma_token():
    assert query_to_patterns("dvt") == [[{"LEMMA": "dvt"}]]


def test_and_group():
    assert query_to_patterns("clot AND leg") == [[{"LEMMA": "clot"}, {"LEMMA": "leg"}]]


def test_or_groups():
    assert query_to_patterns("dvt OR embolus") == [
        [{"LEMMA": "dvt"}],
        [{"LEMMA": "embolus"}],
    ]


def test_wildcard_uses_regex():
    assert query_to_patterns("clot*") == [[{"TEXT": {"REGEX": r"\bclot.*\b"}}]]


def test_negation_operator():
    assert query_to_patterns("!suspected") == [[{"LOWER": "suspected", "OP": "!"}]]


def test_helper_builders():
    assert get_lemma_dict("x") == {"LEMMA": "x"}
    assert get_negated_dict("x") == {"LOWER": "x", "OP": "!"}
    assert get_regex_dict("a?b") == {"TEXT": {"REGEX": r"\ba.b\b"}}
