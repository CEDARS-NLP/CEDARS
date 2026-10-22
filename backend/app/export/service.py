"""Export service: query annotations for export."""

import csv
import io
import json

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation
from app.connectors.models import Note, Patient
from app.evaluation.models import EvaluationSession
from app.production.models import NotePrediction, ProductionResult, ProductionState


async def get_export_stats(
    session: AsyncSession,
    project_id: str,
) -> dict:
    """Get counts for export preview."""
    base = select(func.count()).select_from(Annotation).where(
        Annotation.project_id == project_id
    )
    total = (await session.execute(base)).scalar() or 0
    reviewed = (await session.execute(base.where(Annotation.status == "R"))).scalar() or 0
    events = (
        await session.execute(
            select(func.count())
            .select_from(Patient)
            .where(Patient.project_id == project_id, Patient.event_annotation_id.isnot(None))
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

    return {"total": total, "reviewed": reviewed,
            "events": events, "total_eval_tokens": total_eval_tokens}


async def export_annotations(
    session: AsyncSession,
    project_id: str,
    status_filter: str | None = None,
) -> list[dict]:
    """Query annotations for export with optional status filter.

    Production verdicts are joined by external note identity. Canonical event
    fields are emitted only for the annotation linked from its patient.
    """
    state = await session.get(ProductionState, project_id)
    join_conditions = [
        NotePrediction.project_id == Annotation.project_id,
        NotePrediction.text_id == Annotation.text_id,
        NotePrediction.patient_id == Annotation.patient_id,
    ]
    if state and state.active_run_id:
        join_conditions.append(NotePrediction.run_id == state.active_run_id)
    else:
        join_conditions.append(NotePrediction.run_id == "")
    stmt = (
        select(Annotation, NotePrediction, Patient, Note)
        .outerjoin(NotePrediction, and_(*join_conditions))
        .outerjoin(
            Patient,
            and_(Patient.id == Annotation.patient_uuid, Patient.project_id == Annotation.project_id),
        )
        .outerjoin(Note, Note.id == Annotation.note_uuid)
        .where(Annotation.project_id == project_id)
    )

    if status_filter == "reviewed":
        stmt = stmt.where(Annotation.status == "R")
    elif status_filter == "events":
        stmt = stmt.where(Patient.event_annotation_id == Annotation.annotation_id)

    stmt = stmt.order_by(Annotation.patient_id, Annotation.text_date, Annotation.annotation_id)
    rows = (await session.execute(stmt)).all()

    return [
        {
            "annotation_id": ann.annotation_id,
            "predictor_config_id": None,
            "patient_id": ann.patient_id,
            "note_id": note.id if note else (ann.note_uuid or ann.text_id),
            "sentence_id": None,
            "sentence_text": ann.sentence,
            "token": ann.token,
            "is_negated": ann.isNegated,
            "review_excluded": ann.review_reason in {"llm_negative", "duplicate", "negated"},
            "manual_review_override": False,
            "note_start_index": ann.note_start_index,
            "note_end_index": ann.note_end_index,
            "sentence_number": ann.sentence_number,
            "sentence_start": ann.sentence_start,
            "sentence_end": ann.sentence_end,
            "text_date": ann.text_date,
            "predicted_label": pred.label if pred else None,
            "predicted_score": pred.score if pred else None,
            "predictor_model": pred.model_fingerprint if pred else "",
            "reasoning": (pred.reasoning if pred else "") or "",
            "review_status": getattr(ann.review_status, "value", ann.review_status),
            "reviewed_by": ann.reviewed_by,
            "reviewed_at": ann.reviewed_at,
            "event_date": (
                patient.event_date
                if patient and patient.event_annotation_id == ann.annotation_id
                else None
            ),
            "patient_review_source": patient.review_source if patient else None,
            "patient_review_reason": patient.review_reason if patient else None,
            "patient_reviewed_by": patient.reviewed_by if patient else None,
            "patient_reviewed_at": patient.reviewed_at if patient else None,
        }
        for ann, pred, patient, note in rows
    ]


async def export_results(session: AsyncSession, project_id: str) -> list[dict]:
    """Export the patient-level RESULTS projection with canonical event truth."""
    stmt = (
        select(ProductionResult, Patient)
        .join(Patient, Patient.id == ProductionResult.patient_uuid)
        .where(
            ProductionResult.project_id == project_id,
            Patient.project_id == project_id,
            Patient.deleted_at.is_(None),
        )
        .order_by(ProductionResult.index_no, ProductionResult.patient_id)
    )
    rows = (await session.execute(stmt)).all()
    exported = []
    for result, patient in rows:
        row = result.model_dump()
        row.update(
            {
                "patient_id": patient.patient_id_ext,
                "event_date": patient.event_date,
                "event_annotation_id": patient.event_annotation_id,
                "event_information": (
                    {
                        "event_date": patient.event_date.isoformat(),
                        "annotation_id": patient.event_annotation_id,
                        "reviewer": patient.event_reviewer,
                    }
                    if patient.event_date and patient.event_annotation_id
                    else None
                ),
                "reviewer": patient.event_reviewer or result.reviewer,
            }
        )
        exported.append(row)
    return exported


_CSV_HEADERS = [
    "annotation_id",
    "predictor_config_id",
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
_RESULT_CSV_HEADERS = [
    "project_id", "patient_uuid", "patient_id", "index_no", "processing_status",
    "review_status", "comments", "event_information", "event_date",
    "event_annotation_id", "first_note_date", "last_note_date", "max_score",
    "max_score_note_date", "max_score_note_id", "reviewer", "reviewed_notes",
    "reviewed_sentences", "total_notes", "total_sentences", "notes_total",
    "notes_processed", "notes_failed", "annotations_total", "annotations_pending",
    "annotations_reviewed", "annotations_skipped", "reason_counts", "failure_count",
    "last_error", "last_updated_at",
]
_RESULT_DATE_FIELDS = {
    "event_date", "first_note_date", "last_note_date", "max_score_note_date",
    "last_updated_at", "updated_at",
}


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


def format_results_csv(results: list[dict]) -> str:
    """Format patient RESULTS export rows as CSV."""
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(_RESULT_CSV_HEADERS)
    for result in results:
        row = []
        for field in _RESULT_CSV_HEADERS:
            value = result.get(field)
            if field in _RESULT_DATE_FIELDS:
                value = value.isoformat() if value else ""
            elif field in {"event_information", "reason_counts"} and value is not None:
                value = json.dumps(value, sort_keys=True)
            row.append("" if value is None else value)
        writer.writerow(row)
    return output.getvalue()
