"""User model."""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict


class User(BaseModel):
    """Represents a user account in CEDARS."""

    model_config = ConfigDict(from_attributes=True)

    id: Optional[str] = None
    user: str  # Username (unique)
    password: str  # Hashed password
    is_admin: bool = False
    date_created: Optional[datetime] = None
