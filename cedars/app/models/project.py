"""Project info model."""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class EventDefinitionModel(BaseModel):
    """Definition of a clinical event to detect (embedded in project)."""

    model_config = ConfigDict(from_attributes=True)

    name: str = ""
    description: str = ""
    include_criteria: str = ""
    exclude_criteria: str = ""


class LLMConfigModel(BaseModel):
    """LLM configuration (embedded in project)."""

    model_config = ConfigDict(from_attributes=True)

    provider: str = "openai"  # openai, anthropic, ollama, lmstudio, gemini, bedrock
    model: str = "gpt-4o"
    api_base: Optional[str] = None
    api_key_env: Optional[str] = None
    timeout: int = 60
    temperature: float = 0.0


class ProjectInfo(BaseModel):
    """Project-level metadata (INFO collection)."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    creation_time: Optional[datetime] = None
    project: str  # Project name
    project_id: str  # Unique project identifier
    investigator: str  # Primary investigator name
    cedars_version: Optional[str] = None  # CEDARS_version in MongoDB

    # PINES configuration (legacy, kept for backwards compatibility)
    pines_url: Optional[str] = None  # PINES API endpoint URL
    is_pines_server_enabled: bool = False

    # Predictor configuration (new)
    predictor_type: Optional[str] = None  # "pines" | "llm" | None
    llm_config: Optional[LLMConfigModel] = None
    event_definition: Optional[EventDefinitionModel] = None
    threshold: float = 0.95  # Score threshold for auto-dismissal
