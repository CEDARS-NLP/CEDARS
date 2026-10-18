"""Normalize evaluation query drafts without persisting constituent rows."""

from app.nlp.engine import parse_query


def normalize_queries(
    rows: list[dict], *, allow_empty: bool = False, raw_input: bool = False
) -> list[dict]:
    """Compile rows, escaping literal backslashes and ! only for user-entered input."""
    if not isinstance(rows, list) or len(rows) > 50:
        raise ValueError("Search queries must be a list of at most 50 items")
    includes = []
    excludes = []
    for row in rows:
        if not isinstance(row, dict) or row.get("type", "include") not in ("include", "exclude"):
            raise ValueError("Search query type must be include or exclude")
        query = row.get("query")
        if not isinstance(query, str):
            raise ValueError("Search query must be text")
        query = query.strip()
        if not query:
            continue
        if raw_input:
            query = query.replace("\\", "\\\\").replace("!", r"\!")
        parse_query(query)
        (includes if row.get("type", "include") == "include" else excludes).append(query)
    if not includes:
        if allow_empty and not excludes:
            return []
        raise ValueError("At least one include search query is required")
    expression = includes[0] if len(includes) == 1 else " OR ".join(
        f"({query})" for query in includes
    )
    if excludes:
        exclusion = " OR ".join(f"({query})" for query in excludes)
        expression = f"({expression}) AND !({exclusion})"
    groups = parse_query(expression)
    if not any(not condition["negated"] for group in groups for condition in group):
        raise ValueError("At least one positive search term is required")
    return [{"query": expression, "type": "include"}]
