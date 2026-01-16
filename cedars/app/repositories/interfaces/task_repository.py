"""Task repository interface."""

from abc import ABC, abstractmethod
from typing import Optional

from app.models.task import Task


class TaskRepositoryInterface(ABC):
    """Abstract interface for background task tracking."""

    @abstractmethod
    def get_by_id(self, task_id: str) -> Optional[Task]:
        """Get a task by its job_id."""
        pass

    @abstractmethod
    def get_in_progress(self, task_id: Optional[str] = None) -> list[Task]:
        """Get tasks that are in progress (not complete)."""
        pass

    @abstractmethod
    def add_task(self, task: dict) -> bool:
        """Add a new task. Returns True if successful."""
        pass

    @abstractmethod
    def update_progress(self, task_id: str, progress: int, complete: bool = False) -> bool:
        """Update task progress."""
        pass

    @abstractmethod
    def report_success(self, job_id: str) -> bool:
        """Mark a job as successfully completed."""
        pass

    @abstractmethod
    def report_failure(self, job_id: str) -> bool:
        """Mark a job as failed."""
        pass

    @abstractmethod
    def delete_all(self) -> int:
        """Delete all tasks. Returns count deleted."""
        pass
