"""Annotation model."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Annotation(BaseModel):
    """Represents an NLP annotation/match in CEDARS."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None  # _id in Mongo, auto-increment in SQLite
    patient_id: str
    note_id: str  # References Note.text_id
    sentence: str  # Full sentence containing match
    token: str  # Matched token/entity text
    is_negated: bool = False  # Negation detection result (isNegated in MongoDB)
    note_start_index: int = 0  # Character position in note
    note_end_index: int = 0
    sentence_number: int = 0  # Sentence index in note
    sentence_start: int = 0  # Start position of sentence in note
    sentence_end: int = 0
    text_date: Optional[datetime] = None
    reviewed: int = 0  # ReviewStatus enum value (0=UNREVIEWED, 1=REVIEWED, 2=SKIPPED)

    @property
    def is_reviewed(self) -> bool:
        """Check if annotation has been reviewed."""
        return self.reviewed == 1

    @property
    def is_skipped(self) -> bool:
        """Check if annotation was skipped."""
        return self.reviewed == 2
