"""LLM-powered query suggestion for evaluation sessions.

Generates clinician-friendly search queries (spaCy Matcher syntax)
from a natural language event description.
"""

import json
import logging
import re

import litellm

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


def _build_litellm_model(provider: str, model: str) -> str:
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    if provider in ("vllm", "lmstudio", "tgi", "openai_compatible"):
        return f"openai/{model}"
    return model


def _build_connection_kwargs(
    provider: str, api_base: str | None, api_key: str | None = None
) -> dict:
    kwargs: dict = {}
    if api_base:
        api_base = api_base.rstrip("/")
        if provider in ("vllm", "lmstudio", "tgi", "openai_compatible") and not api_base.endswith("/v1"):
            api_base = api_base + "/v1"
        kwargs["api_base"] = api_base
    if api_key:
        kwargs["api_key"] = api_key
    elif provider in ("ollama", "vllm", "lmstudio", "tgi", "openai_compatible"):
        kwargs["api_key"] = "no-key-required"
    return kwargs


def _parse_json_response(content: str) -> list[dict]:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```(?:json)?\s*", "", content)
        content = content.rstrip("`").strip()

    try:
        data = json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\[.*\]", content, re.DOTALL)
        if match:
            data = json.loads(match.group())
        else:
            raise ValueError(f"Could not parse LLM response as JSON: {content[:200]}")

    if not isinstance(data, list):
        raise ValueError("Expected JSON array of query suggestions")
    return data


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

    model_str = _build_litellm_model(llm_provider, llm_model)
    conn_kwargs = _build_connection_kwargs(llm_provider, llm_api_base, llm_api_key)

    try:
        response = await litellm.acompletion(
            model=model_str,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            timeout=60,
            **conn_kwargs,
        )
    except Exception as e:
        raise ValueError(f"Query suggestion failed: {e}") from e

    content = response.choices[0].message.content or ""
    suggestions = _parse_json_response(content)

    # Validate each suggestion has required fields
    validated = []
    for s in suggestions:
        if isinstance(s, dict) and "query" in s:
            validated.append({
                "query": str(s["query"]),
                "type": s.get("type", "include"),
            })
    return validated
