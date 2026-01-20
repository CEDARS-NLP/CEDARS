"""Notes summary model for cached statistics."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class NotesSummary(BaseModel):
    """Cached aggregated note statistics per patient."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    patient_id: str
    num_notes: int = 0
    first_note_date: Optional[datetime] = None
    last_note_date: Optional[datetime] = None
