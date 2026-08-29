"""Shared SQLAlchemy test helpers: seed/inspect a project's database directly,
bypassing the app layer, for setting up test fixtures.
"""
from datetime import date, datetime

from sqlalchemy import insert, select
from sqlalchemy.orm import Session

from app import database
from app.database.project_table_creation import Annotations, Notes, Patients


def get_patient(project_id, patient_id):
    """Fetch a Patients row directly, for test assertions."""
    engine = database.get_project_engine(project_id)
    with Session(engine) as session:
        return session.execute(
            select(Patients).where(Patients.patient_id == patient_id)
        ).scalar_one_or_none()


def seed_patient(project_id, patient_id, index_no=0, reviewed=False,
                 last_reviewed_by=None, locked=False):
    """Insert a minimal Patients row."""
    engine = database.get_project_engine(project_id)
    with engine.begin() as conn:
        conn.execute(insert(Patients).values(
            patient_id=patient_id, admin_locked=False, comments="", index_no=index_no,
            locked=locked, reviewed=reviewed, last_reviewed_by=last_reviewed_by,
            updated=False))


def seed_note(project_id, text_id, patient_id, text, text_date: date, **extra_columns):
    """Insert a minimal Notes row."""
    engine = database.get_project_engine(project_id)
    values = {"text_id": text_id, "patient_id": patient_id, "text": text,
             "text_date": text_date, "reviewed": False}
    values.update(extra_columns)
    with engine.begin() as conn:
        conn.execute(insert(Notes).values(**values))


def seed_annotation(project_id, text_id, patient_id, text_date: date, sentence, token,
                    note_start_index=0, note_end_index=0, sentence_number=0,
                    is_negated=False, status=Annotations.STATUS_UNREVIEWED):
    """Insert an Annotations row; returns the new annotation_id."""
    engine = database.get_project_engine(project_id)
    with engine.begin() as conn:
        result = conn.execute(insert(Annotations).values(
            text_id=text_id, patient_id=patient_id, text_date=text_date,
            sentence=sentence, token=token, isNegated=is_negated,
            note_start_index=note_start_index, note_end_index=note_end_index,
            sentence_number=sentence_number, sentence_start=0, sentence_end=len(sentence),
            status=status))
        return result.inserted_primary_key[0]
