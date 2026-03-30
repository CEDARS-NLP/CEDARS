"""WebSocket endpoint for real-time pipeline run progress."""

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.common.database import async_session
from app.pipeline.models import PipelineRun, PipelineRunStatus
from app.pipeline.orchestrator import get_run_stats

logger = logging.getLogger(__name__)

_TERMINAL = {PipelineRunStatus.COMPLETED, PipelineRunStatus.FAILED, PipelineRunStatus.CANCELLED}


async def pipeline_progress_ws(websocket: WebSocket, project_id: str, run_id: str):
    """Stream pipeline run progress over WebSocket.

    Polls PatientTask aggregate counts every 1s and pushes updates.
    Closes when the run reaches a terminal state.
    """
    await websocket.accept()
    last_stats: dict = {}

    try:
        while True:
            async with async_session() as session:
                run = await session.get(PipelineRun, run_id)
                if not run or run.project_id != project_id:
                    await websocket.send_json({"type": "error", "detail": "Run not found"})
                    break

                stats = await get_run_stats(session, run_id)

            msg = {
                "type": "progress" if run.status not in _TERMINAL else run.status.value,
                "run_id": run.id,
                "status": run.status.value,
                "total_patients": run.total_patients,
                "processed_patients": run.processed_patients,
                "failed_patients": run.failed_patients,
                **stats,
            }

            if stats != last_stats or run.status in _TERMINAL:
                last_stats = stats
                await websocket.send_json(msg)

            if run.status in _TERMINAL:
                break

            await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
