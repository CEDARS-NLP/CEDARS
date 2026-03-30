"""LLM note classifier — single call per patient with excerpts (Decision #32).

Instead of one LLM call per note, sends all matched excerpts for a patient
in a single call and gets a unified classification decision.
"""

import json
import logging
import re
from dataclasses import dataclass, field

import litellm

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a clinical NLP system that classifies whether a patient's clinical notes contain evidence of a specific medical event. You will receive relevant excerpts from the patient's notes. Respond ONLY with a JSON object.

Classification rules:
- Analyze ALL provided excerpts together for a unified patient-level decision
- Determine if the excerpts collectively contain evidence of the defined event
- Consider inclusion and exclusion criteria carefully
- Negated mentions (e.g., "no evidence of", "ruled out") should NOT be classified as positive
- A single strong positive excerpt is sufficient for a positive classification

Response format (JSON only, no other text):
{
  "event_detected": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "Brief explanation referencing specific excerpts"
}"""


@dataclass
class ClassificationResult:
    label: str  # "positive" or "negative"
    confidence: float
    reasoning: str
    token_usage: dict | None = field(default=None)


def _build_user_prompt(excerpts: list[dict], event_config) -> str:
    """Build user prompt with all excerpts for a single patient."""
    excerpt_text = "\n\n".join(
        f"--- Excerpt from note {e['note_id']} ---\n{e['text']}"
        for e in excerpts
    )
    return f"""Event to detect: {event_config.name}
Description: {event_config.description}
Include criteria: {event_config.include_criteria}
Exclude criteria: {event_config.exclude_criteria}

Patient excerpts ({len(excerpts)} matched notes):

{excerpt_text}

Based on ALL excerpts above, classify whether this patient has evidence of the event. Respond with JSON only."""


def _build_litellm_model(provider: str, model: str) -> str:
    if provider == "ollama":
        return f"ollama/{model}"
    if provider == "bedrock":
        return f"bedrock/{model}"
    if provider in ("vllm", "lmstudio", "tgi", "openai_compatible"):
        return f"openai/{model}"
    return model


def _build_connection_kwargs(provider: str, api_base: str | None) -> dict:
    kwargs: dict = {}
    if api_base:
        api_base = api_base.rstrip("/")
        if provider in ("vllm", "lmstudio", "tgi", "openai_compatible") and not api_base.endswith("/v1"):
            api_base = api_base + "/v1"
        kwargs["api_base"] = api_base
    if provider in ("ollama", "vllm", "lmstudio", "tgi", "openai_compatible"):
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
        raise ValueError(f"Could not parse LLM classification response: {content[:200]}")


async def classify_patient(
    excerpts: list[dict],
    event_config,
) -> ClassificationResult:
    """Classify a patient using a single LLM call with all matched excerpts.

    Args:
        excerpts: List of dicts with 'note_id' and 'text' keys.
        event_config: Object with name, description, include_criteria,
            exclude_criteria, llm_provider, llm_model, llm_api_base.

    Returns:
        ClassificationResult with label, confidence, reasoning, token_usage.

    Raises:
        ValueError: On LLM or parsing errors.
    """
    if not excerpts:
        return ClassificationResult(label="negative", confidence=0.0, reasoning="No matched excerpts")

    user_prompt = _build_user_prompt(excerpts, event_config)
    model_str = _build_litellm_model(event_config.llm_provider, event_config.llm_model)
    conn_kwargs = _build_connection_kwargs(event_config.llm_provider, event_config.llm_api_base)

    try:
        response = await litellm.acompletion(
            model=model_str,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.0,
            timeout=120,
            **conn_kwargs,
        )
    except Exception as e:
        raise ValueError(f"Classification failed: {e}") from e

    content = response.choices[0].message.content or ""
    data = _parse_json_response(content)

    token_usage = None
    if hasattr(response, "usage") and response.usage:
        token_usage = {
            "prompt_tokens": getattr(response.usage, "prompt_tokens", 0) or 0,
            "completion_tokens": getattr(response.usage, "completion_tokens", 0) or 0,
            "total_tokens": getattr(response.usage, "total_tokens", 0) or 0,
        }

    detected = data.get("event_detected", False)
    confidence = float(data.get("confidence", 0.5))
    reasoning = data.get("reasoning", "")

    return ClassificationResult(
        label="positive" if detected else "negative",
        confidence=confidence,
        reasoning=reasoning,
        token_usage=token_usage,
    )
