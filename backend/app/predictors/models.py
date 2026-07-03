"""Predictor configuration models."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel

from app.common.utils import now_utc


class PredictorType(str, enum.Enum):
    """Supported predictor backends."""

    LLM = "llm"
    PINES = "pines"


class PredictorConfig(SQLModel, table=True):
    """A configured predictor for a project."""

    __tablename__ = "predictor_configs"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    project_id: str = Field(foreign_key="projects.id", index=True)
    predictor_type: PredictorType
    name: str
    config: dict = Field(
        default_factory=dict,
        sa_column=Column(JSON, nullable=False, server_default="{}"),
    )
    is_active: bool = Field(default=False)
    created_by: str = Field(foreign_key="users.id")
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    deleted_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), nullable=True),
    )
