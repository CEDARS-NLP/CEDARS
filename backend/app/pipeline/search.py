"""Deterministic note search engine for the pipeline.

Uses keyword matching and re2-based regex for safe, predictable search
without risk of catastrophic backtracking (Decision #33).
"""

import logging
import re
from dataclasses import dataclass
from typing import Protocol

import re2

logger = logging.getLogger(__name__)


class NoteProtocol(Protocol):
    """Minimal interface for a note object."""

    id: str
    text: str


@dataclass
class SearchMatch:
    """A single search match within a note."""

    note_id: str
    matched_text: str
    start_pos: int
    end_pos: int
    match_source: str  # "keyword" or "regex"
    match_pattern: str  # the pattern that matched


def _make_case_insensitive(pattern: str) -> str:
    """Prepend (?i) to make a pattern case-insensitive for re2."""
    if pattern.startswith("(?i)"):
        return pattern
    return f"(?i){pattern}"


def _keyword_matches(text: str, keywords: list[str]) -> list[SearchMatch]:
    """Find keyword matches using case-insensitive word-boundary search."""
    matches = []
    text_lower = text.lower()
    for kw in keywords:
        kw_lower = kw.lower()
        # Use simple find for multi-word phrases, regex word boundary for single words
        if " " in kw_lower:
            start = 0
            while True:
                idx = text_lower.find(kw_lower, start)
                if idx == -1:
                    break
                matches.append(SearchMatch(
                    note_id="",  # filled by caller
                    matched_text=text[idx:idx + len(kw)],
                    start_pos=idx,
                    end_pos=idx + len(kw),
                    match_source="keyword",
                    match_pattern=kw,
                ))
                start = idx + 1
        else:
            pattern = re.compile(r"\b" + re.escape(kw_lower) + r"\b", re.IGNORECASE)
            for m in pattern.finditer(text):
                matches.append(SearchMatch(
                    note_id="",
                    matched_text=m.group(),
                    start_pos=m.start(),
                    end_pos=m.end(),
                    match_source="keyword",
                    match_pattern=kw,
                ))
    return matches


def _regex_matches(text: str, patterns: list[str]) -> list[SearchMatch]:
    """Find regex matches using re2 (safe against catastrophic backtracking)."""
    matches = []
    for pat in patterns:
        try:
            compiled = re2.compile(_make_case_insensitive(pat))
        except re2.error:
            logger.warning("Skipping invalid re2 pattern: %s", pat)
            continue
        for m in compiled.finditer(text):
            matches.append(SearchMatch(
                note_id="",
                matched_text=m.group(),
                start_pos=m.start(),
                end_pos=m.end(),
                match_source="regex",
                match_pattern=pat,
            ))
    return matches


def _is_excluded(text: str, exclusion_patterns: list[str]) -> bool:
    """Check if the note text matches any exclusion pattern."""
    for pat in exclusion_patterns:
        try:
            if re2.search(_make_case_insensitive(pat), text):
                return True
        except re2.error:
            # Fall back to stdlib re for patterns re2 can't handle
            try:
                if re.search(pat, text, re.IGNORECASE):
                    return True
            except re.error:
                logger.warning("Skipping invalid exclusion pattern: %s", pat)
    return False


def search_patient_notes(
    notes: list,
    keywords: list[str],
    regex_patterns: list[str],
    exclusion_patterns: list[str],
) -> list[SearchMatch]:
    """Search notes using keywords and regex patterns, filtering by exclusions.

    Args:
        notes: Objects with .id and .text attributes.
        keywords: Case-insensitive keyword/phrase matches.
        regex_patterns: re2-compatible regex patterns.
        exclusion_patterns: Patterns that disqualify a note.

    Returns:
        List of SearchMatch objects for all matching notes.
    """
    all_matches: list[SearchMatch] = []

    for note in notes:
        text = note.text
        if not text or not text.strip():
            continue

        # Check exclusions first (early exit)
        if exclusion_patterns and _is_excluded(text, exclusion_patterns):
            continue

        note_matches: list[SearchMatch] = []
        note_matches.extend(_keyword_matches(text, keywords))
        note_matches.extend(_regex_matches(text, regex_patterns))

        # Set note_id on all matches
        for m in note_matches:
            m.note_id = note.id

        all_matches.extend(note_matches)

    return all_matches
