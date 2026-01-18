"""LLM predictor implementation using LiteLLM.

Supports multiple LLM providers (OpenAI, Anthropic, Ollama, etc.)
for clinical event classification using natural language prompts.
"""

import json
import os
from typing import Any

from loguru import logger

from .base import BasePredictor, PredictionResult, PredictorError
from .config import EventDefinition, LLMConfig, LLMProvider

# LiteLLM is imported at runtime to allow the module to load
# even if litellm isn't installed (for backwards compatibility)
try:
    import litellm
    from litellm import completion
    from litellm.exceptions import (
        APIConnectionError,
        AuthenticationError,
        RateLimitError,
    )

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    litellm = None
    completion = None
    APIConnectionError = Exception
    AuthenticationError = Exception
    RateLimitError = Exception


# Prompt template for clinical event classification
CLASSIFICATION_PROMPT = """You are a clinical research assistant reviewing medical notes to identify specific clinical events.

EVENT TO DETECT: {event_name}
DESCRIPTION: {event_description}
INCLUDE IF: {include_criteria}
EXCLUDE IF: {exclude_criteria}

CLINICAL NOTE:
---
{note_text}
---

INSTRUCTIONS:
1. Read the clinical note carefully
2. Determine if this note documents the specified clinical event
3. Consider carefully:
   - Is this a CONFIRMED occurrence of the event?
   - Or is it: negated, hypothetical, ruled-out, family history, or past medical history without a new event?
4. Assign a confidence score based on how certain you are

Respond with ONLY a JSON object (no markdown, no explanation outside JSON):
{{"contains_event": true or false, "confidence": 0.0 to 1.0, "reasoning": "brief explanation"}}"""


class LLMPredictor(BasePredictor):
    """Predictor using LLMs via LiteLLM for clinical event classification.

    Supports multiple providers: OpenAI, Anthropic, Ollama, LMStudio, Gemini, Bedrock.
    Uses natural language prompts instead of requiring trained models.
    """

    def __init__(self, config: LLMConfig, event_definition: EventDefinition):
        """Initialize LLM predictor.

        Args:
            config: LLM configuration (provider, model, API settings).
            event_definition: Clinical event to detect.

        Raises:
            PredictorError: If LiteLLM is not installed.
        """
        if not LITELLM_AVAILABLE:
            raise PredictorError(
                "LiteLLM is not installed. Install with: pip install litellm"
            )

        self.config = config
        self.event = event_definition
        self._setup_provider()

    def _setup_provider(self) -> None:
        """Configure LiteLLM for the specified provider."""
        # Set API key from environment variable if specified
        if self.config.api_key_env:
            api_key = os.getenv(self.config.api_key_env)
            if not api_key:
                logger.warning(
                    f"API key environment variable {self.config.api_key_env} not set"
                )

        # Configure custom API base for local providers
        if self.config.api_base:
            if self.config.provider == LLMProvider.OLLAMA:
                os.environ["OLLAMA_API_BASE"] = self.config.api_base
            elif self.config.provider == LLMProvider.LMSTUDIO:
                # LMStudio uses OpenAI-compatible API
                os.environ["OPENAI_API_BASE"] = self.config.api_base

        # Disable LiteLLM telemetry
        litellm.telemetry = False

    def _get_model_string(self) -> str:
        """Get the LiteLLM model string for the configured provider.

        Returns:
            Model string in LiteLLM format (e.g., "openai/gpt-4o").
        """
        provider = self.config.provider
        model = self.config.model

        # LiteLLM model name format varies by provider
        if provider == LLMProvider.OPENAI:
            return f"openai/{model}"
        elif provider == LLMProvider.ANTHROPIC:
            return f"anthropic/{model}"
        elif provider == LLMProvider.OLLAMA:
            return f"ollama/{model}"
        elif provider == LLMProvider.LMSTUDIO:
            # LMStudio uses OpenAI-compatible format
            return f"openai/{model}"
        elif provider == LLMProvider.GEMINI:
            return f"gemini/{model}"
        elif provider == LLMProvider.BEDROCK:
            return f"bedrock/{model}"
        else:
            # Default: use model name directly
            return model

    def _build_prompt(self, note_text: str) -> str:
        """Build the classification prompt for a clinical note.

        Args:
            note_text: The clinical note to classify.

        Returns:
            Formatted prompt string.
        """
        return CLASSIFICATION_PROMPT.format(
            event_name=self.event.name,
            event_description=self.event.description,
            include_criteria=self.event.include_criteria,
            exclude_criteria=self.event.exclude_criteria,
            note_text=note_text,
        )

    def _parse_response(self, response_text: str) -> dict[str, Any]:
        """Parse JSON response from LLM.

        Args:
            response_text: Raw response text from LLM.

        Returns:
            Parsed JSON as dict.

        Raises:
            PredictorError: If response is not valid JSON.
        """
        # Strip markdown code blocks if present
        text = response_text.strip()
        if text.startswith("```json"):
            text = text[7:]
        if text.startswith("```"):
            text = text[3:]
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()

        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse LLM response as JSON: {text[:200]}")
            raise PredictorError(f"Invalid JSON response from LLM: {e}")

    def predict(self, text: str) -> PredictionResult:
        """Classify a clinical note using LLM.

        Args:
            text: Full clinical note text.

        Returns:
            PredictionResult with score, label, and reasoning.

        Raises:
            PredictorError: If LLM call fails.
        """
        prompt = self._build_prompt(text)
        model = self._get_model_string()

        try:
            response = completion(
                model=model,
                messages=[{"role": "user", "content": prompt}],
                temperature=self.config.temperature,
                timeout=self.config.timeout,
            )

            response_text = response.choices[0].message.content
            parsed = self._parse_response(response_text)

            contains_event = parsed.get("contains_event", False)
            confidence = float(parsed.get("confidence", 0.5))
            reasoning = parsed.get("reasoning", "")

            # Convert to score matching PINES behavior:
            # - High score = likely contains event
            # - Low score = likely doesn't contain event
            if contains_event:
                score = confidence
                label = 1
            else:
                score = 1 - confidence
                label = 0

            return PredictionResult(
                score=score,
                label=label,
                model=f"{self.config.provider.value}/{self.config.model}",
                reasoning=reasoning,
            )

        except AuthenticationError as e:
            logger.error(f"LLM authentication failed: {e}")
            raise PredictorError(
                f"Invalid API key for {self.config.provider.value}. "
                f"Check environment variable {self.config.api_key_env}"
            )
        except RateLimitError as e:
            logger.error(f"LLM rate limit exceeded: {e}")
            raise PredictorError(
                f"Rate limit exceeded for {self.config.provider.value}. Try again later."
            )
        except APIConnectionError as e:
            logger.error(f"Cannot connect to LLM: {e}")
            raise PredictorError(
                f"Cannot connect to {self.config.provider.value} API. "
                f"Check network connection and API base URL."
            )
        except PredictorError:
            # Re-raise our own errors
            raise
        except Exception as e:
            logger.error(f"LLM prediction failed: {e}")
            raise PredictorError(f"LLM prediction failed: {e}")

    def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        """Classify multiple clinical notes.

        Note: Most LLM APIs don't support true batch processing,
        so this calls predict() for each text sequentially.
        Consider using async for better performance with many texts.

        Args:
            texts: List of clinical note texts.

        Returns:
            List of PredictionResult, one per input.

        Raises:
            PredictorError: If any prediction fails.
        """
        results = []
        for i, text in enumerate(texts):
            try:
                result = self.predict(text)
                results.append(result)
            except PredictorError as e:
                logger.error(f"Failed to predict text {i}: {e}")
                # Return partial results or re-raise
                raise PredictorError(f"Batch prediction failed at text {i}: {e}")
        return results

    def healthcheck(self) -> bool:
        """Check if LLM provider is accessible.

        Sends a minimal request to verify connectivity and authentication.

        Returns:
            True if provider is accessible.
        """
        model = self._get_model_string()

        try:
            # Send a minimal request to check connectivity
            response = completion(
                model=model,
                messages=[{"role": "user", "content": "Reply with: OK"}],
                temperature=0,
                max_tokens=10,
                timeout=10,
            )
            return response.choices[0].message.content is not None

        except Exception as e:
            logger.warning(f"LLM healthcheck failed: {e}")
            return False
