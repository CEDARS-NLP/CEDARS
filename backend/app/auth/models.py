"""User model and role enum for authentication."""

import enum
from datetime import datetime
from uuid import uuid4

from sqlalchemy import Column, DateTime
from sqlmodel import Field

from app.common.model_registry import GlobalSQLModel
from app.common.utils import now_utc


class UserRole(str, enum.Enum):
    """Roles available for CEDARS platform users."""

    PLATFORM_ADMIN = "platform_admin"
    USER = "user"


class User(GlobalSQLModel, table=True):
    """Platform user account."""

    __tablename__ = "users"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str
    password_hash: str
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(
        default_factory=now_utc,
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
