"""Annotation repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.models.annotation import Annotation


class AnnotationRepositoryInterface(ABC):
    """Abstract interface for annotation data access."""

    @abstractmethod
    def get_by_id(self, annotation_id: str) -> Optional[Annotation]:
        """Get an annotation by its ID."""
        pass

    @abstractmethod
    def get_note_for_annotation(self, annotation_id: str) -> Optional[dict]:
        """Get the note associated with an annotation."""
        pass

    @abstractmethod
    def get_by_note(self, note_id: str, include_negated: bool = False) -> list[Annotation]:
        """Get all annotations for a note."""
        pass

    @abstractmethod
    def get_by_sentence(self, note_id: str, sentence_number: int) -> list[Annotation]:
        """Get annotations for a specific sentence in a note."""
        pass

    @abstractmethod
    def get_by_patient(self, patient_id: str, include_negated: bool = False) -> list[Annotation]:
        """Get all annotations for a patient."""
        pass

    @abstractmethod
    def get_patient_annotation_ids(
        self, patient_id: str, reviewed_status: int = 0, key: str = "_id"
    ) -> list[str]:
        """Get annotation IDs for a patient filtered by review status."""
        pass

    @abstractmethod
    def get_annotations_post_event(
        self, patient_id: str, event_date: datetime
    ) -> list[Annotation]:
        """Get unreviewed annotations after a given event date."""
        pass

    @abstractmethod
    def insert_one(self, annotation: dict) -> str:
        """Insert a single annotation. Returns the inserted ID."""
        pass

    @abstractmethod
    def get_all(self) -> list[Annotation]:
        """Get all annotations."""
        pass

    @abstractmethod
    def count(self, include_negated: bool = True) -> int:
        """Count annotations, optionally excluding negated."""
        pass

    @abstractmethod
    def mark_reviewed(self, annotation_id: str) -> bool:
        """Mark an annotation as reviewed."""
        pass

    @abstractmethod
    def batch_mark_reviewed(self, annotation_ids: list[str]) -> int:
        """Mark multiple annotations as reviewed. Returns count updated."""
        pass

    @abstractmethod
    def revert_reviewed(self, annotation_id: str) -> bool:
        """Revert an annotation to unreviewed."""
        pass

    @abstractmethod
    def mark_skipped_post_event(self, patient_id: str, event_date: datetime) -> int:
        """Mark annotations after event date as skipped. Returns count updated."""
        pass

    @abstractmethod
    def revert_skipped(self, patient_id: str) -> int:
        """Revert skipped annotations to unreviewed. Returns count updated."""
        pass

    @abstractmethod
    def update_note_review_status(self, annotation_id: str, reviewed_by: str) -> dict:
        """Update review status after annotation review. Returns status info."""
        pass

    @abstractmethod
    def batch_update_note_review_status(
        self, annotation_ids: list[str], reviewed_by: str
    ) -> dict:
        """Batch update review status. Returns status info."""
        pass

    @abstractmethod
    def mark_all_in_note_reviewed(self, note_id: str) -> int:
        """Mark all annotations in a note as reviewed. Returns count updated."""
        pass

    @abstractmethod
    def delete_all(self) -> int:
        """Delete all annotations. Returns count deleted."""
        pass

    @abstractmethod
    def create_indices(self) -> None:
        """Create database indices for annotations."""
        pass
