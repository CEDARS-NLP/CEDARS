"""Configuration models for predictors."""

from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

# Import canonical model from models module to avoid duplication
from app.models.project import EventDefinitionModel


class PredictorType(str, Enum):
    """Type of predictor backend."""

    PINES = "pines"
    LLM = "llm"


class LLMProvider(str, Enum):
    """Supported LLM providers via LiteLLM."""

    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    OLLAMA = "ollama"
    LMSTUDIO = "lmstudio"
    GEMINI = "gemini"
    BEDROCK = "bedrock"


# Alias for backwards compatibility - use EventDefinitionModel as the canonical definition
# The model in app/models/project.py is the source of truth
EventDefinition = EventDefinitionModel


class LLMConfig(BaseModel):
    """Configuration for LLM predictor."""

    model_config = ConfigDict(from_attributes=True)

    provider: LLMProvider
    model: str  # e.g., "gpt-4o", "claude-sonnet-4-20250514", "llama3"
    api_base: Optional[str] = None  # Custom endpoint for Ollama/LMStudio
    api_key_env: Optional[str] = None  # Env var name for API key (never store key directly)
    timeout: int = 60  # Request timeout in seconds
    temperature: float = 0.0  # Low temperature for consistent classification


class PredictorConfig(BaseModel):
    """Full predictor configuration for a project."""

    model_config = ConfigDict(from_attributes=True)

    predictor_type: PredictorType
    pines_url: Optional[str] = None  # Used if predictor_type == PINES
    llm_config: Optional[LLMConfig] = None  # Used if predictor_type == LLM
    event_definition: Optional[EventDefinition] = None  # Required for LLM
    threshold: float = 0.95  # Score threshold for auto-dismissal
