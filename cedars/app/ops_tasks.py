"""Project-scoped ops-queue tasks (ported from the Flask ``ops`` blueprint).

These mirror ``update_patient_data`` / ``enter_patient_date`` /
``delete_patient_date`` verbatim, wrapped so each runs against the correct
project database in the worker. A thin ``upsert_patient_records`` wrapper is
is provided for the enqueue sites.
"""
from .database import (get_bucket_name, get_current_project_engine,
                       project_s3_prefix, s3)
from .database.db_export import download_annotations as export_annotations
from .database.db_inserts import add_comment
from .database.db_updates import (batch_mark_annotation_reviewed,
                                  delete_event_date, mark_annotation_reviewed,
                                  mark_annotations_post_event,
                                  remove_all_locked as remove_all_patients_locked,
                                  revert_annotation_reviewed,
                                  revert_skipped_annotations,
                                  set_patient_lock_status,
                                  update_event_date,
                                  update_patient_results as rebuild_patient_results,
                                  upsert_patient_records as update_patient_records)
from .tasks import project_scope


def _update_patient_data(patient_id, comments, reviewed_by,
                         reviewed_annotation_ids, timestamp):
    project_engine = get_current_project_engine()
    batch_mark_annotation_reviewed(project_engine, reviewed_annotation_ids, reviewed_by)
    add_comment(project_engine, patient_id, comments.strip())
    update_patient_records(project_engine, patient_id, timestamp, reviewed_by)
    set_patient_lock_status(project_engine, patient_id, False)


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
        project_engine = get_current_project_engine()
        if skip_after_event:
            mark_annotations_post_event(project_engine, patient_id, new_date)
        mark_annotation_reviewed(project_engine, current_annotation_id, reviewed_by)
        update_event_date(project_engine, patient_id, new_date, current_annotation_id)
        if is_patient_reviewed:
            _update_patient_data(patient_id, comments, reviewed_by,
                                 reviewed_annotation_ids, timestamp)


def delete_patient_date(project_id, patient_id, current_annotation_id, reviewed_by,
                        comments, reviewed_annotation_ids, timestamp,
                        is_patient_reviewed):
    """Delete the event date and revert skipped/reviewed markers."""
    with project_scope(project_id):
        project_engine = get_current_project_engine()
        delete_event_date(project_engine, patient_id)
        revert_skipped_annotations(project_engine, patient_id)
        revert_annotation_reviewed(project_engine, current_annotation_id, reviewed_by)
        if is_patient_reviewed:
            _update_patient_data(patient_id, comments, reviewed_by,
                                 reviewed_annotation_ids, timestamp)


def upsert_patient_records(project_id, patient_id, timestamp, updated_by):
    """Recompute a patient's RESULTS row within its project scope."""
    with project_scope(project_id):
        update_patient_records(get_current_project_engine(), patient_id, timestamp, updated_by)


def download_annotations(project_id, filename, get_sentences=False):
    """Generate the annotations CSV and upload it to S3, within project scope."""
    with project_scope(project_id):
        return export_annotations(get_current_project_engine(), s3, get_bucket_name(),
                                  project_s3_prefix(), filename)


def update_patient_results(project_id, update_existing_results=False):
    """Rebuild the RESULTS collection within project scope."""
    with project_scope(project_id):
        return rebuild_patient_results(get_current_project_engine(), update_existing_results)


def remove_all_locked(project_id):
    """Unlock all patients within project scope."""
    with project_scope(project_id):
        return remove_all_patients_locked(get_current_project_engine())
