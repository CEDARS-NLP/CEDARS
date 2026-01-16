"""SQLite task repository implementation."""

from typing import Optional

from app.models.task import Task
from app.repositories.interfaces.task_repository import TaskRepositoryInterface
from .database import session_scope
from .tables import TaskTable


class SQLiteTaskRepository(TaskRepositoryInterface):
    """SQLite implementation of task repository."""

    def _to_model(self, row: TaskTable) -> Task:
        """Convert SQLAlchemy row to Task model."""
        if row is None:
            return None
        return Task(
            id=str(row.id),
            job_id=row.job_id,
            name=row.name,
            description=row.description or "",
            user=row.user or "",
            complete=row.complete,
            progress=row.progress,
        )

    def get_by_id(self, task_id: str) -> Optional[Task]:
        with session_scope() as session:
            row = session.query(TaskTable).filter_by(job_id=task_id).first()
            return self._to_model(row) if row else None

    def get_in_progress(self, task_id: Optional[str] = None) -> list[Task]:
        with session_scope() as session:
            query = session.query(TaskTable).filter_by(complete=False)
            if task_id:
                query = query.filter_by(job_id=task_id)
            rows = query.all()
            return [self._to_model(row) for row in rows]

    def add_task(self, task: dict) -> bool:
        with session_scope() as session:
            task_row = TaskTable(
                job_id=task.get("job_id"),
                name=task.get("name"),
                description=task.get("description", ""),
                user=task.get("user", ""),
                complete=task.get("complete", False),
                progress=task.get("progress", 0),
            )
            session.add(task_row)
            return True

    def update_progress(self, task_id: str, progress: int, complete: bool = False) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(TaskTable)
                .filter_by(job_id=task_id)
                .update({"progress": progress, "complete": complete})
            )
            return rows_updated > 0

    def report_success(self, job_id: str) -> bool:
        return self.update_progress(job_id, 100, complete=True)

    def report_failure(self, job_id: str) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(TaskTable)
                .filter_by(job_id=job_id)
                .update({"complete": True})
            )
            return rows_updated > 0

    def delete_all(self) -> int:
        with session_scope() as session:
            rows_deleted = session.query(TaskTable).delete()
            return rows_deleted
