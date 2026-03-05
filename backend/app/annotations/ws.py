"""WebSocket endpoint for real-time prediction job progress."""

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.common.database import async_session
from app.jobs.models import BackgroundJob, JobStatus

logger = logging.getLogger(__name__)


async def prediction_job_ws(websocket: WebSocket, project_id: str, job_id: str):
    """Stream prediction job progress over WebSocket.

    Polls the BackgroundJob table every 1s and pushes updates to the client.
    Closes when the job reaches a terminal state (completed, failed, cancelled).
    """
    await websocket.accept()

    terminal_statuses = {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}
    last_progress = -1

    try:
        while True:
            async with async_session() as session:
                job = await session.get(BackgroundJob, job_id)

            if not job or job.project_id != project_id:
                await websocket.send_json({"type": "error", "detail": "Job not found"})
                break

            if job.progress != last_progress or job.status in terminal_statuses:
                last_progress = job.progress
                msg = {
                    "type": "progress" if job.status not in terminal_statuses else job.status.value,
                    "job_id": job.id,
                    "status": job.status.value,
                    "progress": job.progress,
                    "result_summary": job.result_summary,
                }
                await websocket.send_json(msg)

            if job.status in terminal_statuses:
                break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
