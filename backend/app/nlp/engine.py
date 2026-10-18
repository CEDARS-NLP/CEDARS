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
        Backslash escapes literal ! and backslash characters
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

    if len(query_str) > 10000:
        raise ValueError("Search query is too long")
    tokens = []
    term_parts = []
    for match in re.finditer(
        r"\\[\\!]|(\bOR\b|\bAND\b|[()!])|.", query_str, flags=re.IGNORECASE | re.DOTALL
    ):
        if match.group(1) is None:
            term_parts.append(match.group())
        else:
            term = "".join(term_parts).strip()
            if term:
                tokens.append(term)
            term_parts = []
            tokens.append(match.group())
    term = "".join(term_parts).strip()
    if term:
        tokens.append(term)
    if len(tokens) > 512:
        raise ValueError("Search query is too complex")
    position = 0

    def parse_expression(min_precedence=0, depth=0):
        nonlocal position
        if depth > 32:
            raise ValueError("Search query nesting is too deep")
        if position >= len(tokens):
            raise ValueError("Search query is missing a term")
        token = tokens[position]
        position += 1
        if token == "!":
            node = ("not", parse_expression(3, depth + 1))
        elif token == "(":
            node = parse_expression(0, depth + 1)
            if position >= len(tokens) or tokens[position] != ")":
                raise ValueError("Search query has unmatched parentheses")
            position += 1
        elif token.upper() in {"AND", "OR", ")"}:
            raise ValueError("Search query is missing a term")
        else:
            node = ("term", token)
        while position < len(tokens):
            operator = tokens[position].upper()
            precedence = {"OR": 1, "AND": 2}.get(operator, -1)
            if precedence < min_precedence:
                break
            position += 1
            node = (operator, node, parse_expression(precedence + 1, depth + 1))
        return node

    def expand(node, negated=False):
        operator = node[0]
        if operator == "term":
            term = re.sub(r"\\([\\!])", r"\1", node[1])
            return [[{"pattern": _term_to_pattern(term), "negated": negated, "text": term}]]
        if operator == "not":
            return expand(node[1], not negated)
        left = expand(node[1], negated)
        right = expand(node[2], negated)
        conjunction = (operator == "AND") != negated
        group_count = len(left) * len(right) if conjunction else len(left) + len(right)
        condition_count = (
            sum(map(len, left)) * len(right) + sum(map(len, right)) * len(left)
            if conjunction else sum(map(len, left)) + sum(map(len, right))
        )
        if group_count > 128 or condition_count > 1024:
            raise ValueError("Search query Boolean expansion is too complex")
        return [first + second for first in left for second in right] if conjunction else left + right

    expression = parse_expression()
    if position != len(tokens):
        raise ValueError("Search query has unexpected terms or parentheses")
    return expand(expression)


def _term_to_pattern(term: str) -> list[dict]:
    """Convert a single search term to a spaCy Matcher pattern."""
    if " " in term or not ("*" in term or "?" in term):
        pattern = []
        for word in term.split():
            if "*" in word or "?" in word:
                pattern.extend(_term_to_pattern(word))
            else:
                pattern.extend({"LOWER": token.lower_} for token in get_nlp().make_doc(word))
        return pattern
    if "*" in term or "?" in term:
        # Wildcard → regex on TEXT (case-insensitive)
        # Escape regex-special chars first, then convert our wildcards
        parts = re.split(r"(\*|\?)", term)
        regex = ""
        for part in parts:
            if part == "*":
                regex += ".*"
            elif part == "?":
                regex += "."
            else:
                regex += re.escape(part)
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
            "matches": [{"token": str, "note_start_index": int, "note_end_index": int}, ...],
        }
    """
    nlp = get_nlp()
    doc = nlp(note_text)

    matcher = Matcher(nlp.vocab)
    # Add all query patterns to matcher
    for g_idx, group in enumerate(query_groups):
        for c_idx, condition in enumerate(group):
            name = f"q_{g_idx}_{c_idx}"
            matcher.add(name, [condition["pattern"]])

    sentences = []
    for sent_idx, sent in enumerate(doc.sents):
        sent_text = sent.text.strip()
        if not sent_text:
            continue

        # Run matcher on this sentence span
        sent_doc = sent.as_doc() if query_groups else None
        matches = matcher(sent_doc) if query_groups else []
        matched_tokens = []
        match_spans: list[dict] = []
        condition_matches = {}
        for match_id, start, end in matches:
            rule_name = nlp.vocab.strings[match_id]
            parts = rule_name.split("_")
            condition_matches.setdefault((int(parts[1]), int(parts[2])), []).append((start, end))
        positive_spans = set()
        for group_index, group in enumerate(query_groups):
            if all(
                bool(condition_matches.get((group_index, condition_index))) != condition["negated"]
                for condition_index, condition in enumerate(group)
            ):
                for condition_index, condition in enumerate(group):
                    if not condition["negated"]:
                        positive_spans.update(condition_matches.get((group_index, condition_index), []))
        for start, end in sorted(positive_spans):
            token_span = sent_doc[start:end]
            token_start = sent.start_char + token_span.start_char
            matched_tokens.append(token_span.text)
            match_spans.append({
                "token": token_span.text,
                "note_start_index": token_start,
                "note_end_index": token_start + len(token_span.text),
            })
        is_target = bool(positive_spans)

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
            "matches": match_spans if is_target else [],
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
    matched_lower = {token.lower_ for text in matched_tokens for token in get_nlp().make_doc(text)}

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
    matched_lower = {token.lower_ for text in matched_tokens for token in get_nlp().make_doc(text)}
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
