"""LLM note classifier — single call per patient with excerpts (Decision #32).

Instead of one LLM call per note, sends all matched excerpts for a patient
in a single call and gets a unified classification decision.
"""

import logging
from dataclasses import dataclass, field

from app.llm import complete_json
from app.llm.client import build_connection_kwargs as _build_connection_kwargs

logger = logging.getLogger(__name__)

__all__ = ["ClassificationResult", "classify_patient", "_build_connection_kwargs"]

SYSTEM_PROMPT = """You are a clinical NLP system that classifies whether a patient's clinical notes contain evidence of a specific medical event. You will receive relevant excerpts from the patient's notes sorted chronologically. Respond ONLY with a JSON object.

Classification rules:
- Analyze ALL provided excerpts together for a unified patient-level decision
- Determine if the excerpts collectively contain evidence of the defined event
- Consider inclusion and exclusion criteria carefully
- Negated mentions (e.g., "no evidence of", "ruled out") should NOT be classified as positive
- A single strong positive excerpt is sufficient for a positive classification
- If the event is detected, identify the EARLIEST confirmed occurrence date
- Distinguish between the note date and the actual event date mentioned in the text

Response format (JSON only, no other text):
{
  "event_detected": true or false,
  "confidence": 0.0 to 1.0,
  "event_date": "YYYY-MM-DD or null if not detected or unknown",
  "reasoning": "Brief explanation referencing specific excerpts",
  "evidence": [{"note_id": "...", "text": "relevant excerpt", "note_date": "YYYY-MM-DD"}]
}"""


@dataclass
class ClassificationResult:
    label: str  # "positive" or "negative"
    confidence: float
    reasoning: str
    event_date: str | None = None  # ISO date string
    evidence: list[dict] | None = None
    token_usage: dict | None = field(default=None)


def _build_user_prompt(excerpts: list[dict], event_config) -> str:
    """Build user prompt with all excerpts for a single patient."""
    excerpt_text = "\n\n".join(
        f"--- Excerpt from note {e['note_id']} (date: {e.get('note_date', 'unknown')}) ---\n{e['text']}"
        for e in excerpts
    )
    return f"""Event to detect: {event_config.name}
Description: {event_config.description}
Include criteria: {event_config.include_criteria}
Exclude criteria: {event_config.exclude_criteria}

Patient excerpts ({len(excerpts)} matched notes, chronological order):

{excerpt_text}

Based on ALL excerpts above, classify whether this patient has evidence of the event. Identify the EARLIEST confirmed occurrence date if positive. Respond with JSON only."""


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
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]

    try:
        data, token_usage = await complete_json(
            provider=event_config.llm_provider,
            model=event_config.llm_model,
            messages=messages,
            api_base=event_config.llm_api_base,
            api_key=getattr(event_config, "llm_api_key", None),
            timeout=120,
            num_retries=3,  # litellm retries transient errors (429, 503, timeout)
            response_format={"type": "json_object"},
        )
    except ValueError:
        # Parse failures already carry a "parse" message; surface as-is.
        raise
    except Exception as e:
        raise ValueError(f"Classification failed: {e}") from e

    detected = data.get("event_detected", False)
    confidence = float(data.get("confidence", 0.5))
    reasoning = data.get("reasoning", "")
    event_date = data.get("event_date") if detected else None
    evidence = data.get("evidence", [])

    return ClassificationResult(
        label="positive" if detected else "negative",
        confidence=confidence,
        reasoning=reasoning,
        event_date=event_date,
        evidence=evidence,
        token_usage=token_usage,
    )
