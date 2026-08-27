from __future__ import annotations

from loguru import logger
from datetime import date, datetime, timezone
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Double,
    String,
    Text,
)
from sqlalchemy import update
from sqlalchemy import select, func, insert

from cedars.app.database.db_search import get_notes_summary
from cedars.app.database.project_table_creation import Results
from cedars.app.database.project_table_creation import Notes, NotesSummary


def update_results_for_patient(project_engine, patient_id: str):
    """
    Update the results for a specific patient in the database.

    Args:
        project_engine: SQLAlchemy engine for the project database.
        patient_id (str): The ID of the patient whose results are to be updated.
    """
    updated_results = {
        "last_updated_at": datetime.now(timezone.utc),
    }

    note_summary = get_notes_summary(project_engine, patient_id)
    updated_results['first_note_date'] = note_summary.min_note_date
    updated_results['last_note_date'] = note_summary.max_note_date
    updated_results['total_notes'] = note_summary.num_notes

    with project_engine.connect() as conn:
        update_stmt = (
            update(Results)
            .where(Results.patient_id == patient_id)
            .values(**updated_results)
        )
        conn.execute(update_stmt)
        conn.commit()
    
    logger.info(f"Successfully updated results for patient {patient_id}.")


def update_notes_summary(project_engine):
    with project_engine.connect() as conn:
        agg = select(
            Notes.patient_id.label("patient_id"),
            func.min(Notes.note_date).label("min_note_date"),
            func.max(Notes.note_date).label("max_note_date"),
            func.count().label("num_notes"),
        ).group_by(Notes.patient_id)

        stmt = insert(NotesSummary).from_select(
            ["patient_id", "min_note_date", "max_note_date", "num_notes"],
            agg,
        )
        conn.execute(stmt)