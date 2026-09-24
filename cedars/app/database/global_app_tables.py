"""
global_app_tables.py
This module defines the global tables for the CEDARS application.

"""
from __future__ import annotations

from loguru import logger
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Double,
    String,
    Text,
    Integer,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from ..schemas import ProjectRole


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

    # Global superuser flag (first registered user, or explicitly promoted).
    # Distinct from per-project admin status (ProjectUsers.is_admin /
    # UserProjectRelation.has_admin_privileges).
    is_admin: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )

    sign_up_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    uses_orcid: Mapped[bool] = mapped_column(Boolean, 
                                             default=False,
                                             nullable=False)

    auth_provider: Mapped[Optional[str]] = mapped_column(String(50), nullable=True)

    sso_subject: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    sso_email: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)

    sso_email_verified: Mapped[Optional[bool]] = mapped_column(Boolean, nullable=True)

    sso_groups_json: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    last_login_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)

    created_projects: Mapped[list["Projects"]] = relationship(
        back_populates="investigator_user",
        foreign_keys="Projects.investigator",
    )

    project_memberships: Mapped[list["UserProjectRelation"]] = relationship(
        back_populates="user",
        foreign_keys="UserProjectRelation.user_id",
    )

    memberships_added: Mapped[list["UserProjectRelation"]] = relationship(
        back_populates="added_by_user",
        foreign_keys="UserProjectRelation.added_by",
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

    description: Mapped[str] = mapped_column(Text, default="", nullable=False)

    creation_time: Mapped[datetime] = mapped_column(
        DateTime, default=datetime.now(timezone.utc), nullable=False
    )

    investigator: Mapped[str] = mapped_column(
        String(100), ForeignKey("Users.user_id"), nullable=False
    )

    cedars_version: Mapped[Decimal] = mapped_column(Double, nullable=False)

    investigator_user: Mapped["Users"] = relationship(
        back_populates="created_projects",
        foreign_keys=[investigator],
    )

    memberships: Mapped[list["UserProjectRelation"]] = relationship(
        back_populates="project",
        foreign_keys="UserProjectRelation.project_id",
    )

    def __repr__(self) -> str:  # for debugging and logging only
        return f"Projects(project_id={self.project_id!r},project_name={self.project_name!r})"

class UserProjectRelation(GlobalBase):
    """User-Project relation table.
    """

    __tablename__ = "UserProjectRelation"

    relation_id: Mapped[int] = mapped_column(
        Integer, primary_key=True, autoincrement=True
    )

    project_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Projects.project_id"), nullable=False
    )

    user_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Users.user_id"), nullable=False
    )

    added_by: Mapped[str] = mapped_column(
        String(100), ForeignKey("Users.user_id"), nullable=False
    )

    role: Mapped[str] = mapped_column(
        String(20), nullable=False, default=ProjectRole.ANNOTATOR.value
    )

    project: Mapped["Projects"] = relationship(
        back_populates="memberships",
        foreign_keys=[project_id],
    )

    user: Mapped["Users"] = relationship(
        back_populates="project_memberships",
        foreign_keys=[user_id],
    )

    added_by_user: Mapped["Users"] = relationship(
        back_populates="memberships_added",
        foreign_keys=[added_by],
    )

    @property
    def has_admin_privileges(self) -> bool:
        return self.role in {ProjectRole.ADMIN.value, ProjectRole.INVESTIGATOR.value}

    @has_admin_privileges.setter
    def has_admin_privileges(self, value: bool) -> None:
        self.role = ProjectRole.ADMIN.value if value else ProjectRole.ANNOTATOR.value

    def __repr__(self) -> str:  # for debugging and logging only
        return f"UserProjectRelation(project_id={self.project_id!r}, investigator={self.user_id!r})"


class ProjectRedisCredentials(GlobalBase):
    """Per-project Redis ACL identity, used to scope RQ queues/dashboard access."""

    __tablename__ = "ProjectRedisCredentials"

    project_id: Mapped[str] = mapped_column(
        String(100), ForeignKey("Projects.project_id"), primary_key=True
    )

    redis_username: Mapped[str] = mapped_column(String(150), nullable=False)

    redis_secret: Mapped[str] = mapped_column(String(200), nullable=False)
