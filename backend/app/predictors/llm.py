"""LLM predictor using LiteLLM for multi-provider abstraction."""

import logging
import re

import litellm

from app.llm.client import (
    build_connection_kwargs,
    build_litellm_model,
    extract_json,
    extract_token_usage,
)
from app.predictors.base import BasePredictor, PredictionResult, PredictorError, TokenUsage

logger = logging.getLogger(__name__)

MAX_NOTE_LENGTH = 100_000  # 100KB safety limit

# Patterns that may indicate prompt injection attempts
SUSPICIOUS_PATTERNS = [
    r"ignore\s+(all\s+)?previous\s+instructions",
    r"you\s+are\s+now",
    r"system\s*:\s*",
    r"<\|im_start\|>",
]

SYSTEM_PROMPT = """You are a clinical NLP system that classifies whether a clinical note contains evidence of a specific medical event. You must respond ONLY with a JSON object.

Classification rules:
- Analyze the clinical note within the XML tags
- Determine if the note contains evidence of the defined event
- Consider inclusion and exclusion criteria carefully
- Negated mentions (e.g., "no evidence of", "ruled out") should NOT be classified as positive

Response format (JSON only, no other text):
{
  "event_detected": true or false,
  "confidence": 0.0 to 1.0,
  "reasoning": "Brief explanation"
}"""


def _build_user_prompt(
    text: str,
    event_name: str,
    event_description: str,
    include_criteria: str,
    exclude_criteria: str,
) -> str:
    """Build the user prompt with XML-escaped clinical note."""
    sanitized = _sanitize_note(text)
    return f"""Event to detect: {event_name}
Description: {event_description}
Include criteria: {include_criteria}
Exclude criteria: {exclude_criteria}

<clinical_note>
{sanitized}
</clinical_note>

Classify whether this note contains evidence of the event. Respond with JSON only."""


def _sanitize_note(text: str) -> str:
    """Sanitize clinical note text to prevent prompt injection via XML tags."""
    text = text.replace("</clinical_note>", "&lt;/clinical_note&gt;")
    text = text.replace("<clinical_note>", "&lt;clinical_note&gt;")

    for pattern in SUSPICIOUS_PATTERNS:
        if re.search(pattern, text, re.IGNORECASE):
            logger.warning("Suspicious pattern detected in clinical note: %s", pattern)

    return text[:MAX_NOTE_LENGTH]


class LLMPredictor(BasePredictor):
    """Predictor using LLM providers via LiteLLM."""

    def __init__(self, config: dict):
        self.provider = config.get("provider", "ollama")
        self.model = config.get("model", "llama3")
        self.api_base = config.get("api_base")
        self.api_key = config.get("api_key", "")
        self.temperature = config.get("temperature", 0.0)
        self.timeout = config.get("timeout", 60)
        self.event = config.get("event_definition", {})

    async def predict(self, text: str) -> PredictionResult:
        if not text.strip():
            return PredictionResult(score=0.0, label=0, model=self.model, reasoning="Empty text")

        user_prompt = _build_user_prompt(
            text,
            self.event.get("name", "Clinical Event"),
            self.event.get("description", ""),
            self.event.get("include_criteria", ""),
            self.event.get("exclude_criteria", ""),
        )

        try:
            response = await litellm.acompletion(
                model=build_litellm_model(self.provider, self.model),
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=self.temperature,
                timeout=self.timeout,
                **build_connection_kwargs(self.provider, self.api_base, self.api_key),
            )
        except litellm.AuthenticationError as e:
            raise PredictorError(f"Authentication failed for {self.provider}: {e}") from e
        except litellm.RateLimitError as e:
            raise PredictorError(f"Rate limit exceeded for {self.provider}: {e}") from e
        except litellm.APIConnectionError as e:
            raise PredictorError(f"Cannot connect to {self.provider}: {e}") from e
        except litellm.NotFoundError:
            raise PredictorError(
                f"Model '{self.model}' not found at {self.api_base or 'default endpoint'}. "
                f"Check that the model name matches the server "
                f"(try GET {self.api_base or ''}/models to list available models) "
                f"and the API base URL is correct (should end with /v1 for OpenAI-compatible servers)."
            )
        except Exception as e:
            raise PredictorError(f"LLM prediction failed: {e}") from e

        content = response.choices[0].message.content or ""
        usage = extract_token_usage(response)
        token_usage = TokenUsage(**usage) if usage else None
        result = self._parse_response(content)
        result.token_usage = token_usage
        return result

    async def healthcheck(self) -> bool:
        try:
            response = await litellm.acompletion(
                model=build_litellm_model(self.provider, self.model),
                messages=[{"role": "user", "content": "Reply with: OK"}],
                max_tokens=5,
                timeout=10,
                **build_connection_kwargs(self.provider, self.api_base, self.api_key),
            )
            return bool(response.choices)
        except Exception:
            return False

    def _parse_response(self, content: str) -> PredictionResult:
        """Parse LLM JSON response into PredictionResult.

        Unlike the raising ``extract_json``, an unparseable response degrades to
        a neutral negative result rather than erroring — a prediction backend
        should not crash a run on a single malformed reply.
        """
        try:
            data = extract_json(content)
        except ValueError:
            logger.warning("Failed to parse LLM response: %s", content[:200])
            return PredictionResult(
                score=0.0, label=0, model=self.model,
                reasoning=f"Failed to parse response: {content[:100]}",
            )

        detected = data.get("event_detected", False)
        confidence = float(data.get("confidence", 0.5))
        reasoning = data.get("reasoning", "")

        score = confidence if detected else (1.0 - confidence)
        label = 1 if detected else 0

        return PredictionResult(
            score=score,
            label=label,
            model=self.model,
            reasoning=reasoning,
        )
