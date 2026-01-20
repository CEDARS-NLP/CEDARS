"""Result model for aggregated patient statistics."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Result(BaseModel):
    """Aggregated statistics and results for a patient."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    patient_id: str
    total_notes: int = 0
    reviewed_notes: int = 0
    total_sentences: str = ""  # Count as string (legacy)
    reviewed_sentences: int = 0
    sentences: str = ""  # Concatenated sentence text (newline-separated)
    event_date: Optional[datetime] = None
    event_information: str = ""  # Text and note_id of event annotation
    first_note_date: Optional[datetime] = None
    last_note_date: Optional[datetime] = None
    comments: str = ""
    reviewer: Optional[str] = None
    max_score_note_id: Optional[str] = None
    max_score_note_date: Optional[datetime] = None
    max_score: Optional[float] = None
    predicted_notes: str = ""  # Formatted predictions (note:date:score)
    last_updated: Optional[datetime] = None
    index_no: int = 0
