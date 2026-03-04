"""NLP engine: spaCy sentence splitting, query matching, negation detection.

Configurable pipeline:
- Default: spacy.blank("en") + sentencizer (no model download needed)
- Optional: scispaCy clinical model (e.g. en_core_sci_sm, en_core_sci_lg)
  for dependency-based negation and better biomedical tokenization.

Set CEDARS_SPACY_MODEL env var to use a trained model.
Install models with: pip install <model-url>  (see scispaCy docs)
"""

import logging
import re

import spacy
from spacy.matcher import Matcher

logger = logging.getLogger(__name__)

# Negation words from v1 (NegEx-style)
NEGATION_WORDS = frozenset({
    "no", "not", "never", "nobody", "nothing", "neither", "barely",
    "hardly", "scarcely", "seldom", "rarely", "without", "deny",
    "denies", "denied", "negative", "absent", "none", "nor",
})

_nlp = None
_has_parser = False  # whether dependency parsing is available


def get_nlp():
    """Get or create the spaCy NLP pipeline (lazy loaded).

    Tries to load a configured model, falls back to blank English.
    """
    global _nlp, _has_parser
    if _nlp is not None:
        return _nlp

    from app.config import settings

    model_name = settings.spacy_model.strip()

    if model_name:
        try:
            _nlp = spacy.load(model_name)
            _has_parser = _nlp.has_pipe("parser") or _nlp.has_pipe("senter")
            logger.info("Loaded spaCy model '%s' (parser=%s)", model_name, _has_parser)
            return _nlp
        except OSError:
            logger.warning(
                "spaCy model '%s' not found. Install it with: "
                "python -m spacy download %s  — Falling back to blank model.",
                model_name, model_name,
            )

    # Default: blank English with sentencizer (no model download needed)
    _nlp = spacy.blank("en")
    _nlp.add_pipe("sentencizer")
    _has_parser = False
    logger.info(
        "Loaded blank spaCy model. Set CEDARS_SPACY_MODEL to a scispaCy model "
        "(e.g. en_core_sci_sm) for dependency-based negation detection."
    )

    return _nlp


def has_parser() -> bool:
    """Check if the loaded model supports dependency parsing."""
    get_nlp()  # ensure loaded
    return _has_parser


def get_pipeline_info() -> dict:
    """Return info about the current NLP pipeline for diagnostics."""
    nlp = get_nlp()
    return {
        "model_name": nlp.meta.get("name", "blank"),
        "model_version": nlp.meta.get("version", ""),
        "pipes": nlp.pipe_names,
        "has_parser": _has_parser,
        "has_lemmatizer": nlp.has_pipe("lemmatizer"),
    }


# ── Query parser ─────────────────────────────────────────────────


def parse_query(query_str: str) -> list[list[dict]]:
    """Parse CEDARS query syntax into spaCy Matcher-compatible patterns.

    Query syntax:
        OR groups separated by OR
        AND conditions within a group
        ! prefix for negation
        * and ? wildcards

    Example: ``(DVT OR embolus) AND !suspected``

    Returns a list of OR groups, each group is a list of AND conditions.
    Each condition is a dict with:
        - ``pattern``: spaCy Matcher pattern (list of dicts)
        - ``negated``: bool (if prefixed with !)
    """
    query_str = query_str.strip()
    if not query_str:
        return []

    # Remove outer parentheses
    query_str = re.sub(r"^\(|\)$", "", query_str.strip())

    # Split by OR (case-insensitive, word boundary)
    or_groups = re.split(r"\s+OR\s+", query_str, flags=re.IGNORECASE)

    result = []
    for group in or_groups:
        group = group.strip().strip("()")
        # Split by AND
        and_terms = re.split(r"\s+AND\s+", group, flags=re.IGNORECASE)

        conditions = []
        for term in and_terms:
            term = term.strip()
            negated = term.startswith("!")
            if negated:
                term = term[1:].strip()

            pattern = _term_to_pattern(term)
            conditions.append({"pattern": pattern, "negated": negated, "text": term})

        result.append(conditions)

    return result


def _term_to_pattern(term: str) -> list[dict]:
    """Convert a single search term to a spaCy Matcher pattern."""
    if "*" in term or "?" in term:
        # Wildcard → regex on TEXT (case-insensitive)
        regex = term.replace("*", ".*").replace("?", ".")
        regex = rf"(?i)^{regex}$"
        return [{"TEXT": {"REGEX": regex}}]

    # Use LOWER for case-insensitive exact matching.
    # With a lemmatizer, LEMMA match would handle morphological variants
    # (embolus → emboli), but LOWER works reliably with or without one.
    return [{"LOWER": term.lower()}]


# ── Sentence processing ─────────────────────────────────────────


def process_note(note_text: str, query_groups: list[list[dict]]) -> list[dict]:
    """Split a note into sentences, match against query, detect negation.

    Returns a list of sentence dicts:
        {
            "sentence_number": int,
            "text": str,
            "start_pos": int,
            "end_pos": int,
            "is_target": bool,
            "is_negated": bool,
            "matched_tokens": [str, ...],
        }
    """
    nlp = get_nlp()
    doc = nlp(note_text)

    matcher = Matcher(nlp.vocab)
    # Add all query patterns to matcher
    pattern_meta: list[tuple[str, bool]] = []  # (term_text, is_negation_condition)
    for g_idx, group in enumerate(query_groups):
        for c_idx, condition in enumerate(group):
            name = f"q_{g_idx}_{c_idx}"
            matcher.add(name, [condition["pattern"]])
            pattern_meta.append((condition["text"], condition["negated"]))

    sentences = []
    for sent_idx, sent in enumerate(doc.sents):
        sent_text = sent.text.strip()
        if not sent_text:
            continue

        # Run matcher on this sentence span
        matches = matcher(sent.as_doc()) if query_groups else []
        matched_tokens = []
        has_positive_match = False
        has_negation_violation = False

        for match_id, start, end in matches:
            rule_name = nlp.vocab.strings[match_id]
            parts = rule_name.split("_")
            if len(parts) == 3:
                g_idx = int(parts[1])
                c_idx = int(parts[2])
                meta_idx = sum(len(query_groups[i]) for i in range(g_idx)) + c_idx
                if meta_idx < len(pattern_meta):
                    _term_text, is_negated_condition = pattern_meta[meta_idx]
                    sent_doc = sent.as_doc()
                    token_text = sent_doc[start:end].text
                    if is_negated_condition:
                        has_negation_violation = True
                    else:
                        matched_tokens.append(token_text)
                        has_positive_match = True

        is_target = has_positive_match and not has_negation_violation

        # Negation detection on matched tokens
        is_negated = False
        if is_target:
            is_negated = _detect_negation(sent, matched_tokens)

        sentences.append({
            "sentence_number": sent_idx,
            "text": sent_text,
            "start_pos": sent.start_char,
            "end_pos": sent.end_char,
            "is_target": is_target,
            "is_negated": is_negated,
            "matched_tokens": matched_tokens if is_target else [],
        })

    return sentences


# ── Negation detection ───────────────────────────────────────────


def _detect_negation(sent_span, matched_tokens: list[str]) -> bool:
    """Check if matched tokens in a sentence are negated.

    Strategy depends on pipeline capabilities:
    - With parser: dependency-based (dep_=="neg", ancestor/child analysis)
    - Without parser: word proximity window (NegEx-style)

    Both strategies use the NEGATION_WORDS list.
    """
    if _has_parser:
        return _detect_negation_dep(sent_span, matched_tokens)
    return _detect_negation_proximity(sent_span, matched_tokens)


def _detect_negation_dep(sent_span, matched_tokens: list[str]) -> bool:
    """Dependency-based negation detection (requires trained model)."""
    matched_lower = {t.lower() for t in matched_tokens}

    for token in sent_span:
        if token.text.lower() not in matched_lower:
            continue

        # Direct negation dependency
        if token.dep_ == "neg":
            return True

        # Check ancestors for negation
        for ancestor in token.ancestors:
            if ancestor.dep_ == "neg" or ancestor.text.lower() in NEGATION_WORDS:
                return True

        # Check children for negation
        for child in token.children:
            if child.dep_ == "neg" or child.text.lower() in NEGATION_WORDS:
                return True

    return False


def _detect_negation_proximity(sent_span, matched_tokens: list[str]) -> bool:
    """Word-proximity negation detection (NegEx-style, no parser needed).

    Checks a window of tokens before each matched token for negation cues.
    Window size of 5 tokens is the standard NegEx heuristic.
    """
    matched_lower = {t.lower() for t in matched_tokens}
    window_size = 5

    for token in sent_span:
        if token.text.lower() not in matched_lower:
            continue

        # Check preceding tokens within window
        local_idx = token.i - sent_span.start
        start = max(0, local_idx - window_size)
        for i in range(start, local_idx):
            if sent_span[i].text.lower() in NEGATION_WORDS:
                return True

    return False
