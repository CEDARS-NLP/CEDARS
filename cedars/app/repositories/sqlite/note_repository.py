"""SQLite note repository implementation."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, and_

from app.models.note import Note
from app.models.notes_summary import NotesSummary
from app.repositories.interfaces.note_repository import NoteRepositoryInterface
from .database import session_scope
from .tables import NoteTable, NotesSummaryTable, AnnotationTable


class SQLiteNoteRepository(NoteRepositoryInterface):
    """SQLite implementation of note repository."""

    def _to_model(self, row: NoteTable) -> Note:
        """Convert SQLAlchemy row to Note model."""
        if row is None:
            return None
        return Note(
            id=str(row.id),
            text_id=row.text_id,
            patient_id=row.patient_id,
            text=row.text,
            text_date=row.text_date,
            reviewed=row.reviewed,
            reviewed_by=row.reviewed_by,
            text_tag_1=row.text_tag_1,
            text_tag_2=row.text_tag_2,
            text_tag_3=row.text_tag_3,
        )

    def _to_summary_model(self, row: NotesSummaryTable) -> NotesSummary:
        """Convert SQLAlchemy row to NotesSummary model."""
        if row is None:
            return None
        return NotesSummary(
            id=str(row.id),
            patient_id=row.patient_id,
            num_notes=row.num_notes,
            first_note_date=row.first_note_date,
            last_note_date=row.last_note_date,
        )

    def get_by_id(self, text_id: str) -> Optional[Note]:
        with session_scope() as session:
            row = session.query(NoteTable).filter_by(text_id=text_id).first()
            return self._to_model(row) if row else None

    def get_by_patient(self, patient_id: str) -> list[Note]:
        with session_scope() as session:
            rows = session.query(NoteTable).filter_by(patient_id=patient_id).all()
            return [self._to_model(row) for row in rows]

    def get_patient_notes_for_review(self, patient_id: str, reviewed: bool = False) -> list[Note]:
        with session_scope() as session:
            query = session.query(NoteTable).filter_by(patient_id=patient_id)
            if reviewed is not None:
                query = query.filter_by(reviewed=reviewed)
            rows = query.all()
            return [self._to_model(row) for row in rows]

    def get_note_date(self, text_id: str) -> Optional[datetime]:
        with session_scope() as session:
            row = session.query(NoteTable).filter_by(text_id=text_id).first()
            return row.text_date if row else None

    def count_by_patient(self, patient_id: str, reviewed: Optional[bool] = None) -> int:
        with session_scope() as session:
            query = session.query(func.count(NoteTable.id)).filter_by(patient_id=patient_id)
            if reviewed is not None:
                query = query.filter_by(reviewed=reviewed)
            return query.scalar()

    def count(self, **filters) -> int:
        with session_scope() as session:
            query = session.query(func.count(NoteTable.id))
            for key, value in filters.items():
                query = query.filter(getattr(NoteTable, key) == value)
            return query.scalar()

    def bulk_insert(self, notes: list[dict]) -> int:
        if not notes:
            return 0
        with session_scope() as session:
            for note_dict in notes:
                note = NoteTable(
                    text_id=note_dict.get("text_id"),
                    patient_id=note_dict.get("patient_id"),
                    text=note_dict.get("text", ""),
                    text_date=note_dict.get("text_date"),
                    reviewed=note_dict.get("reviewed", False),
                    text_tag_1=note_dict.get("text_tag_1"),
                    text_tag_2=note_dict.get("text_tag_2"),
                    text_tag_3=note_dict.get("text_tag_3"),
                )
                session.add(note)
            return len(notes)

    def mark_reviewed(self, text_id: str, reviewed_by: str) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(NoteTable)
                .filter_by(text_id=text_id)
                .update({"reviewed": True, "reviewed_by": reviewed_by})
            )
            return rows_updated > 0

    def batch_mark_reviewed(self, text_ids: list[str], reviewed_by: str) -> int:
        if not text_ids:
            return 0
        with session_scope() as session:
            rows_updated = (
                session.query(NoteTable)
                .filter(NoteTable.text_id.in_(text_ids))
                .update({"reviewed": True, "reviewed_by": reviewed_by}, synchronize_session=False)
            )
            return rows_updated

    def revert_reviewed(self, text_id: str, reviewed_by: str) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(NoteTable)
                .filter_by(text_id=text_id)
                .update({"reviewed": False, "reviewed_by": reviewed_by})
            )
            return rows_updated > 0

    def reset_all_reviewed(self) -> int:
        with session_scope() as session:
            rows_updated = session.query(NoteTable).update(
                {"reviewed": False, "reviewed_by": ""}
            )
            return rows_updated

    def get_documents_to_annotate(self, patient_id: Optional[str] = None) -> list[Note]:
        """Get notes that have no annotations and are not reviewed."""
        with session_scope() as session:
            # Subquery to get note_ids that have annotations
            annotated_notes = session.query(AnnotationTable.note_id).distinct()

            query = session.query(NoteTable).filter(
                and_(
                    ~NoteTable.text_id.in_(annotated_notes),
                    NoteTable.reviewed != True,
                )
            )

            if patient_id:
                query = query.filter_by(patient_id=patient_id)

            rows = query.all()
            return [self._to_model(row) for row in rows]

    def update_notes_summary(self) -> int:
        """Update/rebuild the notes summary cache."""
        with session_scope() as session:
            # Get aggregated stats per patient
            summaries = (
                session.query(
                    NoteTable.patient_id,
                    func.count(NoteTable.id).label("num_notes"),
                    func.min(NoteTable.text_date).label("first_note_date"),
                    func.max(NoteTable.text_date).label("last_note_date"),
                )
                .group_by(NoteTable.patient_id)
                .all()
            )

            # Clear existing summaries
            session.query(NotesSummaryTable).delete()

            # Insert new summaries
            for summary in summaries:
                ns = NotesSummaryTable(
                    patient_id=summary.patient_id,
                    num_notes=summary.num_notes,
                    first_note_date=summary.first_note_date,
                    last_note_date=summary.last_note_date,
                )
                session.add(ns)

            return len(summaries)

    def get_notes_summary(self) -> list[NotesSummary]:
        with session_scope() as session:
            rows = session.query(NotesSummaryTable).all()
            return [self._to_summary_model(row) for row in rows]

    def get_first_note_date(self, patient_id: str) -> Optional[datetime]:
        with session_scope() as session:
            row = session.query(NotesSummaryTable).filter_by(patient_id=patient_id).first()
            return row.first_note_date if row else None

    def get_last_note_date(self, patient_id: str) -> Optional[datetime]:
        with session_scope() as session:
            row = session.query(NotesSummaryTable).filter_by(patient_id=patient_id).first()
            return row.last_note_date if row else None

    def get_num_notes(self, patient_id: str) -> int:
        with session_scope() as session:
            row = session.query(NotesSummaryTable).filter_by(patient_id=patient_id).first()
            return row.num_notes if row else 0
