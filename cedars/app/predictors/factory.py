"""Factory function for creating predictors based on project configuration."""

from typing import Optional

from loguru import logger

from .base import BasePredictor, PredictorError
from .config import (
    EventDefinition,
    LLMConfig,
    LLMProvider,
    PredictorConfig,
    PredictorType,
)
from .llm import LLMPredictor
from .pines import PinesPredictor


def get_predictor(
    predictor_config: Optional[PredictorConfig] = None,
    project_info: Optional[dict] = None,
) -> BasePredictor:
    """Create a predictor based on configuration.

    Args:
        predictor_config: Explicit predictor configuration. If provided,
            project_info is ignored.
        project_info: Project info dict from MongoDB INFO collection.
            Used to build predictor config if predictor_config is not provided.

    Returns:
        Configured predictor instance (PinesPredictor or LLMPredictor).

    Raises:
        PredictorError: If configuration is invalid or missing.
    """
    # If explicit config provided, use it directly
    if predictor_config is not None:
        return _create_from_config(predictor_config)

    # Otherwise, build config from project_info
    if project_info is None:
        raise PredictorError("Either predictor_config or project_info must be provided")

    config = _build_config_from_project(project_info)
    return _create_from_config(config)


def get_predictor_from_db() -> BasePredictor:
    """Create a predictor from the current project's database configuration.

    Reads the INFO collection to get predictor settings.

    Returns:
        Configured predictor instance.

    Raises:
        PredictorError: If no project configured or configuration invalid.
    """
    # Import here to avoid circular imports
    from ..database import mongo

    info = mongo.db["INFO"].find_one()
    if info is None:
        raise PredictorError("No project configured. Create a project first.")

    return get_predictor(project_info=info)


def _build_config_from_project(project_info: dict) -> PredictorConfig:
    """Build PredictorConfig from project info document.

    Args:
        project_info: MongoDB document from INFO collection.

    Returns:
        PredictorConfig with settings from project.
    """
    # Check for new-style predictor configuration
    predictor_type_str = project_info.get("predictor_type")

    if predictor_type_str == "llm":
        # LLM predictor configuration
        llm_config_dict = project_info.get("llm_config", {})
        event_def_dict = project_info.get("event_definition", {})

        if not llm_config_dict:
            raise PredictorError("LLM predictor selected but llm_config is missing")
        if not event_def_dict:
            raise PredictorError(
                "LLM predictor selected but event_definition is missing"
            )

        llm_config = LLMConfig(
            provider=LLMProvider(llm_config_dict.get("provider", "openai")),
            model=llm_config_dict.get("model", "gpt-4o"),
            api_base=llm_config_dict.get("api_base"),
            api_key_env=llm_config_dict.get("api_key_env"),
            timeout=llm_config_dict.get("timeout", 60),
            temperature=llm_config_dict.get("temperature", 0.0),
        )

        event_definition = EventDefinition(
            name=event_def_dict.get("name", ""),
            description=event_def_dict.get("description", ""),
            include_criteria=event_def_dict.get("include_criteria", ""),
            exclude_criteria=event_def_dict.get("exclude_criteria", ""),
        )

        return PredictorConfig(
            predictor_type=PredictorType.LLM,
            llm_config=llm_config,
            event_definition=event_definition,
            threshold=project_info.get("threshold", 0.95),
        )

    elif predictor_type_str == "pines" or project_info.get("nlp_apply"):
        # PINES predictor (explicit or legacy nlp_apply=true)
        pines_url = project_info.get("pines_url")
        if not pines_url:
            raise PredictorError("PINES predictor selected but pines_url is missing")

        return PredictorConfig(
            predictor_type=PredictorType.PINES,
            pines_url=pines_url,
            threshold=project_info.get("threshold", 0.95),
        )

    else:
        raise PredictorError(
            "No predictor configured. Set predictor_type to 'pines' or 'llm'."
        )


def _create_from_config(config: PredictorConfig) -> BasePredictor:
    """Create predictor instance from configuration.

    Args:
        config: Predictor configuration.

    Returns:
        Predictor instance.

    Raises:
        PredictorError: If configuration is invalid.
    """
    if config.predictor_type == PredictorType.PINES:
        if not config.pines_url:
            raise PredictorError("PINES URL is required for PINES predictor")

        logger.info(f"Creating PINES predictor with URL: {config.pines_url}")
        return PinesPredictor(pines_url=config.pines_url)

    elif config.predictor_type == PredictorType.LLM:
        if not config.llm_config:
            raise PredictorError("LLM config is required for LLM predictor")
        if not config.event_definition:
            raise PredictorError("Event definition is required for LLM predictor")

        logger.info(
            f"Creating LLM predictor with provider: {config.llm_config.provider.value}, "
            f"model: {config.llm_config.model}"
        )
        return LLMPredictor(
            config=config.llm_config,
            event_definition=config.event_definition,
        )

    else:
        raise PredictorError(f"Unknown predictor type: {config.predictor_type}")
