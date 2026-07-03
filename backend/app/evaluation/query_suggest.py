"""LLM-powered query suggestion for evaluation sessions.

Generates clinician-friendly search queries (spaCy Matcher syntax)
from a natural language event description.
"""

import logging

from app.llm import complete_json

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical NLP expert. Given a clinical event description, generate broad search queries to find relevant mentions in clinical notes.

Use this query syntax:
- `term1 OR term2` — match notes containing either term in a sentence
- `(term1 OR term2) AND term3` — both conditions in same sentence
- `embol*` — wildcard: matches embolism, emboli, embolus, etc.
- `!term` — exclude notes containing this term

Rules:
- Generate include queries (to find relevant notes) and exclude queries (to filter noise)
- Start with more general queries, then add specific ones if needed to improve precision
- Use terms clinicians actually write in notes, including abbreviations
- Include common misspellings and variations
- Keep queries simple and focused — one concept per query
- Only give exclusion queries if there are common sources of false positives
- Prefer wildcards for word stems (e.g., `thromb*` instead of listing all variants)

Respond ONLY with a JSON array:
[
  {"query": "troponin OR MI", "type": "include"},
  {"query": "(ECG OR EKG) AND elevation", "type": "include"},
  {"query": "!suspected", "type": "exclude"}
]"""


async def suggest_queries(
    description: str,
    llm_provider: str,
    llm_model: str,
    llm_api_base: str | None = None,
    llm_api_key: str | None = None,
) -> list[dict]:
    """Generate search query suggestions from a natural language event description.

    Returns list of dicts: [{"query": "...", "type": "include|exclude"}, ...]
    Raises ValueError on LLM or parsing errors.
    """
    user_prompt = f"""Generate search queries to find this clinical event in patient notes:

{description}

Respond with a JSON array only."""

    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        suggestions, _ = await complete_json(
            provider=llm_provider,
            model=llm_model,
            messages=messages,
            api_base=llm_api_base,
            api_key=llm_api_key,
            timeout=60,
        )
    except ValueError:
        raise
    except Exception as e:
        raise ValueError(f"Query suggestion failed: {e}") from e

    if not isinstance(suggestions, list):
        raise ValueError("Expected JSON array of query suggestions")

    # Validate each suggestion has required fields
    validated = []
    for s in suggestions:
        if isinstance(s, dict) and "query" in s:
            validated.append({
                "query": str(s["query"]),
                "type": s.get("type", "include"),
            })
    return validated
