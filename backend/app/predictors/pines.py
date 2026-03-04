"""PINES predictor — HTTP client for the Longformer NLP service."""

import logging

import httpx

from app.predictors.base import BasePredictor, PredictionResult, PredictorError

logger = logging.getLogger(__name__)


class PinesPredictor(BasePredictor):
    """Predictor wrapping the PINES REST API."""

    def __init__(self, config: dict):
        self.api_url = config.get("pines_api_url", "http://localhost:8000")
        self.timeout = config.get("timeout", 3600)
        self._model_name: str | None = None

    async def predict(self, text: str) -> PredictionResult:
        if not text.strip():
            return PredictionResult(score=0.0, label=0, model="pines", reasoning="Empty text")

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.api_url}/predict",
                    json={"text": text},
                )
                resp.raise_for_status()
            except httpx.HTTPError as e:
                raise PredictorError(f"PINES prediction failed: {e}") from e

        data = resp.json()
        score = float(data.get("score", 0.0))
        label = int(data.get("label", 0))

        # Invert score when label is 0 to match v1 behavior
        if label == 0:
            score = 1.0 - score

        return PredictionResult(
            score=score,
            label=label,
            model=self._model_name or "pines",
            reasoning="",
        )

    async def predict_batch(self, texts: list[str]) -> list[PredictionResult]:
        """Try batch endpoint, fall back to individual predictions."""
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.post(
                    f"{self.api_url}/predict_batch",
                    json={"texts": texts},
                )
                resp.raise_for_status()
                results = resp.json()
                return [
                    PredictionResult(
                        score=1.0 - r["score"] if r["label"] == 0 else r["score"],
                        label=r["label"],
                        model=self._model_name or "pines",
                    )
                    for r in results
                ]
            except httpx.HTTPError:
                logger.warning("PINES batch endpoint failed, falling back to individual")
                return await super().predict_batch(texts)

    async def healthcheck(self) -> bool:
        async with httpx.AsyncClient(timeout=10) as client:
            try:
                resp = await client.get(f"{self.api_url}/healthcheck")
                resp.raise_for_status()
                data = resp.json()
                self._model_name = data.get("model", "pines")
                return True
            except httpx.HTTPError:
                return False
