"""Independent SQLModel registries for global and project databases."""

from sqlalchemy.orm import registry
from sqlmodel import SQLModel

global_registry = registry()
project_registry = registry()


class GlobalSQLModel(SQLModel, registry=global_registry):
    """Base for users, projects, and global project memberships."""

    __abstract__ = True


class ProjectSQLModel(SQLModel, registry=project_registry):
    """Base for project-local clinical and operational records."""

    __abstract__ = True


global_metadata = GlobalSQLModel.metadata
project_metadata = ProjectSQLModel.metadata


def create_all_metadata(connection) -> None:
    """Create both model sets in one database for isolated tests and local tooling."""
    global_metadata.create_all(connection)
    project_metadata.create_all(connection)


def drop_all_metadata(connection) -> None:
    """Drop both model sets in one database for isolated tests and local tooling."""
    project_metadata.drop_all(connection)
    global_metadata.drop_all(connection)
