"""SQLite patient repository implementation."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func
from sqlalchemy.dialects.sqlite import insert

from app.models.patient import Patient
from app.repositories.interfaces.patient_repository import PatientRepositoryInterface
from .database import session_scope
from .tables import PatientTable


class SQLitePatientRepository(PatientRepositoryInterface):
    """SQLite implementation of patient repository."""

    def _to_model(self, row: PatientTable) -> Patient:
        """Convert SQLAlchemy row to Patient model."""
        if row is None:
            return None
        return Patient(
            id=str(row.id),
            patient_id=row.patient_id,
            reviewed=row.reviewed,
            locked=row.locked,
            updated=row.updated,
            comments=row.comments or "",
            reviewed_by=row.reviewed_by,
            event_date=row.event_date,
            event_annotation_id=str(row.event_annotation_id) if row.event_annotation_id else None,
            admin_locked=row.admin_locked,
            index_no=row.index_no,
        )

    def get_by_id(self, patient_id: str) -> Optional[Patient]:
        with session_scope() as session:
            row = session.query(PatientTable).filter_by(patient_id=patient_id).first()
            return self._to_model(row) if row else None

    def get_next_unreviewed(self) -> Optional[Patient]:
        with session_scope() as session:
            row = (
                session.query(PatientTable)
                .filter_by(reviewed=False, locked=False)
                .order_by(PatientTable.index_no)
                .first()
            )
            return self._to_model(row) if row else None

    def get_all_ids(self, reviewed_only: bool = False) -> list[str]:
        with session_scope() as session:
            query = session.query(PatientTable.patient_id)
            if reviewed_only:
                query = query.filter_by(reviewed=True)
            rows = query.order_by(PatientTable.index_no).all()
            return [row.patient_id for row in rows]

    def get_unreviewed_ids(self) -> list[str]:
        with session_scope() as session:
            rows = (
                session.query(PatientTable.patient_id)
                .filter_by(reviewed=False, locked=False)
                .order_by(PatientTable.index_no)
                .all()
            )
            return [row.patient_id for row in rows]

    def count(self) -> int:
        with session_scope() as session:
            return session.query(func.count(PatientTable.id)).scalar()

    def bulk_upsert(self, patient_ids: set[str], start_index: int = 0) -> int:
        with session_scope() as session:
            existing_count = session.query(func.count(PatientTable.id)).scalar()

            new_count = 0
            for i, p_id in enumerate(patient_ids):
                # Check if exists
                existing = session.query(PatientTable).filter_by(patient_id=p_id).first()
                if not existing:
                    patient = PatientTable(
                        patient_id=p_id,
                        reviewed=False,
                        locked=False,
                        updated=False,
                        comments="",
                        index_no=existing_count + start_index + i,
                    )
                    session.add(patient)
                    new_count += 1

            return new_count

    def mark_reviewed(self, patient_id: str, reviewed_by: str, is_reviewed: bool = True) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(PatientTable)
                .filter_by(patient_id=patient_id)
                .update({"reviewed": is_reviewed, "reviewed_by": reviewed_by})
            )
            return rows_updated > 0

    def set_lock_status(self, patient_id: str, locked: bool) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(PatientTable)
                .filter_by(patient_id=patient_id)
                .update({"locked": locked})
            )
            return rows_updated > 0

    def remove_all_locks(self) -> int:
        with session_scope() as session:
            rows_updated = session.query(PatientTable).update({"locked": False})
            return rows_updated

    def set_event_date(self, patient_id: str, event_date: Optional[datetime]) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(PatientTable)
                .filter_by(patient_id=patient_id)
                .update({"event_date": event_date})
            )
            return rows_updated > 0

    def set_event_annotation_id(self, patient_id: str, annotation_id: Optional[str]) -> bool:
        with session_scope() as session:
            ann_id = int(annotation_id) if annotation_id else None
            rows_updated = (
                session.query(PatientTable)
                .filter_by(patient_id=patient_id)
                .update({"event_annotation_id": ann_id})
            )
            return rows_updated > 0

    def add_comment(self, patient_id: str, comment: str) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(PatientTable)
                .filter_by(patient_id=patient_id)
                .update({"comments": comment})
            )
            return rows_updated > 0

    def get_reviewer(self, patient_id: str) -> Optional[str]:
        with session_scope() as session:
            row = session.query(PatientTable).filter_by(patient_id=patient_id).first()
            return row.reviewed_by if row else None

    def reset_all_reviewed(self) -> int:
        with session_scope() as session:
            rows_updated = session.query(PatientTable).update(
                {
                    "reviewed": False,
                    "reviewed_by": "",
                    "event_annotation_id": None,
                    "event_date": None,
                    "comments": "",
                }
            )
            return rows_updated
