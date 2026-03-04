"""Export service: query annotations for export."""

import csv
import io

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.evaluation.models import EvaluationSession


async def get_export_stats(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Get counts for export preview."""
    base = select(func.count()).select_from(Annotation).where(
        Annotation.project_id == project_id
    )
    total = (await session.execute(base)).scalar() or 0
    reviewed = (
        await session.execute(
            base.where(Annotation.review_status == ReviewStatus.REVIEWED)
        )
    ).scalar() or 0
    events = (
        await session.execute(
            base.where(Annotation.event_date.isnot(None))
        )
    ).scalar() or 0

    # Sum token usage from evaluation sessions
    eval_stmt = select(EvaluationSession).where(
        EvaluationSession.project_id == project_id
    )
    eval_result = await session.execute(eval_stmt)
    total_eval_tokens = 0
    for es in eval_result.scalars().all():
        if es.metrics and isinstance(es.metrics, dict):
            tu = es.metrics.get("token_usage")
            if tu and isinstance(tu, dict):
                total_eval_tokens += tu.get("total_tokens", 0)

    return {"total": total, "reviewed": reviewed, "events": events, "total_eval_tokens": total_eval_tokens}


async def export_annotations(
    session: AsyncSession,
    project_id: str,
    status_filter: str | None = None,
) -> list[Annotation]:
    """Query annotations for export with optional status filter."""
    stmt = select(Annotation).where(Annotation.project_id == project_id)

    if status_filter == "reviewed":
        stmt = stmt.where(Annotation.review_status == ReviewStatus.REVIEWED)
    elif status_filter == "events":
        stmt = stmt.where(Annotation.event_date.isnot(None))

    stmt = stmt.order_by(Annotation.patient_id, Annotation.created_at)
    result = await session.execute(stmt)
    return list(result.scalars().all())


def format_csv(annotations: list[Annotation]) -> str:
    """Format annotations as CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        "patient_id",
        "note_id",
        "sentence_id",
        "sentence_text",
        "predicted_label",
        "predicted_score",
        "predictor_model",
        "reasoning",
        "review_status",
        "reviewed_by",
        "reviewed_at",
        "event_date",
    ]
    writer.writerow(headers)

    for ann in annotations:
        writer.writerow([
            ann.patient_id,
            ann.note_id,
            ann.sentence_id,
            ann.sentence_text,
            ann.predicted_label,
            ann.predicted_score,
            ann.predictor_model,
            ann.reasoning,
            ann.review_status.value if hasattr(ann.review_status, 'value') else ann.review_status,
            ann.reviewed_by or "",
            ann.reviewed_at.isoformat() if ann.reviewed_at else "",
            ann.event_date.isoformat() if ann.event_date else "",
        ])

    return output.getvalue()
