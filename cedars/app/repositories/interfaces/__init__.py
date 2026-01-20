"""Abstract repository interfaces."""

from .patient_repository import PatientRepositoryInterface
from .note_repository import NoteRepositoryInterface
from .annotation_repository import AnnotationRepositoryInterface
from .user_repository import UserRepositoryInterface
from .project_repository import ProjectRepositoryInterface
from .task_repository import TaskRepositoryInterface
from .evaluation_repository import EvaluationRepositoryInterface

__all__ = [
    "PatientRepositoryInterface",
    "NoteRepositoryInterface",
    "AnnotationRepositoryInterface",
    "UserRepositoryInterface",
    "ProjectRepositoryInterface",
    "TaskRepositoryInterface",
    "EvaluationRepositoryInterface",
]
