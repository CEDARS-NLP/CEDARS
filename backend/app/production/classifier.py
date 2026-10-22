"""Full-note production classifier; isolated from evaluation classification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.llm import complete_json

SYSTEM_PROMPT = """You classify one complete clinical note for a configured medical event.
Return only a JSON object with exactly these fields:
{
  "label": "positive" or "negative",
  "score": 0.0,
  "reasoning": "brief evidence-based explanation",
  "evidence_spans": [{"start": 0, "end": 12, "text": "exact note text"}]
}
The score is the probability that the label is correct, from 0 to 1. Evidence spans
must use zero-based half-open character offsets into the supplied note and reproduce
the exact text at those offsets. Return an empty evidence_spans list when no span
supports the decision. Do not return an event date or infer one."""


@dataclass(frozen=True)
class NoteClassification:
    label: int
    score: float
    reasoning: str
    evidence_spans: list[dict[str, Any]]
    token_usage: dict[str, Any] | None = None


def _field(source: Any, *names: str, default: Any = None) -> Any:
    for name in names:
        if isinstance(source, dict) and name in source:
            return source[name]
        value = getattr(source, name, None)
        if value is not None:
            return value
    return default


def _event_config(config: Any) -> tuple[Any, Any]:
    nested = _field(config, "config", default=config)
    event = _field(nested, "event_definition", "event_config", "event", default=nested)
    llm = _field(nested, "llm_config", "llm", default=nested)
    return event, llm


def _parse_label(value: Any) -> int:
    if value in (1, True, "1", "positive", "event", "yes"):
        return 1
    if value in (0, False, "0", "negative", "no_event", "no"):
        return 0
    raise ValueError("Classification label must be positive/1 or negative/0")


async def classify_note(
    note_text: str,
    config: Any,
    *,
    api_key: str | None = None,
) -> NoteClassification:
    """Classify the complete note and validate evidence against its source text."""
    event, llm = _event_config(config)
    provider = _field(llm, "provider", "llm_provider")
    model = _field(llm, "model", "llm_model")
    if not provider or not model:
        raise ValueError("LLM production config requires provider and model")

    name = _field(event, "name", "event_name", default="Configured event")
    description = _field(event, "description", default="")
    include = _field(event, "include_criteria", "inclusion_criteria", default="")
    exclude = _field(event, "exclude_criteria", "exclusion_criteria", default="")
    data, usage = await complete_json(
        provider=str(provider),
        model=str(model),
        api_base=_field(llm, "api_base", "llm_api_base"),
        api_key=api_key,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": (
                    f"Event: {name}\nDescription: {description}\n"
                    f"Include criteria: {include}\nExclude criteria: {exclude}\n\n"
                    f"Complete note (text_id={_field(config, 'text_id', default='')!s}):\n"
                    f"<clinical_note>\n{note_text}\n</clinical_note>\n\n"
                    "Classify this note using the required JSON contract."
                ),
            },
        ],
        timeout=120,
        num_retries=3,
        response_format={"type": "json_object"},
    )

    if not isinstance(data, dict):
        raise ValueError("Classification response must be a JSON object")
    missing = {"label", "score", "reasoning", "evidence_spans"} - data.keys()
    if missing:
        raise ValueError(f"Classification response is missing required fields: {sorted(missing)}")

    label = _parse_label(data["label"])
    try:
        score = float(data["score"])
    except (TypeError, ValueError) as exc:
        raise ValueError("Classification score must be a number between 0 and 1") from exc
    if not 0 <= score <= 1:
        raise ValueError("Classification score must be a number between 0 and 1")
    reasoning = data["reasoning"]
    if not isinstance(reasoning, str):
        raise ValueError("Classification reasoning must be text")

    raw_spans = data["evidence_spans"]
    if not isinstance(raw_spans, list):
        raise ValueError("Classification evidence_spans must be a list")
    spans: list[dict[str, Any]] = []
    for span in raw_spans:
        if not isinstance(span, dict):
            raise ValueError("Each evidence span must be an object")
        start, end, text = span.get("start"), span.get("end"), span.get("text")
        if (
            not isinstance(start, int)
            or isinstance(start, bool)
            or not isinstance(end, int)
            or isinstance(end, bool)
            or not isinstance(text, str)
            or start < 0
            or end <= start
            or end > len(note_text)
            or note_text[start:end] != text
        ):
            raise ValueError("Evidence span offsets and text must match the supplied note")
        spans.append({"start": start, "end": end, "text": text})

    return NoteClassification(
        label=label,
        score=score,
        reasoning=reasoning,
        evidence_spans=spans,
        token_usage=usage,
    )


__all__ = ["NoteClassification", "classify_note"]
