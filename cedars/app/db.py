"""
db.py

Thin compatibility facade over ``cedars.app.database.*``. Preserves the
original function names/signatures used across the app (routers, services,
nlpprocessor, adjudication_handler, tasks) so those call sites don't need to
know about SQLAlchemy engines/sessions - each function here resolves the
current project's engine (and the global engine) from the contextvar bound by
``dependencies.bind_project`` / ``tasks.project_scope``, then delegates to the
matching function in ``cedars.app.database``.

Return values are now SQLAlchemy ORM objects/typed values, not mongo dicts -
callers that used dict-style access (``doc["field"]``) must be updated to
attribute access (``doc.field``); see the migration plan for the full list.
"""
from datetime import date, datetime

from .cedars_enums import ReviewStatus, log_function_call
from .database import (get_current_project_engine, get_current_project_id,
                       get_global_engine)
from .database import (db_auth, db_deletes, db_export, db_inserts, db_projects,
                       db_query, db_search, db_stats, db_tasks, db_updates,
                       external_services, init_db)
from .database.project_table_creation import (
    Annotations, Notes, NotesSummary, PINES, Patients, Results, Task,
)
from .queues import task_queue

# Maps mongo's ReviewStatus enum onto the single-char Annotations.status column.
_STATUS_BY_REVIEW_ENUM = {
    ReviewStatus.UNREVIEWED: Annotations.STATUS_UNREVIEWED,
    ReviewStatus.REVIEWED: Annotations.STATUS_REVIEWED,
    ReviewStatus.SKIPPED: Annotations.STATUS_SKIPPED,
}

# Maps the old mongo collection-name strings (get_total_counts) onto ORM models.
_MODEL_BY_COLLECTION_NAME = {
    "NOTES": Notes,
    "PATIENTS": Patients,
    "ANNOTATIONS": Annotations,
    "RESULTS": Results,
    "PINES": PINES,
    "TASK": Task,
    "NOTES_SUMMARY": NotesSummary,
}


def _parse_version(cedars_version) -> float:
    """Best-effort conversion of a "0.1.0"-style version string to a float."""
    if isinstance(cedars_version, (int, float)):
        return float(cedars_version)
    try:
        return float(cedars_version)
    except (TypeError, ValueError):
        parts = str(cedars_version).split(".")[:2]
        return float(".".join(parts)) if parts else 0.0


# --- project / info management ---------------------------------------------

@log_function_call
def create_project(project_name, investigator_name, project_id=None,
                   cedars_version="0.1.0", description=""):
    """Creates a new project's database, tables, and registers it globally."""
    return init_db.initialize_project(
        project_name, investigator_name, _parse_version(cedars_version),
        project_id=project_id, description=description)


@log_function_call
def terminate_project():
    """Resets the current project to its initial (empty) state."""
    db_projects.terminate_project(get_global_engine(), get_current_project_engine(),
                                  get_current_project_id())


@log_function_call
def get_info():
    """Returns the current project's metadata (mirrors mongo's INFO doc)."""
    return db_projects.get_info(get_global_engine(), get_current_project_engine(),
                                get_current_project_id())


@log_function_call
def get_proj_name():
    """Returns the current project's name."""
    return db_projects.get_proj_name(get_global_engine(), get_current_project_id())


@log_function_call
def get_curr_version():
    """Returns the CEDARS version the current project was created with."""
    return db_projects.get_curr_version(get_global_engine(), get_current_project_id())


@log_function_call
def update_project_name(new_name):
    """Updates the current project's display name."""
    db_projects.update_project_name(get_global_engine(), get_current_project_id(), new_name)


@log_function_call
def update_project_description(new_description):
    """Updates the current project's description."""
    db_projects.update_project_description(get_global_engine(), get_current_project_id(),
                                           new_description)


@log_function_call
def list_projects():
    """Returns every project in the global registry."""
    return db_projects.list_projects(get_global_engine())


@log_function_call
def create_pines_info(pines_url, is_url_from_api):
    """Sets the initial PINES url/enabled status for the current project."""
    return db_projects.create_pines_info(get_current_project_engine(), pines_url, is_url_from_api)


@log_function_call
def update_pines_api_status(new_status):
    """Updates whether the PINES server is enabled for the current project."""
    db_projects.update_pines_api_status(get_current_project_engine(), new_status)


@log_function_call
def update_pines_api_url(new_url):
    """Updates the PINES API url for the current project."""
    db_projects.update_pines_api_url(get_current_project_engine(), new_url)


@log_function_call
def get_pines_url():
    """Returns the configured PINES url for the current project."""
    return db_projects.get_pines_url(get_current_project_engine())


@log_function_call
def is_pines_api_running():
    """Returns True if a PINES API server is enabled for the current project."""
    return db_projects.is_pines_api_running(get_current_project_engine())


# --- global user management --------------------------------------------------

@log_function_call
def add_user(username, password, is_admin=False):
    """Adds a new user to the global application database.

    Note: ``password`` is expected to already be a werkzeug password hash
    (callers hash it before calling this, same as the old mongo behavior).
    """
    db_auth.add_user(get_global_engine(), username, password_hash=password,
                     uses_orcid=False, is_admin=is_admin)


@log_function_call
def get_user(username):
    """Returns the global Users row for `username`, or None."""
    return db_auth.get_user(get_global_engine(), username)


@log_function_call
def check_password(username, password):
    """Validates `password` (plaintext) against the stored hash for `username`."""
    ok, _ = db_auth.validate_local_user(get_global_engine(), username, password)
    return ok


@log_function_call
def is_admin_user(username):
    """Returns True if `username` is a global superuser."""
    user = db_auth.get_user(get_global_engine(), username)
    return bool(user is not None and user.is_admin)


@log_function_call
def get_project_users():
    """Returns every registered username (global registry, not project-scoped -
    name kept for backward compatibility with the mongo-era call sites)."""
    return db_auth.list_users(get_global_engine())


# --- query management ---------------------------------------------------------

@log_function_call
def save_query(query, exclude_negated, hide_duplicates, skip_after_event,
               tag_query, date_min=None, date_max=None):
    """Saves a new search query for the current project."""
    tag_query = tag_query or {}
    tag_query_exact = tag_query.get("exact", False) if isinstance(tag_query, dict) else bool(tag_query)
    apply_pines = tag_query.get("apply_pines", False) if isinstance(tag_query, dict) else False
    apply_llm = tag_query.get("apply_llm", False) if isinstance(tag_query, dict) else False
    return db_query.save_query(get_current_project_engine(), query, exclude_negated,
                               hide_duplicates, skip_after_event, tag_query_exact,
                               apply_pines, apply_llm, date_min, date_max)


@log_function_call
def get_search_query(query_key="query"):
    """Returns a single field from the current project's active search query."""
    return db_query.get_search_query(get_current_project_engine(), query_key)


@log_function_call
def get_search_query_details():
    """Returns the current project's active search query as a dict."""
    return db_query.get_search_query_details(get_current_project_engine())


# --- inserts / bulk operations --------------------------------------------------

@log_function_call
def bulk_insert_notes(notes):
    """Bulk inserts notes into the current project."""
    return db_inserts.bulk_insert_notes(get_current_project_engine(), notes)


@log_function_call
def bulk_upsert_patients(patient_ids, chunk_size_upsert_patients=2000):
    """Creates default Patients/Results rows for any new patient_ids."""
    return db_inserts.bulk_upsert_patients(get_current_project_engine(), list(patient_ids),
                                           chunk_size_upsert_patients)


@log_function_call
def update_notes_summary():
    """Rebuilds the current project's NotesSummary table."""
    db_updates.update_notes_summary(get_current_project_engine())


@log_function_call
def insert_one_annotation(annotation):
    """Inserts a single annotation for the current project."""
    db_inserts.insert_one_annotation(get_current_project_engine(), annotation)


@log_function_call
def add_task(task):
    """Creates or resets a background task record."""
    db_tasks.add_task(get_current_project_engine(), task)


@log_function_call
def add_comment(patient_id, comment):
    """Stores a new comment for a patient."""
    db_inserts.add_comment(get_current_project_engine(), patient_id, comment)


# --- annotation review-status updates -------------------------------------------

@log_function_call
def mark_annotation_reviewed(annotation_id, reviewed_by):
    db_updates.mark_annotation_reviewed(get_current_project_engine(), annotation_id, reviewed_by)


@log_function_call
def batch_mark_annotation_reviewed(annotation_ids, reviewed_by):
    db_updates.batch_mark_annotation_reviewed(get_current_project_engine(), annotation_ids, reviewed_by)


@log_function_call
def revert_annotation_reviewed(annotation_id, reviewed_by):
    db_updates.revert_annotation_reviewed(get_current_project_engine(), annotation_id, reviewed_by)


@log_function_call
def mark_annotations_post_event(patient_id: str, event_date: date):
    db_updates.mark_annotations_post_event(get_current_project_engine(), patient_id, event_date)


@log_function_call
def revert_skipped_annotations(patient_id: str):
    db_updates.revert_skipped_annotations(get_current_project_engine(), patient_id)


@log_function_call
def update_annotation_reviewed(note_id: str) -> int:
    return db_updates.update_annotation_reviewed(get_current_project_engine(), note_id)


# --- note review-status updates -------------------------------------------------

@log_function_call
def mark_note_reviewed(note_id, reviewed_by: str):
    db_updates.mark_note_reviewed(get_current_project_engine(), note_id, reviewed_by)


@log_function_call
def batch_mark_note_reviewed(note_ids, reviewed_by: str):
    db_updates.batch_mark_note_reviewed(get_current_project_engine(), note_ids, reviewed_by)


@log_function_call
def revert_note_reviewed(note_id, reviewed_by: str):
    db_updates.revert_note_reviewed(get_current_project_engine(), note_id, reviewed_by)


# --- patient review-status / event-date updates ---------------------------------

@log_function_call
def mark_patient_reviewed(patient_id: str, reviewed_by: str, is_reviewed=True):
    db_updates.mark_patient_reviewed(get_current_project_engine(), patient_id, reviewed_by, is_reviewed)


@log_function_call
def revert_patient_reviewed(patient_id, reviewed_by: str):
    db_updates.revert_patient_reviewed(get_current_project_engine(), patient_id, reviewed_by)


@log_function_call
def reset_patient_reviewed():
    db_updates.reset_patient_reviewed(get_current_project_engine())


@log_function_call
def set_patient_lock_status(patient_id: str, status):
    db_updates.set_patient_lock_status(get_current_project_engine(), patient_id, status)


@log_function_call
def remove_all_locked():
    db_updates.remove_all_locked(get_current_project_engine())


@log_function_call
def update_event_date(patient_id: str, new_date, annotation_id):
    db_updates.update_event_date(get_current_project_engine(), patient_id, new_date, annotation_id)


@log_function_call
def delete_event_date(patient_id: str):
    db_updates.delete_event_date(get_current_project_engine(), patient_id)


@log_function_call
def update_event_annotation_id(patient_id: str, annotation_id):
    db_updates.update_event_annotation_id(get_current_project_engine(), patient_id, annotation_id)


@log_function_call
def delete_event_annotation_id(patient_id: str):
    db_updates.delete_event_annotation_id(get_current_project_engine(), patient_id)


@log_function_call
def upsert_patient_records(patient_id: str, insert_datetime: datetime = None, updated_by: str = None):
    db_updates.upsert_patient_records(get_current_project_engine(), patient_id, insert_datetime, updated_by)


@log_function_call
def update_patient_results(update_existing_results=False):
    db_updates.update_patient_results(get_current_project_engine(), update_existing_results)


# --- annotation reads ------------------------------------------------------------

@log_function_call
def get_all_annotations_for_note(note_id):
    return db_search.get_all_annotations_for_note(get_current_project_engine(), note_id)


@log_function_call
def get_all_annotations_for_sentence(note_id, sentence_number):
    return db_search.get_all_annotations_for_sentence(get_current_project_engine(), note_id, sentence_number)


@log_function_call
def get_annotation(annotation_id):
    return db_search.get_annotation(get_current_project_engine(), int(annotation_id))


@log_function_call
def get_annotation_note(annotation_id: str):
    return db_search.get_annotation_note(get_current_project_engine(), int(annotation_id))


@log_function_call
def get_all_annotations_for_patient(patient_id: str):
    return db_search.get_all_annotations_for_patient(get_current_project_engine(), patient_id)


@log_function_call
def get_patient_annotation_ids(p_id: str, reviewed=ReviewStatus.UNREVIEWED, key="_id"):
    status = _STATUS_BY_REVIEW_ENUM.get(reviewed, Annotations.STATUS_UNREVIEWED)
    key = "annotation_id" if key == "_id" else key
    return db_search.get_patient_annotation_ids(get_current_project_engine(), p_id, status, key)


@log_function_call
def get_annotations_post_event(patient_id: str, event_date: date):
    return db_search.get_annotations_post_event(get_current_project_engine(), patient_id, event_date)


@log_function_call
def get_all_annotations():
    return db_search.get_all_annotations(get_current_project_engine())


@log_function_call
def get_annotated_notes_for_patient(patient_id: str) -> list:
    return db_search.get_annotated_notes_for_patient(get_current_project_engine(), patient_id)


# --- patient reads ----------------------------------------------------------------

@log_function_call
def get_patient_by_id(patient_id: str):
    return db_search.get_patient_by_id(get_current_project_engine(), patient_id)


@log_function_call
def get_patient():
    return db_search.get_patient(get_current_project_engine())


@log_function_call
def get_patients_to_annotate():
    return db_search.get_patients_to_annotate(get_current_project_engine())


@log_function_call
def get_all_patient_ids():
    return db_search.get_all_patient_ids(get_current_project_engine())


@log_function_call
def get_patient_ids():
    return db_search.get_patient_ids(get_current_project_engine())


@log_function_call
def get_patient_lock_status(patient_id: str):
    return db_search.get_patient_lock_status(get_current_project_engine(), patient_id)


@log_function_call
def get_patient_reviewer(patient_id: str):
    return db_search.get_patient_reviewer(get_current_project_engine(), patient_id)


@log_function_call
def get_event_date(patient_id: str):
    return db_search.get_event_date(get_current_project_engine(), patient_id)


@log_function_call
def get_event_annotation_id(patient_id: str):
    return db_search.get_event_annotation_id(get_current_project_engine(), patient_id)


@log_function_call
def patient_results_exist(patient_id: str):
    return db_search.patient_results_exist(get_current_project_engine(), patient_id)


# --- note reads ---------------------------------------------------------------------

@log_function_call
def get_all_notes(patient_id: str):
    return db_search.get_all_notes(get_current_project_engine(), patient_id)


@log_function_call
def get_patient_notes(patient_id: str, reviewed=False):
    return db_search.get_patient_notes(get_current_project_engine(), patient_id, reviewed)


@log_function_call
def get_num_patient_notes(patient_id: str, num_notes=None):
    return db_search.get_num_patient_notes(get_current_project_engine(), patient_id, num_notes)


@log_function_call
def get_note_date(note_id):
    return db_search.get_note_date(get_current_project_engine(), note_id)


@log_function_call
def get_documents_to_annotate(patient_id=None):
    return db_search.get_documents_to_annotate(get_current_project_engine(), patient_id)


@log_function_call
def get_documents_to_annotate_docdb(patient_id=None):
    """No DocumentDB-specific variant needed for SQL; kept for call-site parity."""
    return get_documents_to_annotate(patient_id)


# --- date / summary reads ------------------------------------------------------------

@log_function_call
def get_first_note_date_for_patient(patient_id: str, first_note_date=None):
    return db_search.get_first_note_date_for_patient(get_current_project_engine(), patient_id, first_note_date)


@log_function_call
def get_last_note_date_for_patient(patient_id: str, last_note_date=None):
    return db_search.get_last_note_date_for_patient(get_current_project_engine(), patient_id, last_note_date)


@log_function_call
def get_notes_summary():
    return db_search.get_all_notes_summaries(get_current_project_engine())


# --- generic counts -------------------------------------------------------------------

@log_function_call
def get_total_counts(collection_name: str, **kwargs) -> int:
    model = _MODEL_BY_COLLECTION_NAME.get(collection_name)
    if model is None:
        raise ValueError(f"Unknown collection/table name: {collection_name!r}")
    return db_search.get_total_counts(get_current_project_engine(), model, **kwargs)


# --- PINES prediction reads ------------------------------------------------------------

@log_function_call
def get_formatted_patient_predictions(patient_id: str):
    return db_search.get_formatted_patient_predictions(get_current_project_engine(), patient_id)


@log_function_call
def get_max_prediction_score(patient_id: str):
    return db_search.get_max_prediction_score(get_current_project_engine(), patient_id)


@log_function_call
def get_max_prediction_score_docdb(patient_id: str):
    """No DocumentDB-specific variant needed for SQL; kept for call-site parity."""
    return get_max_prediction_score(patient_id)


@log_function_call
def get_note_prediction_from_db(note_id: str, pines_collection_name: str = "PINES"):
    return db_search.get_note_prediction_from_db(get_current_project_engine(), note_id)


# --- task queue reads/writes ------------------------------------------------------------

@log_function_call
def get_tasks_in_progress():
    return db_tasks.get_tasks_in_progress(get_current_project_engine())


@log_function_call
def get_task_in_progress(task_id):
    return db_tasks.get_task_in_progress(get_current_project_engine(), task_id)


@log_function_call
def get_task(task_id):
    return db_tasks.get_task(get_current_project_engine(), task_id)


@log_function_call
def update_db_task_progress(task_id, progress, failed=False):
    db_tasks.update_db_task_progress(get_current_project_engine(), task_id, progress, failed)


@log_function_call
def report_success(job):
    external_services.report_success(get_current_project_engine(), job)


@log_function_call
def report_failure(job):
    external_services.report_failure(get_current_project_engine(), job)


# --- deletes -----------------------------------------------------------------------------

@log_function_call
def empty_annotations():
    """Deletes all annotations/tasks for the current project and clears the task queue."""
    db_deletes.empty_annotations(get_current_project_engine())
    task_queue.empty()


@log_function_call
def drop_database(name):
    """Drops a project's entire Postgres database and its global registry rows,
    given its project_id."""
    init_db.drop_project_database(name)
    db_projects.delete_project_registry(get_global_engine(), name)


# --- stats -------------------------------------------------------------------------------

@log_function_call
def get_curr_stats():
    return db_stats.get_curr_stats(get_current_project_engine())


# --- export ------------------------------------------------------------------------------

@log_function_call
def download_annotations(filename: str = "annotations.csv", get_sentences: bool = False) -> bool:
    """Exports the current project's Results table as a CSV to S3.

    Note: `get_sentences` is accepted for call-site compatibility but ignored -
    the SQL Results table has no per-sentence cache column (see db_export.py).
    """
    from . import database as _database  # local import avoids a module-load cycle
    return db_export.download_annotations(
        get_current_project_engine(), _database.s3, _database.get_bucket_name(),
        _database.project_s3_prefix(), filename)


# --- PINES prediction (external HTTP) -----------------------------------------------------

@log_function_call
def get_prediction(note: str):
    pines_url = db_projects.get_pines_url(get_current_project_engine())
    return external_services.get_prediction(pines_url, note)


@log_function_call
def predict_and_save(text_ids=None, note_collection_name: str = "NOTES",
                     pines_collection_name: str = "PINES", force_update: bool = False):
    """Note: `note_collection_name`/`pines_collection_name` are accepted for
    call-site compatibility but ignored - there is only one Notes/PINES table."""
    pines_url = db_projects.get_pines_url(get_current_project_engine())
    return external_services.predict_and_save(get_current_project_engine(), pines_url,
                                              text_ids, force_update)


# --- setup/index no-ops (SQL schema/indices are declared in the ORM models) ----------------

@log_function_call
def create_collections():
    """No-op: SQL tables are created via init_db.create_project_tables/Alembic."""


@log_function_call
def create_collection(collection_name):
    """No-op: SQL tables are created via init_db.create_project_tables/Alembic."""


@log_function_call
def create_index(collection, index: list):
    """No-op: SQL indices are declared in project_table_creation.py's __table_args__."""


@log_function_call
def create_annotation_indices():
    """No-op: SQL indices are declared in project_table_creation.py's __table_args__."""


@log_function_call
def create_db_indices():
    """No-op: SQL indices are declared in project_table_creation.py's __table_args__."""


@log_function_call
def create_info_col(project_name, project_id, investigator_name, cedars_version):
    """No-op: project info is populated by init_db.populate_project_info."""
