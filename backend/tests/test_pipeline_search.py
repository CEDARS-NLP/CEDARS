"""Tests for deterministic note search engine."""

from dataclasses import dataclass

import pytest


@dataclass
class FakeNote:
    id: str
    text: str


class TestNoteSearch:
    def test_keyword_search_finds_matches(self):
        from app.pipeline.search import search_patient_notes

        notes = [
            FakeNote(id="n1", text="Patient has troponin elevation and chest pain."),
            FakeNote(id="n2", text="No significant findings today."),
        ]
        results = search_patient_notes(
            notes, keywords=["troponin"], regex_patterns=[], exclusion_patterns=[],
        )
        assert len(results) == 1
        assert results[0].note_id == "n1"
        assert "troponin" in results[0].matched_text.lower()

    def test_keyword_case_insensitive(self):
        from app.pipeline.search import search_patient_notes

        notes = [FakeNote(id="n1", text="TROPONIN level elevated.")]
        results = search_patient_notes(
            notes, keywords=["troponin"], regex_patterns=[], exclusion_patterns=[],
        )
        assert len(results) == 1

    def test_regex_search_finds_patterns(self):
        from app.pipeline.search import search_patient_notes

        notes = [FakeNote(id="n1", text="Troponin I level: 2.4 ng/mL, elevated.")]
        results = search_patient_notes(
            notes, keywords=[], regex_patterns=[r"troponin.*?(\d+\.?\d*)\s*ng/mL"],
            exclusion_patterns=[],
        )
        assert len(results) == 1

    def test_exclusion_patterns_filter_matches(self):
        from app.pipeline.search import search_patient_notes

        notes = [
            FakeNote(id="n1", text="Family history of MI."),
            FakeNote(id="n2", text="Confirmed MI with troponin elevation."),
        ]
        results = search_patient_notes(
            notes, keywords=["MI"], regex_patterns=[], exclusion_patterns=["family history"],
        )
        assert len(results) == 1
        assert results[0].note_id == "n2"

    def test_regex_timeout_protection(self):
        """Catastrophic backtracking should not hang — re2 handles this safely."""
        from app.pipeline.search import search_patient_notes

        notes = [FakeNote(id="n1", text="a" * 10000)]
        results = search_patient_notes(
            notes, keywords=[], regex_patterns=[r"(a+)+b"], exclusion_patterns=[],
        )
        assert len(results) == 0

    def test_no_matches_returns_empty(self):
        from app.pipeline.search import search_patient_notes

        notes = [FakeNote(id="n1", text="Normal labs, no issues.")]
        results = search_patient_notes(
            notes, keywords=["troponin"], regex_patterns=[], exclusion_patterns=[],
        )
        assert len(results) == 0

    def test_multiple_match_sources(self):
        """A note can match via both keyword and regex."""
        from app.pipeline.search import search_patient_notes

        notes = [FakeNote(id="n1", text="Troponin elevated at 5.2 ng/mL")]
        results = search_patient_notes(
            notes, keywords=["troponin"], regex_patterns=[r"\d+\.\d+\s*ng/mL"],
            exclusion_patterns=[],
        )
        # Should have matches from both sources
        assert len(results) >= 1
        sources = {r.match_source for r in results}
        assert "keyword" in sources
        assert "regex" in sources

    def test_invalid_re2_pattern_skipped(self):
        """Patterns that re2 can't compile should be skipped, not crash."""
        from app.pipeline.search import search_patient_notes

        notes = [FakeNote(id="n1", text="troponin elevated")]
        # re2 doesn't support backreferences — this should be skipped gracefully
        results = search_patient_notes(
            notes, keywords=["troponin"], regex_patterns=[r"(\w)\1+"],
            exclusion_patterns=[],
        )
        # Should still get keyword match, regex pattern skipped
        assert len(results) >= 1

    def test_empty_notes_returns_empty(self):
        from app.pipeline.search import search_patient_notes

        results = search_patient_notes(
            [], keywords=["troponin"], regex_patterns=[], exclusion_patterns=[],
        )
        assert results == []

    def test_search_match_fields(self):
        """Verify SearchMatch dataclass has expected fields."""
        from app.pipeline.search import SearchMatch, search_patient_notes

        notes = [FakeNote(id="n1", text="Patient has troponin elevation.")]
        results = search_patient_notes(
            notes, keywords=["troponin"], regex_patterns=[], exclusion_patterns=[],
        )
        assert len(results) == 1
        m = results[0]
        assert isinstance(m, SearchMatch)
        assert m.note_id == "n1"
        assert m.match_source == "keyword"
        assert m.match_pattern == "troponin"
        assert m.start_pos >= 0
        assert m.end_pos > m.start_pos
