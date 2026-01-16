"""Repository factory - selects the appropriate database backend based on configuration."""

from typing import TYPE_CHECKING

from config import config

if TYPE_CHECKING:
    from app.repositories.interfaces.patient_repository import PatientRepositoryInterface
    from app.repositories.interfaces.note_repository import NoteRepositoryInterface
    from app.repositories.interfaces.annotation_repository import AnnotationRepositoryInterface
    from app.repositories.interfaces.user_repository import UserRepositoryInterface
    from app.repositories.interfaces.project_repository import ProjectRepositoryInterface
    from app.repositories.interfaces.task_repository import TaskRepositoryInterface


def _get_db_type() -> str:
    """Get the database type from configuration."""
    return config.get("DB_TYPE", "mongodb").lower()


def get_patient_repository() -> "PatientRepositoryInterface":
    """Get the patient repository for the configured database type."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.patient_repository import SQLitePatientRepository
        return SQLitePatientRepository()
    else:
        from app.repositories.mongo.patient_repository import MongoPatientRepository
        return MongoPatientRepository()


def get_note_repository() -> "NoteRepositoryInterface":
    """Get the note repository for the configured database type."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.note_repository import SQLiteNoteRepository
        return SQLiteNoteRepository()
    else:
        from app.repositories.mongo.note_repository import MongoNoteRepository
        return MongoNoteRepository()


def get_annotation_repository() -> "AnnotationRepositoryInterface":
    """Get the annotation repository for the configured database type."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.annotation_repository import SQLiteAnnotationRepository
        return SQLiteAnnotationRepository()
    else:
        from app.repositories.mongo.annotation_repository import MongoAnnotationRepository
        return MongoAnnotationRepository()


def get_user_repository() -> "UserRepositoryInterface":
    """Get the user repository for the configured database type."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.user_repository import SQLiteUserRepository
        return SQLiteUserRepository()
    else:
        from app.repositories.mongo.user_repository import MongoUserRepository
        return MongoUserRepository()


def get_project_repository() -> "ProjectRepositoryInterface":
    """Get the project repository for the configured database type."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.project_repository import SQLiteProjectRepository
        return SQLiteProjectRepository()
    else:
        from app.repositories.mongo.project_repository import MongoProjectRepository
        return MongoProjectRepository()


def get_task_repository() -> "TaskRepositoryInterface":
    """Get the task repository for the configured database type."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.task_repository import SQLiteTaskRepository
        return SQLiteTaskRepository()
    else:
        from app.repositories.mongo.task_repository import MongoTaskRepository
        return MongoTaskRepository()


def init_database():
    """Initialize the database (create tables/indices)."""
    db_type = _get_db_type()
    if db_type == "sqlite":
        from app.repositories.sqlite.database import init_db
        init_db()
    # MongoDB indices are created lazily or via create_db_indices()
