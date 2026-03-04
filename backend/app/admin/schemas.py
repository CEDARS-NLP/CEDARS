"""Schemas for admin queue monitoring API."""

from datetime import datetime

from pydantic import BaseModel


class QueueStats(BaseModel):
    name: str
    pending: int
    active: int
    complete: int
    failed: int


class QueuesResponse(BaseModel):
    queues: list[QueueStats]


class WorkerInfo(BaseModel):
    name: str
    queue: str
    current_job: str | None


class WorkersResponse(BaseModel):
    workers: list[WorkerInfo]


class JobListItem(BaseModel):
    id: str
    project_id: str | None
    job_type: str
    status: str
    progress: int
    error_message: str | None
    created_by: str | None
    started_at: datetime | None
    completed_at: datetime | None
    created_at: datetime
