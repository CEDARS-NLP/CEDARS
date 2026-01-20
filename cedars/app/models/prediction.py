"""Prediction model for PINES NLP scores."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class Prediction(BaseModel):
    """Stores NLP model predictions for notes (PINES collection)."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    text_id: str  # References Note.text_id
    patient_id: str
    text: Optional[str] = None  # Note text
    text_date: Optional[datetime] = None
    predicted_score: float = 0.0  # Model prediction confidence (0.0-1.0)
    report_type: Optional[str] = None  # From text_tag_3
    document_type: Optional[str] = None  # From text_tag_1
