"""Tests for NLP engine: query parsing, sentence splitting, negation detection."""

import pytest

from app.nlp.engine import (
    _detect_negation_proximity,
    get_nlp,
    parse_query,
    process_note,
)
from app.nlp.models import NlpJobStatus, SearchQuery, Sentence


class TestQueryParser:
    @pytest.mark.parametrize(
        ("query", "text"),
        [
            (r"\!DVT", "!DVT"),
            (r"DVT\!", "DVT!"),
            (r"DVT\!\!", "DVT!!"),
            (r"DVT\!PE", "DVT!PE"),
            (r"path\\name", r"path\name"),
            (r"path\name", r"path\name"),
            ("path\\", "path\\"),
            (r"path\\\!", "path\\!"),
        ],
    )
    def test_literal_escapes(self, query, text):
        condition = parse_query(query)[0][0]
        assert condition["text"] == text
        assert condition["negated"] is False

    def test_even_backslashes_leave_exclusion_operator(self):
        groups = parse_query(r"DVT\\ AND !suspected")
        assert groups[0][0]["text"] == "DVT\\"
        assert groups[0][1]["negated"] is True
        with pytest.raises(ValueError):
            parse_query(r"DVT\\!suspected")

    def test_escaped_punctuation_with_boolean_and_wildcard(self):
        groups = parse_query(r"(DVT\! OR embol*) AND !suspected")
        assert len(groups) == 2
        assert groups[0][0]["text"] == "DVT!"
        assert "REGEX" in str(groups[1][0]["pattern"])
        assert all(group[1]["negated"] for group in groups)

    @pytest.mark.parametrize(
        ("query", "message"),
        [
            ("x" * 10001, "too long"),
            (" OR ".join("DVT" for _ in range(257)), "too complex"),
            ("(" * 34 + "DVT" + ")" * 34, "too deep"),
        ],
        ids=["length", "tokens", "nesting"],
    )
    def test_parser_limits_remain_bounded(self, query, message):
        with pytest.raises(ValueError, match=message):
            parse_query(query)

    @pytest.mark.parametrize("query", ["DVT AND", "(DVT", "DVT)", "()", "DVT OR OR PE"])
    def test_invalid_syntax_rejected(self, query):
        with pytest.raises(ValueError):
            parse_query(query)

    def test_expansion_is_bounded(self):
        query = " AND ".join("(DVT OR PE)" for _ in range(8))
        with pytest.raises(ValueError, match="too complex"):
            parse_query(query)

    def test_simple_term(self):
        groups = parse_query("DVT")
        assert len(groups) == 1
        assert len(groups[0]) == 1
        assert groups[0][0]["text"] == "DVT"
        assert groups[0][0]["negated"] is False

    def test_or_terms(self):
        groups = parse_query("DVT OR embolus OR PE")
        assert len(groups) == 3
        assert groups[0][0]["text"] == "DVT"
        assert groups[1][0]["text"] == "embolus"
        assert groups[2][0]["text"] == "PE"

    def test_and_terms(self):
        groups = parse_query("troponin AND elevated")
        assert len(groups) == 1
        assert len(groups[0]) == 2
        assert groups[0][0]["text"] == "troponin"
        assert groups[0][1]["text"] == "elevated"

    def test_negation_prefix(self):
        groups = parse_query("MI AND !suspected")
        assert len(groups) == 1
        assert groups[0][0]["negated"] is False
        assert groups[0][1]["negated"] is True
        assert groups[0][1]["text"] == "suspected"

    def test_wildcard_pattern(self):
        groups = parse_query("embol*")
        pattern = groups[0][0]["pattern"]
        assert "REGEX" in str(pattern)

    def test_empty_query(self):
        assert parse_query("") == []
        assert parse_query("  ") == []

    def test_parenthesized_groups(self):
        groups = parse_query("(DVT OR PE) AND !suspected")
        assert len(groups) == 2
        assert all(len(group) == 2 and group[1]["negated"] for group in groups)


class TestProcessNote:
    @pytest.mark.parametrize(
        ("query", "text", "matched"),
        [
            (r"DVT\!", "Confirmed DVT!", "DVT!"),
            (r"DVT\!\!", "Confirmed DVT!!", "DVT!!"),
            (r"path\\name", r"Confirmed path\name.", r"path\name"),
        ],
    )
    def test_literal_punctuation_matches(self, query, text, matched):
        sentences = process_note(text, parse_query(query))
        assert sentences[0]["is_target"] is True
        assert sentences[0]["matched_tokens"] == [matched]
        match = sentences[0]["matches"][0]
        assert text[match["note_start_index"]:match["note_end_index"]] == matched

    def test_negated_conjunction_preserves_group_truth(self):
        query = "DVT AND !(suspected AND family history)"
        sentences = process_note(
            "Suspected DVT. Family history of DVT. Suspected DVT with family history.",
            parse_query(query),
        )
        assert [sentence["is_target"] for sentence in sentences] == [True, True, False]

    def test_phrase_negation_and_question_wildcard(self):
        sentences = process_note("No chest pain. Confirmed DVT.", parse_query("chest pain OR D?T"))
        assert sentences[0]["is_target"] and sentences[0]["is_negated"]
        assert sentences[1]["is_target"] and not sentences[1]["is_negated"]

    def test_and_requires_every_term(self):
        sentences = process_note(
            "Troponin measured. Troponin elevated.", parse_query("troponin AND elevated")
        )
        assert [sentence["is_target"] for sentence in sentences] == [False, True]

    def test_grouped_exclusions_are_sentence_scoped(self):
        query = "((DVT) OR (thromb*)) AND !((suspected) OR (family history))"
        sentences = process_note(
            "Suspected DVT. Confirmed thrombosis. Family history of DVT. Confirmed DVT.",
            parse_query(query),
        )
        assert [sentence["is_target"] for sentence in sentences] == [False, True, False, True]
        assert sentences[0]["matches"] == []
        assert sentences[2]["matched_tokens"] == []

    def test_phrase_matches_and_positive_spans(self):
        text = "Chest pain with elevated troponin. Chest discomfort."
        sentences = process_note(text, parse_query("chest pain AND elevated troponin"))
        assert [sentence["is_target"] for sentence in sentences] == [True, False]
        assert sentences[0]["matched_tokens"] == ["Chest pain", "elevated troponin"]
        for match in sentences[0]["matches"]:
            assert text[match["note_start_index"]:match["note_end_index"]] == match["token"]

    def test_exclusion_does_not_leak_between_or_branches(self):
        sentences = process_note("Suspected DVT.", parse_query("(DVT AND !suspected) OR DVT"))
        assert sentences[0]["is_target"] is True

    def test_splits_sentences(self):
        text = "Patient has chest pain. No fever noted. Labs are pending."
        sentences = process_note(text, [])
        assert len(sentences) == 3
        assert sentences[0]["text"] == "Patient has chest pain."
        assert sentences[0]["sentence_number"] == 0
        assert sentences[0]["is_target"] is False

    def test_keyword_match(self):
        text = "Patient presents with chest pain. Troponin was elevated. No fever."
        groups = parse_query("troponin")
        sentences = process_note(text, groups)
        targets = [s for s in sentences if s["is_target"]]
        assert len(targets) == 1
        assert "Troponin" in targets[0]["text"] or "troponin" in targets[0]["text"].lower()

    def test_no_match(self):
        text = "Patient has a headache. Prescribed ibuprofen."
        groups = parse_query("troponin")
        sentences = process_note(text, groups)
        targets = [s for s in sentences if s["is_target"]]
        assert len(targets) == 0

    def test_negation_detected(self):
        text = "No evidence of DVT was found."
        groups = parse_query("DVT")
        sentences = process_note(text, groups)
        targets = [s for s in sentences if s["is_target"]]
        assert len(targets) == 1
        assert targets[0]["is_negated"] is True

    def test_non_negated_match(self):
        text = "Patient diagnosed with DVT in left leg."
        groups = parse_query("DVT")
        sentences = process_note(text, groups)
        targets = [s for s in sentences if s["is_target"]]
        assert len(targets) == 1
        assert targets[0]["is_negated"] is False

    def test_wildcard_match(self):
        text = "Patient had an embolism. Also emboli in lungs."
        groups = parse_query("embol*")
        sentences = process_note(text, groups)
        targets = [s for s in sentences if s["is_target"]]
        assert len(targets) >= 1

    def test_positions_tracked(self):
        text = "First sentence. Second sentence."
        sentences = process_note(text, [])
        assert sentences[0]["start_pos"] == 0
        assert sentences[0]["end_pos"] > 0
        assert sentences[1]["start_pos"] > sentences[0]["start_pos"]

    def test_empty_text(self):
        sentences = process_note("", [])
        assert sentences == []


class TestNegationProximity:
    def test_negation_before_token(self):
        nlp = get_nlp()
        doc = nlp("No evidence of MI was found.")
        sent = list(doc.sents)[0]
        assert _detect_negation_proximity(sent, ["MI"]) is True

    def test_no_negation(self):
        nlp = get_nlp()
        doc = nlp("Patient has confirmed MI.")
        sent = list(doc.sents)[0]
        assert _detect_negation_proximity(sent, ["MI"]) is False

    def test_denied_negation(self):
        nlp = get_nlp()
        doc = nlp("Patient denies chest pain.")
        sent = list(doc.sents)[0]
        assert _detect_negation_proximity(sent, ["chest"]) is True


class TestModels:
    def test_sentence_defaults(self):
        s = Sentence(
            note_id="n1", project_id="p1", sentence_number=0,
            text="Test sentence.", start_pos=0, end_pos=14,
        )
        assert s.is_negated is False
        assert s.is_target is False
        assert s.matched_tokens == []

    def test_search_query_defaults(self):
        sq = SearchQuery(project_id="p1", query="troponin")
        assert sq.is_active is True
        assert sq.nlp_apply is True
        assert sq.hide_duplicates is True

    def test_job_status_values(self):
        assert NlpJobStatus.PENDING.value == "pending"
        assert NlpJobStatus.COMPLETED.value == "completed"
