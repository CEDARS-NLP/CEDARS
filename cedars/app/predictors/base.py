"""Base predictor interface for clinical event classification."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class PredictionResult:
    """Result from a predictor classification."""

    score: float  # Confidence score 0-1
    label: int  # Binary classification: 0 or 1
    model: str  # Model identifier (e.g., "pines-v1", "gpt-4o")
    reasoning: Optional[str] = None  # LLM can provide reasoning, PINES returns None


class PredictorError(Exception):
    """Exception raised by predictors."""

    pass


class BasePredictor(ABC):
    """Abstract base class for clinical event predictors.

    Both PINES and LLM predictors implement this interface,
    allowing the system to use either backend interchangeably.
    """

    @abstractmethod
    def predict(self, text: str) -> PredictionResult:
        """Classify a clinical note.

        Args:
            text: Full clinical note text.

        Returns:
            PredictionResult with score (0-1), label, and model info.

        Raises:
            PredictorError: If prediction fails.
        """
        pass

    @abstractmethod
    def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        """Classify multiple clinical notes.

        Args:
            texts: List of clinical note texts.

        Returns:
            List of PredictionResult, one per input text.

        Raises:
            PredictorError: If prediction fails.
        """
        pass

    @abstractmethod
    def healthcheck(self) -> bool:
        """Check if the predictor backend is available.

        Returns:
            True if backend is healthy and ready.
        """
        pass
