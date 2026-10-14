"""Version 2 Boolean queries, evaluated within each spaCy sentence.

Precedence is NOT/!, AND, OR. Adjacent unquoted words form a phrase;
double-quoted phrases may contain reserved words. Wildcards match within tokens.
Rows use ``query`` and ``query_type`` (include or exclude, default include).
Source query indices are zero-based indices into the original row list.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Any, cast

import re2
from lark import Lark, Token, Tree
from lark.exceptions import UnexpectedInput
from spacy.matcher import Matcher
from spacy.tokens import Span

MAX_EXPRESSION_LENGTH = 8192
MAX_TOKENS = 512
MAX_DEPTH = 32
MAX_ROWS = 64
SYNTAX_VERSION = 2
EXPRESSION_PREFIX = "cedars:v2:"

_GRAMMAR = r'''
?start: disjunction
?disjunction: conjunction (_OR conjunction)* -> disjunction
?conjunction: unary (_AND unary)* -> conjunction
?unary: _NOT unary -> negation
    | "(" disjunction ")" -> group
      | phrase
phrase: WORD+ | QUOTED
_OR.2: /(?i:OR)(?![\w*?])/
_AND.2: /(?i:AND)(?![\w*?])/
_NOT.2: /(?i:NOT)(?![\w*?])/ | "!"
WORD: /(?!(?i:OR|AND|NOT)(?![\w*?]))[^\s()!"\\]+/
QUOTED: /"(?:[^"\\\r\n]|\\["\\])*"/
%import common.WS
%ignore WS
'''
_PARSER = Lark(_GRAMMAR, parser="lalr", lexer="basic")


@dataclass(frozen=True)
class Expression:
    """Immutable AST adapter accepted by engine.process_note for v2 queries."""

    kind: str
    children: tuple[Expression, ...] = ()
    text: str = ""


def _from_tree(tree: Tree, depth: int = 0) -> Expression:
    if depth > MAX_DEPTH * 3:
        raise ValueError(f"Query nesting exceeds {MAX_DEPTH} levels")
    if tree.data == "phrase":
        first = cast(Token, tree.children[0])
        text = json.loads(str(first)) if first.type == "QUOTED" else " ".join(
            str(child) for child in tree.children
        )
        if not text.strip() or len(text) > 256 or not any(char.isalnum() for char in text):
            raise ValueError("Query terms must contain text and be at most 256 characters")
        return Expression("term", text=text)
    children = tuple(_from_tree(child, depth + 1) for child in tree.children)
    if tree.data not in ("negation", "group") and len(children) == 1:
        return children[0]
    return Expression(str(tree.data), children)


def _has_positive(expression: Expression, inverted: bool = False) -> bool:
    if expression.kind == "exclusion":
        return False
    if expression.kind == "term":
        return not inverted
    if expression.kind == "negation":
        return _has_positive(expression.children[0], not inverted)
    return any(_has_positive(child, inverted) for child in expression.children)


@lru_cache(maxsize=256)
def parse_expression(expression: str, *, require_positive: bool = True) -> Expression:
    """Parse bounded grammar; raise ValueError for invalid or exclusion-only input."""
    if not isinstance(expression, str) or not expression.strip():
        raise ValueError("Query expression must not be empty")
    if expression.startswith(EXPRESSION_PREFIX):
        expression = expression[len(EXPRESSION_PREFIX):]
    if len(expression) > MAX_EXPRESSION_LENGTH:
        raise ValueError(f"Query exceeds {MAX_EXPRESSION_LENGTH} characters")
    try:
        depth = 0
        unary_count = 0
        for index, token in enumerate(_PARSER.lex(expression)):
            if index >= MAX_TOKENS:
                raise ValueError(f"Query exceeds {MAX_TOKENS} syntax tokens")
            if token.type == "LPAR":
                depth += 1
            elif token.type == "RPAR":
                depth -= 1
            unary_count = unary_count + 1 if token.type == "_NOT" else 0
            if depth > MAX_DEPTH or unary_count > MAX_DEPTH:
                raise ValueError(f"Query nesting exceeds {MAX_DEPTH} levels")
        ast = _from_tree(_PARSER.parse(expression))
    except UnexpectedInput as error:
        raise ValueError(f"Invalid query at line {error.line}, column {error.column}") from error
    if (ast.kind == "conjunction" and len(ast.children) == 2
            and ast.children[0].kind == "group"
            and ast.children[1].kind == "negation"
            and ast.children[1].children[0].kind == "group"):
        includes, exclusion = ast.children
        ast = Expression("conjunction", (includes, Expression("exclusion", exclusion.children)))
    if require_positive and not _has_positive(ast):
        raise ValueError("Query requires at least one positive include term")
    return ast


def _render(expression: Expression) -> str:
    if expression.kind == "group":
        return _render(expression.children[0])
    if expression.kind == "term":
        if re.search(r'\b(?:OR|AND|NOT)\b|[()!"\\]', expression.text, re.IGNORECASE):
            return json.dumps(expression.text, ensure_ascii=False)
        return expression.text
    if expression.kind in ("negation", "exclusion"):
        return f"NOT ({_render(expression.children[0])})"
    operator = " OR " if expression.kind == "disjunction" else " AND "
    return operator.join(f"({_render(child)})" for child in expression.children)


def _parse_rows(rows: list[dict]) -> list[tuple[int, str, Expression]]:
    if not isinstance(rows, list) or not rows or len(rows) > MAX_ROWS:
        raise ValueError(f"Supply between 1 and {MAX_ROWS} query rows")
    parsed = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError(f"Query row {index} must be an object")
        kind = row.get("query_type", "include")
        if kind not in ("include", "exclude"):
            raise ValueError(f"Query row {index} must be include or exclude")
        query = row.get("query")
        if not isinstance(query, str):
            raise ValueError(f"Query row {index} requires query text")
        parsed.append((index, kind, parse_expression(query, require_positive=kind == "include")))
    if not any(kind == "include" for _, kind, _ in parsed):
        raise ValueError("At least one include row is required")
    return parsed


def compile_query_rows(rows: list[dict]) -> str:
    """Return canonical ((include) OR ...) AND NOT ((exclude) OR ...) text."""
    parsed = _parse_rows(rows)
    includes = " OR ".join(f"({_render(ast)})" for _, kind, ast in parsed if kind == "include")
    excludes = " OR ".join(f"({_render(ast)})" for _, kind, ast in parsed if kind == "exclude")
    compiled = f"({includes})"
    if excludes:
        compiled += f" AND NOT ({excludes})"
    parse_expression(compiled)
    return compiled


def _terms(expression: Expression) -> set[str]:
    if expression.kind == "term":
        return {expression.text}
    return set().union(*(_terms(child) for child in expression.children))


def _pattern(term: str, nlp, doc) -> list[dict]:
    star_marker, question_marker = "cedarswildstar", "cedarswildquestion"
    while star_marker in term.lower() or question_marker in term.lower():
        star_marker += "x"
        question_marker += "x"
    substituted = term.replace("*", star_marker).replace("?", question_marker)
    pattern = []
    for token in nlp.make_doc(substituted):
        if token.is_space:
            continue
        text = token.lower_.replace(star_marker, "*").replace(question_marker, "?")
        if "*" in text or "?" in text:
            regex = re.escape(text).replace(r"\*", ".*").replace(r"\?", ".")
            wildcard = re2.compile(f"^{regex}$")
            words = sorted({word.lower_ for word in doc if wildcard.fullmatch(word.lower_)})
            pattern.append({"LOWER": {"IN": words}})
        else:
            pattern.append({"LOWER": text})
    return pattern


def _span_negated(sent, span) -> bool:
    from app.nlp import engine

    if engine._has_parser:
        return engine._detect_negation_dep(sent, [token.text for token in span])
    local_start = span.start - sent.start
    return any(token.lower_ in engine.NEGATION_WORDS
               for token in sent[max(0, local_start - 5):local_start])


def _evaluate(ast: Expression, hits: dict, exclude_negated: bool, inverted: bool = False):
    if ast.kind == "group":
        return _evaluate(ast.children[0], hits, exclude_negated, inverted)
    if ast.kind == "exclusion":
        truth, _ = _evaluate(ast.children[0], hits, False)
        return truth if inverted else not truth, set()
    if ast.kind == "term":
        raw = hits.get(ast.text, [])
        if inverted:
            return not raw, set()
        retained = [index for index, negated in raw if not exclude_negated or not negated]
        return bool(retained), set(retained)
    if ast.kind == "negation":
        return _evaluate(ast.children[0], hits, exclude_negated, not inverted)
    results = [_evaluate(child, hits, exclude_negated, inverted) for child in ast.children]
    conjunction = (ast.kind == "conjunction") != inverted
    truth = all(result[0] for result in results) if conjunction else any(
        result[0] for result in results
    )
    spans = set().union(*(result[1] for result in results if result[0])) if truth else set()
    return truth, spans


def _process(note_text: str, parsed: list[tuple[int, str, Expression]],
             exclude_negated: bool, retained_only: bool) -> list[dict]:
    from app.nlp.engine import get_nlp

    nlp = get_nlp()
    doc = nlp(note_text)
    terms = sorted(set().union(*(_terms(ast) for _, _, ast in parsed)))
    matcher = Matcher(nlp.vocab)
    identifiers = {}
    for index, term in enumerate(terms):
        name = f"expression_{index}"
        matcher.add(name, [_pattern(term, nlp, doc)])
        identifiers[nlp.vocab.strings[name]] = term
    sentence_matches: dict[int, list[tuple[str, Span]]] = {}
    for match_id, start, end in matcher(doc):
        span = doc[start:end]
        sent = doc[start].sent
        if end > sent.end:
            continue
        sentence_matches.setdefault(sent.start, []).append((identifiers[match_id], span))
    result = []
    for sentence_number, sent in enumerate(doc.sents):
        if not sent.text.strip():
            continue
        spans: list[tuple[Span, bool]] = []
        hits: dict[str, list[tuple[int, bool]]] = {}
        for term, span in sentence_matches.get(sent.start, []):
            negated = _span_negated(sent, span)
            hits.setdefault(term, []).append((len(spans), negated))
            spans.append((span, negated))
        sources: dict[int, set[int]] = {}
        source_indices = []
        excluded = any(_evaluate(ast, hits, False)[0]
                       for _, kind, ast in parsed if kind == "exclude")
        if not excluded:
            for index, kind, ast in parsed:
                if kind != "include":
                    continue
                truth, selected = _evaluate(ast, hits, exclude_negated)
                if truth and selected:
                    source_indices.append(index)
                    for span_index in selected:
                        sources.setdefault(span_index, set()).add(index)
        matches: dict[tuple[int, int], dict[str, Any]] = {}
        for span_index, indices in sources.items():
            span, negated = spans[span_index]
            key = (span.start_char, span.end_char)
            match = matches.setdefault(key, {
                "token": span.text, "note_start_index": span.start_char,
                "note_end_index": span.end_char, "is_negated": negated,
                "source_query_indices": [],
            })
            match["source_query_indices"] = sorted(set(match["source_query_indices"]) | indices)
        ordered = [matches[key] for key in sorted(matches)]
        if retained_only and not ordered:
            continue
        result.append({
            "sentence_number": sentence_number, "text": sent.text.strip(),
            "start_pos": sent.start_char, "end_pos": sent.end_char,
            "is_target": bool(ordered), "is_negated": any(hit["is_negated"] for hit in ordered),
            "matched_tokens": [hit["token"] for hit in ordered], "matches": ordered,
            "source_query_indices": source_indices,
        })
    return result


def select_note_sentences(note_text: str, rows: list[dict],
                          exclude_negated: bool = True) -> list[dict]:
    """Return retained include-hit sentences after exclusions and clinical negation."""
    compile_query_rows(rows)
    return _process(note_text, _parse_rows(rows), exclude_negated, True)


def process_expression_note(note_text: str, expression: Expression,
                            exclude_negated: bool = True) -> list[dict]:
    """Engine adapter returning all sentences, with v2 target flags and offsets."""
    return _process(note_text, [(0, "include", expression)], exclude_negated, False)
