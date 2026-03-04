"""Predictor factory — instantiate predictor from config."""

from app.predictors.base import BasePredictor
from app.predictors.llm import LLMPredictor
from app.predictors.models import PredictorConfig, PredictorType
from app.predictors.pines import PinesPredictor


def create_predictor(predictor_config: PredictorConfig) -> BasePredictor:
    """Create a predictor instance from a PredictorConfig model."""
    if predictor_config.predictor_type == PredictorType.LLM:
        return LLMPredictor(predictor_config.config)
    elif predictor_config.predictor_type == PredictorType.PINES:
        return PinesPredictor(predictor_config.config)
    else:
        raise ValueError(f"Unknown predictor type: {predictor_config.predictor_type}")
