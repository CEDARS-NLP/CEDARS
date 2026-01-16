"""SQLite annotation repository implementation."""

from datetime import datetime
from typing import Optional

from sqlalchemy import func, and_

from app.models.annotation import Annotation
from app.repositories.interfaces.annotation_repository import AnnotationRepositoryInterface
from .database import session_scope
from .tables import AnnotationTable, NoteTable


# Review status constants
UNREVIEWED = 0
REVIEWED = 1
SKIPPED = 2


class SQLiteAnnotationRepository(AnnotationRepositoryInterface):
    """SQLite implementation of annotation repository."""

    def _to_model(self, row: AnnotationTable) -> Annotation:
        """Convert SQLAlchemy row to Annotation model."""
        if row is None:
            return None
        return Annotation(
            id=str(row.id),
            patient_id=row.patient_id,
            note_id=row.note_id,
            sentence=row.sentence,
            token=row.token,
            is_negated=row.is_negated,
            note_start_index=row.note_start_index,
            note_end_index=row.note_end_index,
            sentence_number=row.sentence_number,
            sentence_start=row.sentence_start,
            sentence_end=row.sentence_end,
            text_date=row.text_date,
            reviewed=row.reviewed,
        )

    def get_by_id(self, annotation_id: str) -> Optional[Annotation]:
        with session_scope() as session:
            row = session.query(AnnotationTable).filter_by(id=int(annotation_id)).first()
            return self._to_model(row) if row else None

    def get_note_for_annotation(self, annotation_id: str) -> Optional[dict]:
        with session_scope() as session:
            annotation = session.query(AnnotationTable).filter_by(id=int(annotation_id)).first()
            if not annotation:
                return None
            note = session.query(NoteTable).filter_by(text_id=annotation.note_id).first()
            if not note:
                return None
            return {
                "text_id": note.text_id,
                "patient_id": note.patient_id,
                "text": note.text,
                "text_date": note.text_date,
            }

    def get_by_note(self, note_id: str, include_negated: bool = False) -> list[Annotation]:
        with session_scope() as session:
            query = session.query(AnnotationTable).filter_by(note_id=note_id)
            if not include_negated:
                query = query.filter_by(is_negated=False)
            rows = query.order_by(AnnotationTable.text_date, AnnotationTable.sentence_number).all()
            return [self._to_model(row) for row in rows]

    def get_by_sentence(self, note_id: str, sentence_number: int) -> list[Annotation]:
        with session_scope() as session:
            rows = (
                session.query(AnnotationTable)
                .filter_by(note_id=note_id, sentence_number=sentence_number, is_negated=False)
                .order_by(AnnotationTable.text_date, AnnotationTable.note_start_index)
                .all()
            )
            return [self._to_model(row) for row in rows]

    def get_by_patient(self, patient_id: str, include_negated: bool = False) -> list[Annotation]:
        with session_scope() as session:
            query = session.query(AnnotationTable).filter_by(patient_id=patient_id)
            if not include_negated:
                query = query.filter_by(is_negated=False)
            rows = query.order_by(
                AnnotationTable.text_date,
                AnnotationTable.note_id,
                AnnotationTable.note_start_index,
            ).all()
            return [self._to_model(row) for row in rows]

    def get_patient_annotation_ids(
        self, patient_id: str, reviewed_status: int = 0, key: str = "_id"
    ) -> list[str]:
        with session_scope() as session:
            query = (
                session.query(AnnotationTable)
                .filter_by(patient_id=patient_id, is_negated=False, reviewed=reviewed_status)
                .order_by(
                    AnnotationTable.note_id,
                    AnnotationTable.text_date,
                    AnnotationTable.sentence_number,
                )
            )
            rows = query.all()
            if key == "_id":
                return [str(row.id) for row in rows]
            return [getattr(row, key) for row in rows]

    def get_annotations_post_event(
        self, patient_id: str, event_date: datetime
    ) -> list[Annotation]:
        with session_scope() as session:
            rows = (
                session.query(AnnotationTable)
                .filter(
                    and_(
                        AnnotationTable.patient_id == patient_id,
                        AnnotationTable.text_date >= event_date,
                        AnnotationTable.reviewed == UNREVIEWED,
                    )
                )
                .all()
            )
            return [self._to_model(row) for row in rows]

    def insert_one(self, annotation: dict) -> str:
        with session_scope() as session:
            ann = AnnotationTable(
                patient_id=annotation.get("patient_id"),
                note_id=annotation.get("note_id"),
                sentence=annotation.get("sentence", ""),
                token=annotation.get("token", ""),
                is_negated=annotation.get("isNegated", False),
                note_start_index=annotation.get("note_start_index", 0),
                note_end_index=annotation.get("note_end_index", 0),
                sentence_number=annotation.get("sentence_number", 0),
                sentence_start=annotation.get("sentence_start", 0),
                sentence_end=annotation.get("sentence_end", 0),
                text_date=annotation.get("text_date"),
                reviewed=annotation.get("reviewed", UNREVIEWED),
            )
            session.add(ann)
            session.flush()  # Get the ID
            return str(ann.id)

    def get_all(self) -> list[Annotation]:
        with session_scope() as session:
            rows = session.query(AnnotationTable).all()
            return [self._to_model(row) for row in rows]

    def count(self, include_negated: bool = True) -> int:
        with session_scope() as session:
            query = session.query(func.count(AnnotationTable.id))
            if not include_negated:
                query = query.filter_by(is_negated=False)
            return query.scalar()

    def mark_reviewed(self, annotation_id: str) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(AnnotationTable)
                .filter_by(id=int(annotation_id))
                .update({"reviewed": REVIEWED})
            )
            return rows_updated > 0

    def batch_mark_reviewed(self, annotation_ids: list[str]) -> int:
        if not annotation_ids:
            return 0
        with session_scope() as session:
            int_ids = [int(aid) for aid in annotation_ids]
            rows_updated = (
                session.query(AnnotationTable)
                .filter(AnnotationTable.id.in_(int_ids))
                .update({"reviewed": REVIEWED}, synchronize_session=False)
            )
            return rows_updated

    def revert_reviewed(self, annotation_id: str) -> bool:
        with session_scope() as session:
            rows_updated = (
                session.query(AnnotationTable)
                .filter_by(id=int(annotation_id))
                .update({"reviewed": UNREVIEWED})
            )
            return rows_updated > 0

    def mark_skipped_post_event(self, patient_id: str, event_date: datetime) -> int:
        with session_scope() as session:
            rows_updated = (
                session.query(AnnotationTable)
                .filter(
                    and_(
                        AnnotationTable.patient_id == patient_id,
                        AnnotationTable.text_date >= event_date,
                        AnnotationTable.reviewed == UNREVIEWED,
                    )
                )
                .update({"reviewed": SKIPPED}, synchronize_session=False)
            )
            return rows_updated

    def revert_skipped(self, patient_id: str) -> int:
        with session_scope() as session:
            rows_updated = (
                session.query(AnnotationTable)
                .filter_by(patient_id=patient_id, reviewed=SKIPPED)
                .update({"reviewed": UNREVIEWED}, synchronize_session=False)
            )
            return rows_updated

    def update_note_review_status(self, annotation_id: str, reviewed_by: str) -> dict:
        """Check if all annotations for a note are reviewed and update note status."""
        with session_scope() as session:
            annotation = session.query(AnnotationTable).filter_by(id=int(annotation_id)).first()
            if not annotation:
                return {"note_reviewed": False, "patient_reviewed": False}

            note_id = annotation.note_id
            patient_id = annotation.patient_id

            # Check if any unreviewed annotations remain
            unreviewed_count = (
                session.query(func.count(AnnotationTable.id))
                .filter_by(note_id=note_id, reviewed=UNREVIEWED)
                .scalar()
            )

            note_reviewed = unreviewed_count == 0
            if note_reviewed:
                session.query(NoteTable).filter_by(text_id=note_id).update(
                    {"reviewed": True, "reviewed_by": reviewed_by}
                )

            return {
                "note_reviewed": note_reviewed,
                "patient_reviewed": False,
                "note_id": note_id,
                "patient_id": patient_id,
            }

    def batch_update_note_review_status(
        self, annotation_ids: list[str], reviewed_by: str
    ) -> dict:
        """Batch check and update note review status."""
        if not annotation_ids:
            return {"notes_reviewed": [], "patient_reviewed": False}

        with session_scope() as session:
            int_ids = [int(aid) for aid in annotation_ids]
            annotations = session.query(AnnotationTable).filter(AnnotationTable.id.in_(int_ids)).all()

            note_ids = list(set(a.note_id for a in annotations))

            reviewed_notes = []
            for note_id in note_ids:
                unreviewed_count = (
                    session.query(func.count(AnnotationTable.id))
                    .filter_by(note_id=note_id, reviewed=UNREVIEWED)
                    .scalar()
                )
                if unreviewed_count == 0:
                    reviewed_notes.append(note_id)

            if reviewed_notes:
                session.query(NoteTable).filter(NoteTable.text_id.in_(reviewed_notes)).update(
                    {"reviewed": True, "reviewed_by": reviewed_by}, synchronize_session=False
                )

            return {"notes_reviewed": reviewed_notes, "patient_reviewed": False}

    def mark_all_in_note_reviewed(self, note_id: str) -> int:
        with session_scope() as session:
            rows_updated = (
                session.query(AnnotationTable)
                .filter_by(note_id=note_id)
                .update({"reviewed": REVIEWED}, synchronize_session=False)
            )
            return rows_updated

    def delete_all(self) -> int:
        with session_scope() as session:
            rows_deleted = session.query(AnnotationTable).delete()
            return rows_deleted

    def create_indices(self) -> None:
        """Indices are created via SQLAlchemy table definitions."""
        pass
