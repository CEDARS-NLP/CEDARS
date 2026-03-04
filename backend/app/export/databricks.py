"""Export project results to a Databricks table."""

import enum
import logging

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.annotations.models import Annotation, ReviewStatus
from app.connectors.databricks import connect_databricks, _fqn
from app.connectors.models import DataSource, Note

logger = logging.getLogger(__name__)


class ExportType(str, enum.Enum):
    ANNOTATIONS = "annotations"
    PREDICTIONS = "predictions"
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
                DataSource.id == data_source_id,
                DataSource.project_id == project_id,
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
    elif export_type == ExportType.EVALUATION:
        return await _fetch_evaluation_rows(session, project_id)
    return []


async def _fetch_annotation_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    stmt = (
        select(Annotation, Note.text_id)
        .join(Note, Annotation.note_id == Note.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.review_status != ReviewStatus.UNREVIEWED,
        )
    )
    result = await session.execute(stmt)
    rows = []
    for ann, text_id in result.all():
        rows.append((
            ann.patient_id,
            text_id,
            ann.sentence_text,
            ann.review_status.value,
            ann.event_date.isoformat() if ann.event_date else None,
            ann.reviewed_by or "",
            ann.reviewed_at.isoformat() if ann.reviewed_at else None,
        ))
    return rows


async def _fetch_prediction_rows(
    session: AsyncSession, project_id: str
) -> list[tuple]:
    stmt = (
        select(Annotation, Note.text_id)
        .join(Note, Annotation.note_id == Note.id)
        .where(
            Annotation.project_id == project_id,
            Annotation.predicted_label.isnot(None),
        )
    )
    result = await session.execute(stmt)
    rows = []
    for ann, text_id in result.all():
        rows.append((
            ann.patient_id,
            text_id,
            ann.sentence_text,
            ann.predictor_model,
            ann.predicted_score,
            ann.predicted_label,
            ann.reasoning,
        ))
    return rows


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
            judgment.judgment.value if hasattr(judgment.judgment, 'value') else str(judgment.judgment),
            predictor_config_id or "",
        ))
    return rows
