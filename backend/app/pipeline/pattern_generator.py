"""LLM-powered search pattern generation for pipeline EventConfigs."""

import json
import logging
import re

import litellm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical NLP expert. Given a clinical event description, generate search patterns to find relevant mentions in clinical notes.

You must respond ONLY with a JSON object containing these fields:
- "keywords": list of lowercase keywords/phrases to search for (exact match, case-insensitive)
- "regex_patterns": list of Python-compatible regex patterns for flexible matching
- "exclusion_patterns": list of regex patterns that indicate false positives (e.g., negations, family history)

Rules:
- Keywords should be common terms clinicians use for this event
- Regex patterns should capture variations (abbreviations, misspellings, related terms)
- Exclusion patterns should catch negations and irrelevant mentions
- All patterns should be case-insensitive compatible
- Keep regex patterns simple and efficient

Response format (JSON only, no other text):
{
  "keywords": ["term1", "term2"],
  "regex_patterns": ["pattern1", "pattern2"],
  "exclusion_patterns": ["neg_pattern1"]
}"""


def _build_user_prompt(
    event_name: str,
    description: str,
    include_criteria: str,
    exclude_criteria: str,
) -> str:
    return f"""Generate search patterns for this clinical event:

Event name: {event_name}
Description: {description}
Include criteria: {include_criteria}
Exclude criteria: {exclude_criteria}

Respond with JSON only."""


def _build_litellm_model(provider: str, model: str) -> str:
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    if provider in ("vllm", "lmstudio", "tgi", "openai_compatible"):
        return f"openai/{model}"
    return model


def _build_connection_kwargs(provider: str, api_base: str | None, api_key: str | None = None) -> dict:
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


def _parse_json_response(content: str) -> dict:
    content = content.strip()
    if content.startswith("```"):
        content = re.sub(r"```(?:json)?\s*", "", content)
        content = content.rstrip("`").strip()

    try:
        return json.loads(content)
    except json.JSONDecodeError:
        match = re.search(r"\{[^}]+\}", content, re.DOTALL)
        if match:
            return json.loads(match.group())
        raise ValueError(f"Could not parse LLM response as JSON: {content[:200]}")


def _validate_regex_patterns(patterns: list[str]) -> list[str]:
    valid = []
    for p in patterns:
        try:
            re.compile(p)
            valid.append(p)
        except re.error:
            logger.warning("Filtering out invalid regex pattern: %s", p)
    return valid


async def generate_search_patterns(
    event_name: str,
    description: str,
    include_criteria: str,
    exclude_criteria: str,
    llm_provider: str,
    llm_model: str,
    llm_api_base: str | None = None,
    llm_api_key: str | None = None,
) -> dict:
    """Generate search patterns using an LLM.

    Returns dict with keys: keywords, regex_patterns, exclusion_patterns.
    Raises ValueError on LLM or parsing errors.
    """
    user_prompt = _build_user_prompt(event_name, description, include_criteria, exclude_criteria)
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
        raise ValueError(f"Pattern generation failed: {e}") from e

    content = response.choices[0].message.content or ""
    data = _parse_json_response(content)

    return {
        "keywords": data.get("keywords", []),
        "regex_patterns": _validate_regex_patterns(data.get("regex_patterns", [])),
        "exclusion_patterns": _validate_regex_patterns(data.get("exclusion_patterns", [])),
    }
