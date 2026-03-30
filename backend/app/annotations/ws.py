"""Backwards-compatible re-export — the WebSocket endpoint now lives in app.jobs.ws."""

from app.jobs.ws import job_progress_ws as prediction_job_ws  # noqa: F401
