"""Export service: query annotations for export."""

import csv
import io

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, AnnotationPrediction, ReviewStatus
from app.connectors.models import Patient
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
) -> list[dict]:
    """Query annotations for export with optional status filter.

    Predictor verdicts, when present, are merged in from annotation_predictions.
    """
    stmt = (
        select(Annotation, AnnotationPrediction, Patient)
        .outerjoin(
            AnnotationPrediction, AnnotationPrediction.annotation_id == Annotation.id
        )
        .join(Patient, Patient.id == Annotation.patient_id)
        .where(Annotation.project_id == project_id)
    )

    if status_filter == "reviewed":
        stmt = stmt.where(Annotation.review_status == ReviewStatus.REVIEWED)
    elif status_filter == "events":
        stmt = stmt.where(Annotation.event_date.isnot(None))

    stmt = stmt.order_by(Annotation.patient_id, Annotation.created_at)
    rows = (await session.execute(stmt)).all()

    return [
        {
            "patient_id": ann.patient_id,
            "note_id": ann.note_id,
            "sentence_id": ann.sentence_id,
            "sentence_text": ann.sentence_text,
            "token": ann.token,
            "is_negated": ann.is_negated,
            "review_excluded": ann.review_excluded,
            "manual_review_override": ann.manual_review_override,
            "note_start_index": ann.note_start_index,
            "note_end_index": ann.note_end_index,
            "sentence_number": ann.sentence_number,
            "sentence_start": ann.sentence_start,
            "sentence_end": ann.sentence_end,
            "text_date": ann.text_date,
            "predicted_label": pred.predicted_label if pred else ann.predicted_label,
            "predicted_score": pred.predicted_score if pred else ann.predicted_score,
            "predictor_model": pred.predictor_model if pred else ann.predictor_model,
            "reasoning": (pred.reasoning if pred else ann.reasoning) or "",
            "review_status": getattr(ann.review_status, "value", ann.review_status),
            "reviewed_by": ann.reviewed_by,
            "reviewed_at": ann.reviewed_at,
            "event_date": ann.event_date,
            "patient_review_source": patient.review_source,
            "patient_review_reason": patient.review_reason,
            "patient_reviewed_by": patient.reviewed_by,
            "patient_reviewed_at": patient.reviewed_at,
        }
        for ann, pred, patient in rows
    ]


_CSV_HEADERS = [
    "patient_id",
    "note_id",
    "sentence_id",
    "sentence_text",
    "token",
    "is_negated",
    "review_excluded",
    "manual_review_override",
    "note_start_index",
    "note_end_index",
    "sentence_number",
    "sentence_start",
    "sentence_end",
    "text_date",
    "predicted_label",
    "predicted_score",
    "predictor_model",
    "reasoning",
    "review_status",
    "reviewed_by",
    "reviewed_at",
    "event_date",
    "patient_review_source",
    "patient_review_reason",
    "patient_reviewed_by",
    "patient_reviewed_at",
]

_CSV_DATE_FIELDS = ("text_date", "reviewed_at", "event_date", "patient_reviewed_at")


def format_csv(annotations: list[dict]) -> str:
    """Format annotation export rows as a CSV string."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_CSV_HEADERS)

    for ann in annotations:
        row = []
        for field in _CSV_HEADERS:
            value = ann.get(field)
            if field in _CSV_DATE_FIELDS:
                value = value.isoformat() if value else ""
            row.append("" if value is None else value)
        writer.writerow(row)

    return output.getvalue()
