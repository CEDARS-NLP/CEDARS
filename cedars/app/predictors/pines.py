"""PINES predictor implementation.

Wraps the existing PINES API (Longformer-based clinical text classifier).
"""

import requests
from loguru import logger

from .base import BasePredictor, PredictionResult, PredictorError


class PinesPredictor(BasePredictor):
    """Predictor using PINES (Longformer-based model) backend.

    PINES classifies clinical notes to detect specific clinical events.
    Requires a pre-trained model for each event type.
    """

    def __init__(self, pines_url: str, timeout: int = 3600):
        """Initialize PINES predictor.

        Args:
            pines_url: URL of the PINES API server (e.g., "http://pines:8036").
            timeout: Request timeout in seconds (default: 3600 for long documents).
        """
        self.pines_url = pines_url.rstrip("/")
        self.timeout = timeout
        self._model_name: str | None = None

    def predict(self, text: str) -> PredictionResult:
        """Classify a clinical note using PINES.

        Args:
            text: Full clinical note text.

        Returns:
            PredictionResult with score and label.

        Raises:
            PredictorError: If PINES API call fails.
        """
        url = f"{self.pines_url}/predict"
        data = {"text": text}

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()

            result = response.json()
            prediction = result.get("prediction", {})
            score = prediction.get("score", 0.0)
            label = prediction.get("label", 0)
            model = result.get("model", "pines")

            # Invert score if label is 0 (negative case)
            # This matches the existing PINES behavior in db.py
            if isinstance(label, str):
                label_int = 0 if "0" in label else 1
                score = 1 - score if label_int == 0 else score
            else:
                label_int = int(label)
                score = 1 - score if label_int == 0 else score

            return PredictionResult(
                score=score,
                label=label_int,
                model=model,
                reasoning=None,  # PINES doesn't provide reasoning
            )

        except requests.exceptions.Timeout:
            logger.error(f"PINES request timed out after {self.timeout}s")
            raise PredictorError(f"PINES request timed out after {self.timeout} seconds")
        except requests.exceptions.ConnectionError as e:
            logger.error(f"Cannot connect to PINES at {self.pines_url}: {e}")
            raise PredictorError(f"Cannot connect to PINES server at {self.pines_url}")
        except requests.exceptions.HTTPError as e:
            logger.error(f"PINES API error: {e}")
            raise PredictorError(f"PINES API error: {e}")
        except (KeyError, ValueError) as e:
            logger.error(f"Invalid PINES response format: {e}")
            raise PredictorError(f"Invalid response from PINES: {e}")

    def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        """Classify multiple clinical notes using PINES batch endpoint.

        Args:
            texts: List of clinical note texts.

        Returns:
            List of PredictionResult, one per input.

        Raises:
            PredictorError: If PINES API call fails.
        """
        url = f"{self.pines_url}/predict_batch"
        data = [{"text": text} for text in texts]

        try:
            response = requests.post(url, json=data, timeout=self.timeout)
            response.raise_for_status()

            results = response.json()
            predictions = []

            for result in results:
                prediction = result.get("prediction", {})
                score = prediction.get("score", 0.0)
                label = prediction.get("label", 0)
                model = result.get("model", "pines")

                # Invert score if label is 0
                if isinstance(label, str):
                    label_int = 0 if "0" in label else 1
                    score = 1 - score if label_int == 0 else score
                else:
                    label_int = int(label)
                    score = 1 - score if label_int == 0 else score

                predictions.append(
                    PredictionResult(
                        score=score,
                        label=label_int,
                        model=model,
                        reasoning=None,
                    )
                )

            return predictions

        except requests.exceptions.RequestException as e:
            logger.error(f"PINES batch request failed: {e}")
            # Fall back to individual predictions
            logger.info("Falling back to individual predictions")
            return [self.predict(text) for text in texts]

    def healthcheck(self) -> bool:
        """Check if PINES server is healthy.

        Returns:
            True if PINES is responding and healthy.
        """
        try:
            response = requests.get(
                f"{self.pines_url}/healthcheck",
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
            is_healthy = data.get("status") == "Healthy"

            if is_healthy:
                # Cache model name from healthcheck
                message = data.get("message", "")
                if "Current Model:" in message:
                    self._model_name = message.split("Current Model:")[-1].strip()

            return is_healthy

        except requests.exceptions.RequestException as e:
            logger.warning(f"PINES healthcheck failed: {e}")
            return False
