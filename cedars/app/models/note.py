"""Note model."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Note(BaseModel):
    """Represents a clinical note/document in CEDARS."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None  # _id in Mongo, auto-increment in SQLite
    text_id: str  # Unique note identifier
    patient_id: str
    text: str  # Full note text
    text_date: Optional[datetime] = None
    reviewed: bool = False
    reviewed_by: Optional[str] = None
    text_tag_1: Optional[str] = None  # Document type
    text_tag_2: Optional[str] = None
    text_tag_3: Optional[str] = None  # Report type
