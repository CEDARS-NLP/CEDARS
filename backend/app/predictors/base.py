"""Base predictor interface and prediction result."""

from abc import ABC, abstractmethod
from dataclasses import dataclass


class PredictorError(Exception):
    """Raised when a predictor fails."""


@dataclass
class TokenUsage:
    """Token usage from an LLM prediction call."""

    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0


@dataclass
class PredictionResult:
    """Result of a clinical event classification."""

    score: float  # 0.0–1.0 confidence that the event IS present
    label: int  # 0 = no event, 1 = event detected
    model: str = ""
    reasoning: str = ""
    token_usage: TokenUsage | None = None


class BasePredictor(ABC):
    """Abstract base for all predictor implementations."""

    @abstractmethod
    async def predict(self, text: str) -> PredictionResult:
        """Classify a single clinical text."""

    async def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        """Classify multiple texts. Default: sequential calls."""
        results = []
        for text in texts:
            results.append(await self.predict(text))
        return results

    @abstractmethod
    async def healthcheck(self) -> bool:
        """Check if the predictor backend is available."""
