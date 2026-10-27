"""Export project results to a Databricks table."""

import enum
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.annotations.models import Annotation
from app.connectors.databricks import _fqn, connect_databricks
from app.connectors.models import DataSource, Note, Patient
from app.production.models import NotePrediction, ProductionState

logger = logging.getLogger(__name__)


class ExportType(str, enum.Enum):
    ANNOTATIONS = "annotations"
    PREDICTIONS = "predictions"
    RESULTS = "results"
    EVALUATION = "evaluation"


SCHEMAS = {
    ExportType.ANNOTATIONS: [
        ("patient_id", "STRING"),
        ("text_id", "STRING"),
        ("sentence_text", "STRING"),
        ("review_status", "STRING"),
        ("event_date", "STRING"),
        ("reviewer", "STRING"),
        ("reviewed_at", "STRING"),
    ],
    ExportType.PREDICTIONS: [
        ("patient_id", "STRING"),
        ("text_id", "STRING"),
        ("sentence_text", "STRING"),
        ("predictor_name", "STRING"),
        ("score", "DOUBLE"),
        ("label", "INT"),
        ("reasoning", "STRING"),
    ],
    ExportType.RESULTS: [
        ("project_id", "STRING"),
        ("patient_uuid", "STRING"),
        ("patient_id", "STRING"),
        ("index_no", "INT"),
        ("processing_status", "STRING"),
        ("review_status", "STRING"),
        ("comments", "STRING"),
        ("event_information", "STRING"),
        ("event_date", "STRING"),
        ("event_annotation_id", "INT"),
        ("first_note_date", "STRING"),
        ("last_note_date", "STRING"),
        ("max_score", "DOUBLE"),
        ("max_score_note_date", "STRING"),
        ("max_score_note_id", "STRING"),
        ("reviewer", "STRING"),
        ("reviewed_notes", "INT"),
        ("reviewed_sentences", "INT"),
        ("total_notes", "INT"),
        ("total_sentences", "INT"),
        ("notes_total", "INT"),
        ("notes_processed", "INT"),
        ("notes_failed", "INT"),
        ("annotations_total", "INT"),
        ("annotations_pending", "INT"),
        ("annotations_reviewed", "INT"),
        ("annotations_skipped", "INT"),
        ("reason_counts", "STRING"),
        ("failure_count", "INT"),
        ("last_error", "STRING"),
        ("last_updated_at", "STRING"),
    ],
    ExportType.EVALUATION: [
        ("session_name", "STRING"),
        ("note_id", "STRING"),
        ("predicted_label", "INT"),
        ("human_judgment", "STRING"),
        ("predictor_config_id", "STRING"),
    ],
}


async def export_to_databricks(
    session: AsyncSession,
    project_id: str,
    data_source_id: str,
    target_table: str,
    export_type: ExportType,
) -> int:
    """Export project data to a Databricks table.

    Uses the connection config from the specified data source.
    Returns the number of rows exported.
    """
    ds = (
        await session.execute(
            select(DataSource).where(
                col(DataSource.id) == data_source_id,
                col(DataSource.project_id) == project_id,
            )
        )
    ).scalar_one_or_none()

    if not ds:
        raise ValueError("Data source not found")

    config = ds.config
    export_config = {**config, "table": target_table}

    rows = await _fetch_export_rows(session, project_id, export_type)
    if not rows:
        return 0

    schema = SCHEMAS[export_type]
    conn = connect_databricks(export_config)
    try:
        cursor = conn.cursor()

        col_defs = ", ".join(f"`{name}` {dtype}" for name, dtype in schema)
        fqn = _fqn(export_config)
        cursor.execute(f"CREATE TABLE IF NOT EXISTS {fqn} ({col_defs})")

        col_names = ", ".join(f"`{name}`" for name, _ in schema)
        placeholders = ", ".join("?" for _ in schema)
        insert_sql = f"INSERT INTO {fqn} ({col_names}) VALUES ({placeholders})"

        batch_size = 1000
        for i in range(0, len(rows), batch_size):
            batch = rows[i : i + batch_size]
            for row in batch:
                cursor.execute(insert_sql, row)

        cursor.close()
    finally:
        conn.close()

    return len(rows)


async def _fetch_export_rows(
    session: AsyncSession,
    project_id: str,
    export_type: ExportType,
) -> list[tuple]:
    """Fetch rows from PostgreSQL for export."""
    if export_type == ExportType.ANNOTATIONS:
        return await _fetch_annotation_rows(session, project_id)
    elif export_type == ExportType.PREDICTIONS:
        return await _fetch_prediction_rows(session, project_id)
    elif export_type == ExportType.RESULTS:
        return await _fetch_result_rows(session, project_id)
    elif export_type == ExportType.EVALUATION:
        return await _fetch_evaluation_rows(session, project_id)
    return []


async def _fetch_annotation_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    stmt = (
        select(Annotation, Patient)
        .join(Patient, col(Patient.id) == col(Annotation.patient_uuid))
        .where(
            col(Annotation.project_id) == project_id,
            col(Annotation.status) != "U",
        )
    )
    result = await session.execute(stmt)
    rows = []
    for ann, patient in result.all():
        rows.append((
            ann.patient_id,
            ann.text_id,
            ann.sentence,
            {"U": "unreviewed", "R": "reviewed", "S": "skipped"}[ann.status],
            patient.event_date.isoformat()
            if patient.event_annotation_id == ann.annotation_id and patient.event_date
            else None,
            ann.reviewed_by or "",
            ann.reviewed_at.isoformat() if ann.reviewed_at else None,
        ))
    return rows


async def _fetch_prediction_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    state = await session.get(ProductionState, project_id)
    if not state or not state.active_run_id:
        return []
    stmt = (
        select(NotePrediction, col(Note.text))
        .join(Note, col(Note.id) == col(NotePrediction.note_uuid))
        .where(
            col(NotePrediction.project_id) == project_id,
            col(NotePrediction.run_id) == state.active_run_id,
            col(NotePrediction.label).isnot(None),
        )
    )
    result = await session.execute(stmt)
    return [
        (
            prediction.patient_id,
            prediction.text_id,
            note_text,
            prediction.model_fingerprint or "",
            prediction.score,
            prediction.label,
            prediction.reasoning or "",
        )
        for prediction, note_text in result.all()
    ]


async def _fetch_result_rows(session: AsyncSession, project_id: str) -> list[tuple]:
    import json

    from app.export.service import export_results

    rows = await export_results(session, project_id)
    date_fields = {
        "event_date", "first_note_date", "last_note_date", "max_score_note_date",
        "last_updated_at",
    }
    json_fields = {"event_information", "reason_counts"}
    headers = [name for name, _ in SCHEMAS[ExportType.RESULTS]]
    return [
        tuple(
            value.isoformat() if name in date_fields and value else
            json.dumps(value, sort_keys=True) if name in json_fields and value is not None else
            value
            for name, value in ((name, row.get(name)) for name in headers)
        )
        for row in rows
    ]

async def _fetch_evaluation_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    from app.evaluation.models import EvaluationJudgment, EvaluationSession

    stmt = (
        select(EvaluationJudgment, EvaluationSession.name, EvaluationSession.predictor_config_id)
        .join(EvaluationSession, EvaluationJudgment.session_id == EvaluationSession.id)
        .where(EvaluationSession.project_id == project_id)
    )
    result = await session.execute(stmt)
    rows = []
    for judgment, session_name, predictor_config_id in result.all():
        rows.append((
            session_name,
            judgment.note_id,
            judgment.predicted_label,
            judgment.judgment.value if hasattr(judgment.judgment,
                                               'value') else str(judgment.judgment),
            predictor_config_id or "",
        ))
    return rows
