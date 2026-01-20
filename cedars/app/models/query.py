"""Query configuration models."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class TagQuery(BaseModel):
    """Tag filtering configuration (embedded in Query)."""

    model_config = ConfigDict(from_attributes=True)

    exact: bool = False
    nlp_apply: bool = False
    include: Optional[list[str]] = None
    exclude: Optional[list[str]] = None


class Query(BaseModel):
    """Search and annotation query configuration."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    query: str = ""  # Regex/NLP query string
    exclude_negated: bool = False
    hide_duplicates: bool = False
    skip_after_event: bool = False
    tag_query: Optional[TagQuery] = None
    date_min: Optional[datetime] = None
    date_max: Optional[datetime] = None
    current: bool = False  # Whether this is the active query
