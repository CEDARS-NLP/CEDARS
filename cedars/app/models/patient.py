"""Patient model."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Patient(BaseModel):
    """Represents a patient record in CEDARS."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None  # _id in Mongo, auto-increment in SQLite
    patient_id: str
    reviewed: bool = False
    locked: bool = False
    updated: bool = False
    comments: str = ""
    reviewed_by: Optional[str] = None
    event_date: Optional[datetime] = None
    event_annotation_id: Optional[str] = None
    admin_locked: bool = False
    index_no: int = 0
