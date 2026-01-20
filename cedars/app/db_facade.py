"""
Database facade using the repository pattern.

This module provides a backwards-compatible interface to the database
using the new repository pattern. New code should import from here
or directly use repositories via the factory.

Usage:
    # Option 1: Use facade functions (backwards compatible)
    from app.db_facade import get_patient_by_id, mark_patient_reviewed

    # Option 2: Use repositories directly (recommended for new code)
    from app.factory import get_patient_repository
    patient_repo = get_patient_repository()
    patient = patient_repo.get_by_id("P001")
"""

import threading
from datetime import datetime
from typing import Optional

from app.factory import (
    get_patient_repository,
    get_note_repository,
    get_annotation_repository,
    get_user_repository,
    get_project_repository,
    get_task_repository,
    init_database,
)

# Thread-safe lazy-loaded repository instances
_repo_lock = threading.Lock()
_patient_repo = None
_note_repo = None
_annotation_repo = None
_user_repo = None
_project_repo = None
_task_repo = None


def _get_patient_repo():
    global _patient_repo
    if _patient_repo is None:
        with _repo_lock:
            if _patient_repo is None:
                _patient_repo = get_patient_repository()
    return _patient_repo


def _get_note_repo():
    global _note_repo
    if _note_repo is None:
        with _repo_lock:
            if _note_repo is None:
                _note_repo = get_note_repository()
    return _note_repo


def _get_annotation_repo():
    global _annotation_repo
    if _annotation_repo is None:
        with _repo_lock:
            if _annotation_repo is None:
                _annotation_repo = get_annotation_repository()
    return _annotation_repo


def _get_user_repo():
    global _user_repo
    if _user_repo is None:
        with _repo_lock:
            if _user_repo is None:
                _user_repo = get_user_repository()
    return _user_repo


def _get_project_repo():
    global _project_repo
    if _project_repo is None:
        with _repo_lock:
            if _project_repo is None:
                _project_repo = get_project_repository()
    return _project_repo


def _get_task_repo():
    global _task_repo
    if _task_repo is None:
        with _repo_lock:
            if _task_repo is None:
                _task_repo = get_task_repository()
    return _task_repo


# =============================================================================
# Patient Operations
# =============================================================================

def get_patient_by_id(patient_id: str) -> Optional[dict]:
    """Get a patient by their patient_id."""
    patient = _get_patient_repo().get_by_id(patient_id)
    return patient.model_dump() if patient else None


def get_patient() -> Optional[dict]:
    """Get the next unreviewed patient."""
    patient = _get_patient_repo().get_next_unreviewed()
    return patient.model_dump() if patient else None


def get_all_patient_ids() -> list[str]:
    """Get all patient IDs."""
    return _get_patient_repo().get_all_ids()


def get_patient_ids() -> list[str]:
    """Get unreviewed patient IDs."""
    return _get_patient_repo().get_unreviewed_ids()


def mark_patient_reviewed(patient_id: str, reviewed_by: str, is_reviewed: bool = True) -> bool:
    """Mark a patient as reviewed."""
    return _get_patient_repo().mark_reviewed(patient_id, reviewed_by, is_reviewed)


def set_patient_lock_status(patient_id: str, status: bool) -> bool:
    """Set patient lock status."""
    return _get_patient_repo().set_lock_status(patient_id, status)


def remove_all_locked() -> int:
    """Remove locks from all patients."""
    return _get_patient_repo().remove_all_locks()


def update_event_date(patient_id: str, new_date: Optional[datetime], annotation_id: str = None) -> bool:
    """Update event date for a patient."""
    return _get_patient_repo().set_event_date(patient_id, new_date)


def add_comment(patient_id: str, comment: str) -> bool:
    """Add a comment to a patient."""
    return _get_patient_repo().add_comment(patient_id, comment)


def get_patient_reviewer(patient_id: str) -> Optional[str]:
    """Get the reviewer for a patient."""
    return _get_patient_repo().get_reviewer(patient_id)


# =============================================================================
# Note Operations
# =============================================================================

def get_all_notes(patient_id: str) -> list[dict]:
    """Get all notes for a patient."""
    notes = _get_note_repo().get_by_patient(patient_id)
    return [n.model_dump() for n in notes]


def get_note_date(note_id: str) -> Optional[datetime]:
    """Get the date of a note."""
    return _get_note_repo().get_note_date(note_id)


def bulk_insert_notes(notes: list[dict]) -> int:
    """Bulk insert notes."""
    return _get_note_repo().bulk_insert(notes)


def update_notes_summary() -> int:
    """Update the notes summary cache."""
    return _get_note_repo().update_notes_summary()


# =============================================================================
# Annotation Operations
# =============================================================================

def get_annotation(annotation_id: str) -> Optional[dict]:
    """Get an annotation by ID."""
    annotation = _get_annotation_repo().get_by_id(annotation_id)
    return annotation.model_dump() if annotation else None


def get_all_annotations_for_note(note_id: str) -> list[dict]:
    """Get all annotations for a note."""
    annotations = _get_annotation_repo().get_by_note(note_id)
    return [a.model_dump() for a in annotations]


def get_all_annotations_for_patient(patient_id: str) -> list[dict]:
    """Get all annotations for a patient."""
    annotations = _get_annotation_repo().get_by_patient(patient_id)
    return [a.model_dump() for a in annotations]


def insert_one_annotation(annotation: dict) -> str:
    """Insert a single annotation."""
    return _get_annotation_repo().insert_one(annotation)


def mark_annotation_reviewed(annotation_id: str, reviewed_by: str) -> bool:
    """Mark an annotation as reviewed."""
    _get_annotation_repo().mark_reviewed(annotation_id)
    return True


# =============================================================================
# User Operations
# =============================================================================

def get_user(username: str) -> Optional[dict]:
    """Get a user by username."""
    user = _get_user_repo().get_by_username(username)
    return user.model_dump() if user else None


def add_user(username: str, password_hash: str, is_admin: bool = False) -> bool:
    """Add a new user."""
    return _get_user_repo().add_user(username, password_hash, is_admin)


def check_password(username: str, password: str) -> bool:
    """Check a user's password."""
    return _get_user_repo().check_password(username, password)


def is_admin_user(username: str) -> bool:
    """Check if a user is an admin."""
    return _get_user_repo().is_admin(username)


# =============================================================================
# Project Operations
# =============================================================================

def get_info() -> dict:
    """Get project info."""
    info = _get_project_repo().get_info()
    return info or {}


def get_proj_name() -> Optional[str]:
    """Get the project name."""
    return _get_project_repo().get_project_name()


def create_project(project_name: str, investigator_name: str, project_id: str, cedars_version: str = None) -> bool:
    """Create a new project."""
    return _get_project_repo().create_project(project_name, investigator_name, project_id, cedars_version)


def get_search_query(query_key: str = "query") -> Optional[str]:
    """Get the current search query."""
    return _get_project_repo().get_search_query(query_key)


def get_curr_stats() -> dict:
    """Get current statistics."""
    return _get_project_repo().get_stats()


def create_db_indices() -> None:
    """Create database indices."""
    _get_project_repo().create_indices()
    _get_annotation_repo().create_indices()


# =============================================================================
# Task Operations
# =============================================================================

def add_task(task: dict) -> bool:
    """Add a background task."""
    return _get_task_repo().add_task(task)


def get_tasks_in_progress() -> list[dict]:
    """Get tasks in progress."""
    tasks = _get_task_repo().get_in_progress()
    return [t.model_dump() for t in tasks]


def update_db_task_progress(task_id: str, progress: int) -> bool:
    """Update task progress."""
    complete = progress >= 100
    return _get_task_repo().update_progress(task_id, progress, complete)


def report_success(job) -> bool:
    """Report job success."""
    return _get_task_repo().report_success(job.id)


def report_failure(job) -> bool:
    """Report job failure."""
    return _get_task_repo().report_failure(job.id)
