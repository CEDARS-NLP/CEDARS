"""Behavioral contracts for versioned sentence-level Boolean queries."""

import pytest

from app.nlp.engine import parse_query, process_note
from app.nlp.query_expression import compile_query_rows, parse_expression, select_note_sentences


def row(query, query_type="include"):
    return {"query": query, "query_type": query_type}


@pytest.mark.parametrize(
    ("expression", "text", "expected"),
    [
        ("DVT AND confirmed", "DVT present.", False),
        ("DVT AND confirmed", "Confirmed DVT.", True),
        ("(DVT OR PE) AND !suspected", "Suspected DVT.", False),
        ("(DVT OR PE) AND NOT suspected", "Confirmed PE.", True),
        ("DVT OR PE AND confirmed", "DVT present.", True),
        ("(DVT AND confirmed) OR (PE AND acute)", "DVT acute.", False),
        ("(DVT AND confirmed) OR (PE AND acute)", "Acute PE.", True),
        ("DVT AND NOT (suspected OR historical)", "Historical DVT.", False),
        ("DVT AND NOT NOT confirmed", "Confirmed DVT.", True),
        ("deep vein thromb*", "Deep vein thrombosis.", True),
        ('"deep vein thrombosis"', "Deep vein thrombosis.", True),
        ("emboli?m", "Embolism.", True),
        ("embol*", "Microembolism.", False),
    ],
)
def test_boolean_truth(expression, text, expected):
    assert bool(select_note_sentences(text, [row(expression)])) is expected


def test_canonical_and_sentence_exclusions():
    rows = [row("DVT"), row("thromb*"), row("suspected", "exclude"),
            row("family history", "exclude")]
    assert compile_query_rows(rows) == (
        "((DVT) OR (thromb*)) AND NOT ((suspected) OR (family history))"
    )
    text = "Suspected DVT. Confirmed thrombosis. Family history of DVT."
    selected = select_note_sentences(text, rows)
    assert [sentence["text"] for sentence in selected] == ["Confirmed thrombosis."]
    assert selected[0]["sentence_number"] == 1
    assert selected[0]["source_query_indices"] == [1]


def test_deduplicated_hits_and_note_offsets():
    text = "Other note. Deep vein thrombosis diagnosed."
    selected = select_note_sentences(text, [row("deep vein thromb*"), row("deep vein thromb*")])
    assert len(selected) == 1
    sentence = selected[0]
    assert sentence["source_query_indices"] == [0, 1]
    assert sentence["is_target"] is True
    assert sentence["is_negated"] is False
    assert sentence["matched_tokens"] == ["Deep vein thrombosis"]
    assert len(sentence["matches"]) == 1
    match = sentence["matches"][0]
    assert text[match["note_start_index"]:match["note_end_index"]] == match["token"]
    assert match["source_query_indices"] == [0, 1]


def test_global_negation_and_mixed_occurrences():
    rows = [row("DVT")]
    assert select_note_sentences("No DVT.", rows) == []
    assert select_note_sentences("No DVT.", rows, False)[0]["is_negated"] is True
    selected = select_note_sentences("No DVT but later imaging confirmed DVT.", rows)
    assert selected[0]["matched_tokens"] == ["DVT"]
    assert selected[0]["matches"][0]["note_start_index"] > 10
    assert select_note_sentences("No deep vein thrombosis.", [row("deep vein thrombosis")]) == []


def test_exclusion_does_not_use_clinical_negation_filter():
    assert select_note_sentences("DVT with no suspected PE.",
                                 [row("DVT"), row("suspected", "exclude")], False) == []


def test_failed_or_branch_does_not_contribute_spans():
    selected = select_note_sentences("DVT and acute PE.",
                                     [row("(DVT AND confirmed) OR (PE AND acute)")])
    assert selected[0]["matched_tokens"] == ["acute", "PE"]


def test_grouped_exclude_and_active_parity():
    rows = [row("DVT"), row("suspected AND acute", "exclude")]
    text = "Suspected DVT. Acute suspected DVT. Confirmed DVT."
    selected = select_note_sentences(text, rows)
    assert len(selected) == 2
    active = process_note(text, parse_expression(compile_query_rows(rows)))
    assert [sentence["text"] for sentence in active if sentence["is_target"]] == [
        sentence["text"] for sentence in selected
    ]


def test_nested_not_exclusion_uses_raw_matches_in_both_paths():
    rows = [row("DVT"), row("NOT suspected", "exclude")]
    text = "DVT with no suspected PE. Confirmed DVT."
    selected = select_note_sentences(text, rows)
    active = process_note(text, parse_expression(compile_query_rows(rows)))
    assert [sentence["text"] for sentence in selected] == ["DVT with no suspected PE."]
    assert [sentence["text"] for sentence in active if sentence["is_target"]] == [
        sentence["text"] for sentence in selected
    ]


def test_reserved_words_quoted_and_case_insensitive():
    assert select_note_sentences("AND documented.", [row('"AND"')])
    assert select_note_sentences("DVT confirmed.", [row("dvt aNd confirmed")])
    assert select_note_sentences("NOTABLE finding.", [row("notable")])


def test_phrase_does_not_cross_sentence_boundary():
    assert select_note_sentences("Deep vein. Thrombosis confirmed.",
                                 [row("deep vein thrombosis")]) == []


def test_marker_dispatch_and_empty_note():
    assert select_note_sentences("", [row("DVT")]) == []
    expression = parse_query("cedars:v2:DVT AND confirmed")
    assert process_note("DVT present.", expression)[0]["is_target"] is False


def test_nested_compilation_preserves_not_and_literal_marker_terms():
    compiled = compile_query_rows([row("DVT"), row("suspected", "exclude")])
    nested = compile_query_rows([row(compiled)])
    assert "NOT" in nested
    assert select_note_sentences("Suspected DVT.", [row(nested)]) == []
    assert select_note_sentences("cedarswildstar.", [row("cedarswildstar")])
    assert select_note_sentences("unrelated.", [row("cedarswildstar")]) == []


@pytest.mark.parametrize("expression", ["", "()", "DVT AND", "OR DVT", "DVT)",
                                        "(DVT", "DVT AND OR PE", "NOT DVT", "!DVT", '""'])
def test_invalid_expressions(expression):
    with pytest.raises(ValueError):
        parse_expression(expression)


@pytest.mark.parametrize("rows", [[], [row("DVT", "exclude")], [row("")],
                                 [row("DVT", "unknown")], [row("NOT DVT")]])
def test_invalid_rows(rows):
    with pytest.raises(ValueError):
        compile_query_rows(rows)


def test_bounded_input():
    for expression in ["(" * 40 + "DVT" + ")" * 40, "NOT " * 100 + "DVT", "x" * 20000]:
        with pytest.raises(ValueError):
            parse_expression(expression)


def test_explicit_dispatch_preserves_legacy():
    legacy = process_note("DVT present.", parse_query("DVT AND confirmed"))
    assert legacy[0]["is_target"] is True
    expression = parse_query("DVT AND confirmed", syntax_version=2)
    assert process_note("DVT present.", expression)[0]["is_target"] is False
    selected = select_note_sentences("Confirmed DVT.", [row("DVT AND confirmed")])
    active = process_note("Confirmed DVT.", expression)
    assert [sentence["text"] for sentence in active if sentence["is_target"]] == [
        sentence["text"] for sentence in selected
    ]
