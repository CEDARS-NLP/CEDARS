"""
global_app_tables.py
This module defines the global tables for the CEDARS application.

"""
from __future__ import annotations

from cedars.app.database.project_table_creation import Results
from loguru import logger
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Double,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class GlobalBase(DeclarativeBase):
    """Shared declarative base for all ORM models."""

class Users(GlobalBase):
    """Users table.
    
    The sign_up_time is the date the user registered for the CEDARS application.
    """

    __tablename__ = "Users"

    user_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    # password hash if local auth is used
    # will be null if using SSO auth (like ORCID)
    password_hash: Mapped[str] = mapped_column(
        String(500), nullable=True
    )

    sign_up_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    uses_orcid: Mapped[bool] = mapped_column(Boolean, 
                                             default=False,
                                             nullable=False)

    Projects: Mapped[list["Projects"]] = relationship(
        back_populates="Users", cascade="all, delete-orphan"
    )

    UserProjectRelation: Mapped[list["UserProjectRelation"]] = relationship(
        back_populates="Users", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Users(user_id={self.user_id!r})"

class Projects(GlobalBase):
    """Projects table.
    A list of all projects in this instance of the CEDARS application.
    The investigator is automatically set to the user who created the project.
    """

    __tablename__ = "Projects"

    project_id: Mapped[str] = mapped_column(
        String(100), primary_key=True
    )

    project_name: Mapped[str] = mapped_column(Text, nullable=False)

    creation_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    investigator: Mapped[str] = mapped_column(
        String(100), ForeignKey("Users.user_id"), nullable=False
    )

    cedars_version: Mapped[Decimal] = mapped_column(Double, nullable=False)

    UserProjectRelation: Mapped[list["UserProjectRelation"]] = relationship(
        back_populates="Projects", cascade="all, delete-orphan"
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Projects(project_id={self.project_id!r},project_name={self.project_name!r})"

class UserProjectRelation(GlobalBase):
    """User-Project relation table.
    """

    __tablename__ = "UserProjectRelation"


    project_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Projects.project_id"), nullable=False
    )

    user_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Users.user_id"), nullable=False
    )

    has_admin_privileges: Mapped[bool] = mapped_column(Boolean, nullable=False)

    def __repr__(self) -> str:  # for debugging and logging only
        return f"UserProjectRelation(project_id={self.project_id!r}, investigator={self.user_id!r})"
