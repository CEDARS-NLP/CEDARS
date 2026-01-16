"""Patient repository interface."""

from abc import ABC, abstractmethod
from datetime import datetime
from typing import Optional

from app.models.patient import Patient


class PatientRepositoryInterface(ABC):
    """Abstract interface for patient data access."""

    @abstractmethod
    def get_by_id(self, patient_id: str) -> Optional[Patient]:
        """Get a patient by their patient_id."""
        pass

    @abstractmethod
    def get_next_unreviewed(self) -> Optional[Patient]:
        """Get the next unreviewed, unlocked patient (ordered by index_no)."""
        pass

    @abstractmethod
    def get_all_ids(self, reviewed_only: bool = False) -> list[str]:
        """Get all patient IDs, optionally filtered by review status."""
        pass

    @abstractmethod
    def get_unreviewed_ids(self) -> list[str]:
        """Get IDs of unreviewed, unlocked patients."""
        pass

    @abstractmethod
    def count(self) -> int:
        """Count total patients."""
        pass

    @abstractmethod
    def bulk_upsert(self, patient_ids: set[str], start_index: int = 0) -> int:
        """Bulk insert/update patients. Returns count of new patients."""
        pass

    @abstractmethod
    def mark_reviewed(self, patient_id: str, reviewed_by: str, is_reviewed: bool = True) -> bool:
        """Mark a patient as reviewed/unreviewed."""
        pass

    @abstractmethod
    def set_lock_status(self, patient_id: str, locked: bool) -> bool:
        """Set patient lock status."""
        pass

    @abstractmethod
    def remove_all_locks(self) -> int:
        """Remove locks from all patients. Returns count updated."""
        pass

    @abstractmethod
    def set_event_date(self, patient_id: str, event_date: Optional[datetime]) -> bool:
        """Set or clear the event date for a patient."""
        pass

    @abstractmethod
    def set_event_annotation_id(self, patient_id: str, annotation_id: Optional[str]) -> bool:
        """Set or clear the event annotation ID for a patient."""
        pass

    @abstractmethod
    def add_comment(self, patient_id: str, comment: str) -> bool:
        """Add a comment to a patient record."""
        pass

    @abstractmethod
    def get_reviewer(self, patient_id: str) -> Optional[str]:
        """Get the reviewer username for a patient."""
        pass

    @abstractmethod
    def reset_all_reviewed(self) -> int:
        """Reset all patients to unreviewed state. Returns count updated."""
        pass
