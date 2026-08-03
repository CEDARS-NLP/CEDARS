"""Project-scoped ops-queue tasks (ported from the Flask ``ops`` blueprint).

These mirror ``update_patient_data`` / ``enter_patient_date`` /
``delete_patient_date`` verbatim, wrapped so each runs against the correct
project database in the worker. A thin ``upsert_patient_records`` wrapper is
added for the enqueue sites that previously enqueued ``db.upsert_patient_records``
directly.
"""
from . import db
from .tasks import project_scope


def _update_patient_data(patient_id, comments, reviewed_by,
                         reviewed_annotation_ids, timestamp):
    db.batch_mark_annotation_reviewed(reviewed_annotation_ids, reviewed_by)
    db.add_comment(patient_id, comments.strip())
    db.upsert_patient_records(patient_id, timestamp, reviewed_by)
    db.set_patient_lock_status(patient_id, False)


def update_patient_data(project_id, patient_id, comments, reviewed_by,
                        reviewed_annotation_ids, timestamp):
    """Update comments/results/reviewed annotations, then unlock the patient."""
    with project_scope(project_id):
        _update_patient_data(patient_id, comments, reviewed_by,
                             reviewed_annotation_ids, timestamp)


def enter_patient_date(project_id, patient_id, new_date, current_annotation_id,
                       reviewed_by, comments, reviewed_annotation_ids, timestamp,
                       skip_after_event, is_patient_reviewed):
    """Persist a new event date and mark relevant annotations."""
    with project_scope(project_id):
        if skip_after_event:
            db.mark_annotations_post_event(patient_id, new_date)
        db.mark_annotation_reviewed(current_annotation_id, reviewed_by)
        db.update_event_date(patient_id, new_date, current_annotation_id)
        if is_patient_reviewed:
            _update_patient_data(patient_id, comments, reviewed_by,
                                 reviewed_annotation_ids, timestamp)


def delete_patient_date(project_id, patient_id, current_annotation_id, reviewed_by,
                        comments, reviewed_annotation_ids, timestamp,
                        is_patient_reviewed):
    """Delete the event date and revert skipped/reviewed markers."""
    with project_scope(project_id):
        db.delete_event_date(patient_id)
        db.revert_skipped_annotations(patient_id)
        db.revert_annotation_reviewed(current_annotation_id, reviewed_by)
        if is_patient_reviewed:
            _update_patient_data(patient_id, comments, reviewed_by,
                                 reviewed_annotation_ids, timestamp)


def upsert_patient_records(project_id, patient_id, timestamp, updated_by):
    """Recompute a patient's RESULTS row within its project scope."""
    with project_scope(project_id):
        db.upsert_patient_records(patient_id, timestamp, updated_by)


def download_annotations(project_id, filename, get_sentences=False):
    """Generate the annotations CSV and upload it to S3, within project scope."""
    with project_scope(project_id):
        return db.download_annotations(filename, get_sentences)


def update_patient_results(project_id, update_existing_results=False):
    """Rebuild the RESULTS collection within project scope."""
    with project_scope(project_id):
        return db.update_patient_results(update_existing_results)


def remove_all_locked(project_id):
    """Unlock all patients within project scope."""
    with project_scope(project_id):
        return db.remove_all_locked()
