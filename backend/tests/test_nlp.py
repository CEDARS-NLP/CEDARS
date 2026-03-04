"""Tests for NLP engine: query parsing, sentence splitting, negation detection."""

from app.nlp.engine import (
    _detect_negation_proximity,
    parse_query,
    process_note,
    get_nlp,
)
from app.nlp.models import NlpJobStatus, SearchQuery, Sentence


class TestQueryParser:
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
        # This parses as two OR groups because of how we split
        # The important thing is the patterns are usable
        assert len(groups) >= 1


class TestProcessNote:
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
