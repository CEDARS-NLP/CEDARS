"""WebSocket endpoint for real-time pipeline progress on evaluation sessions."""

import asyncio
import logging

from fastapi import WebSocket, WebSocketDisconnect

from app.common.database import async_session
from app.evaluation.models import EvaluationSession, SessionStatus

logger = logging.getLogger(__name__)


async def eval_pipeline_progress_ws(websocket: WebSocket, project_id: str, session_id: str):
    """Stream full pipeline run progress for a committed evaluation session.

    Polls PatientResult aggregate counts every 1s and pushes updates.
    Closes when the session reaches COMPLETED state or all work is done.
    """
    await websocket.accept()
    last_stats: dict = {}

    try:
        async with async_session() as db:
            while True:
                eval_sess = await db.get(EvaluationSession, session_id)
                if not eval_sess or eval_sess.project_id != project_id:
                    await websocket.send_json({"type": "error", "detail": "Session not found"})
                    break

                # Expire the cached instance so the next get() fetches fresh data
                db.expire(eval_sess)

                if eval_sess.status not in (SessionStatus.COMMITTED, SessionStatus.COMPLETED):
                    await websocket.send_json({
                        "type": "status",
                        "session_status": eval_sess.status.value,
                    })
                    break

                from app.evaluation.service import get_pipeline_stats

                try:
                    stats = await get_pipeline_stats(db, session_id)
                except ValueError:
                    await websocket.send_json({"type": "error", "detail": "No pipeline run found"})
                    break

                msg = {"type": "progress", "session_id": session_id, **stats}

                if stats != last_stats:
                    last_stats = stats
                    await websocket.send_json(msg)

                # Check if done
                if stats.get("queued", 0) == 0 and stats.get("processing", 0) == 0:
                    msg["type"] = "completed"
                    await websocket.send_json(msg)
                    break

                await asyncio.sleep(1)
    except WebSocketDisconnect:
        pass
    finally:
        try:
            await websocket.close()
        except Exception:
            pass
