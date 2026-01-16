"""Note repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.models.note import Note
from app.models.notes_summary import NotesSummary


class NoteRepositoryInterface(ABC):
    """Abstract interface for note data access."""

    @abstractmethod
    def get_by_id(self, text_id: str) -> Optional[Note]:
        """Get a note by its text_id."""
        pass

    @abstractmethod
    def get_by_patient(self, patient_id: str) -> list[Note]:
        """Get all notes for a patient."""
        pass

    @abstractmethod
    def get_patient_notes_for_review(self, patient_id: str, reviewed: bool = False) -> list[Note]:
        """Get patient notes filtered by review status."""
        pass

    @abstractmethod
    def get_note_date(self, text_id: str) -> Optional[datetime]:
        """Get the date of a note."""
        pass

    @abstractmethod
    def count_by_patient(self, patient_id: str, reviewed: Optional[bool] = None) -> int:
        """Count notes for a patient, optionally filtered by review status."""
        pass

    @abstractmethod
    def count(self, **filters) -> int:
        """Count notes matching filters."""
        pass

    @abstractmethod
    def bulk_insert(self, notes: list[dict]) -> int:
        """Bulk insert notes. Returns count inserted."""
        pass

    @abstractmethod
    def mark_reviewed(self, text_id: str, reviewed_by: str) -> bool:
        """Mark a note as reviewed."""
        pass

    @abstractmethod
    def batch_mark_reviewed(self, text_ids: list[str], reviewed_by: str) -> int:
        """Mark multiple notes as reviewed. Returns count updated."""
        pass

    @abstractmethod
    def revert_reviewed(self, text_id: str, reviewed_by: str) -> bool:
        """Revert a note to unreviewed state."""
        pass

    @abstractmethod
    def reset_all_reviewed(self) -> int:
        """Reset all notes to unreviewed. Returns count updated."""
        pass

    @abstractmethod
    def get_documents_to_annotate(self, patient_id: Optional[str] = None) -> list[Note]:
        """Get notes that have no annotations and are not reviewed."""
        pass

    # Notes summary operations
    @abstractmethod
    def update_notes_summary(self) -> int:
        """Update/rebuild the notes summary cache. Returns count of summaries."""
        pass

    @abstractmethod
    def get_notes_summary(self) -> list[NotesSummary]:
        """Get all notes summaries."""
        pass

    @abstractmethod
    def get_first_note_date(self, patient_id: str) -> Optional[datetime]:
        """Get the earliest note date for a patient."""
        pass

    @abstractmethod
    def get_last_note_date(self, patient_id: str) -> Optional[datetime]:
        """Get the latest note date for a patient."""
        pass

    @abstractmethod
    def get_num_notes(self, patient_id: str) -> int:
        """Get the number of notes for a patient from cache."""
        pass
