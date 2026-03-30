"""Shared response schemas for background jobs."""

from pydantic import BaseModel


class BackgroundJobResponse(BaseModel):
    """Generic response for background job status queries."""

    job_id: str
    status: str
    progress: int = 0
    result_summary: dict | None = None
