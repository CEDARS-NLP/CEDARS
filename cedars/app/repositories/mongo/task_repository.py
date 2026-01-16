"""MongoDB task repository implementation."""

from typing import Optional

from app.database import mongo
from app.models.task import Task
from app.repositories.interfaces.task_repository import TaskRepositoryInterface


class MongoTaskRepository(TaskRepositoryInterface):
    """MongoDB implementation of task repository."""

    @property
    def collection(self):
        return mongo.db["TASK"]

    def _to_model(self, doc: dict) -> Task:
        """Convert MongoDB document to Task model."""
        if doc is None:
            return None
        doc["id"] = str(doc.pop("_id", None))
        return Task(**doc)

    def get_by_id(self, task_id: str) -> Optional[Task]:
        doc = self.collection.find_one({"job_id": task_id})
        return self._to_model(doc) if doc else None

    def get_in_progress(self, task_id: Optional[str] = None) -> list[Task]:
        query = {"complete": False}
        if task_id:
            query["job_id"] = task_id
        cursor = self.collection.find(query)
        return [self._to_model(doc) for doc in cursor]

    def add_task(self, task: dict) -> bool:
        result = self.collection.insert_one(task)
        return result.inserted_id is not None

    def update_progress(self, task_id: str, progress: int, complete: bool = False) -> bool:
        result = self.collection.update_one(
            {"job_id": task_id},
            {"$set": {"progress": progress, "complete": complete}},
        )
        return result.modified_count > 0

    def report_success(self, job_id: str) -> bool:
        return self.update_progress(job_id, 100, complete=True)

    def report_failure(self, job_id: str) -> bool:
        # For failures, we just mark as complete but keep progress as-is
        result = self.collection.update_one(
            {"job_id": job_id},
            {"$set": {"complete": True}},
        )
        return result.modified_count > 0

    def delete_all(self) -> int:
        result = self.collection.delete_many({})
        return result.deleted_count
