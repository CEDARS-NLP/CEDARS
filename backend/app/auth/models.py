"""User model and role enum for authentication."""

import enum
from datetime import UTC, datetime
from uuid import uuid4

from sqlmodel import Field, SQLModel


class UserRole(str, enum.Enum):
    """Roles available for CEDARS platform users."""

    PLATFORM_ADMIN = "platform_admin"
    USER = "user"


class User(SQLModel, table=True):
    """Platform user account."""

    __tablename__ = "users"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    email: str = Field(unique=True, index=True)
    name: str
    password_hash: str
    role: UserRole = Field(default=UserRole.USER)
    is_active: bool = Field(default=True)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
