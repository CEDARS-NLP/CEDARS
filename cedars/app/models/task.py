"""Task model for background job tracking."""

from typing import Optional

from pydantic import BaseModel, ConfigDict


class Task(BaseModel):
    """Background job tracking (RQ Redis Queue integration)."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    job_id: str  # Unique job identifier (format: "name-patient_id")
    name: str  # Task name (e.g., "nlp_processor")
    description: str = ""  # Human-readable description
    user: str = ""  # Username who triggered task
    complete: bool = False  # Task completion status
    progress: int = 0  # Progress percentage (0-100)
