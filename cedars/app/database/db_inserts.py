'''
db_inserts.py

Functions to load notes and other user inputs into the database.
'''

from datetime import datetime
from loguru import logger

from sqlalchemy import select, update, insert
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert

from .project_table_creation import (
    Annotations, Notes, NotesSummary, PINES, Patients, ProjectUsers, Results,
)
from ..cedars_enums import log_function_call
from .db_session import session_scope
from .global_app_tables import UserProjectRelation


logger.enable(__name__)


def _upsert_ignore(engine, table):
    '''
    Returns an `insert()` construct for `table` that is a no-op on conflicting
    primary keys, using the dialect-appropriate "ON CONFLICT DO NOTHING" syntax.
    Equivalent to mongo's `$setOnInsert` + `upsert=True` used throughout db.py.
    '''
    dialect = engine.dialect.name
    if dialect == "postgresql":
        return pg_insert(table).on_conflict_do_nothing()
    if dialect == "sqlite":
        return sqlite_insert(table).on_conflict_do_nothing()
    raise NotImplementedError(f"No conflict-ignoring insert implemented for dialect {dialect!r}.")


@log_function_call
def add_user_to_project(global_engine, project_engine,
                        username,
                        added_by,
                        has_admin_privileges,
                        project_id):
    '''
    Adds a new user to the database.
    '''
    with session_scope(global_engine) as session:
        session.execute(
            insert(UserProjectRelation).values(
                user_id=username,
                project_id=project_id,
                added_by=added_by,
                has_admin_privileges=has_admin_privileges
            )
        )

    logger.info(f"Successfully added user {username} to global database.")

    with session_scope(project_engine) as session:
        session.execute(
            insert(ProjectUsers).values(
                user_id=username,
                is_admin=has_admin_privileges
            )
        )

    logger.info(f"Successfully added user {username} to the database for {project_id}.")


def _format_note(note: dict) -> dict:
    '''
    Returns a copy of `note` with `text_date` parsed into a `datetime`.
    '''
    logger.debug(f"Formatting note info for note {note['text_id']}.")
    date_format = "%Y-%m-%d"
    text_date = note["text_date"]

    formatted = dict(note)
    if isinstance(text_date, str):
        try:
            formatted["text_date"] = datetime.strptime(text_date, date_format)
        except ValueError as exc:
            raise ValueError(
                f"Invalid date format for text_date: {text_date} for note "
                f"{note['text_id']}. Expected format: {date_format}"
            ) from exc
    elif not isinstance(text_date, datetime):
        raise ValueError(
            f"Unexpected type for text_date: {type(text_date)} for note "
            f"{note['text_id']}. Expected str or datetime."
        )

    return formatted


@log_function_call
def bulk_insert_notes(project_engine, notes: list[dict],
                      chunk_size_insert_notes: int = 1000) -> int:
    '''
    Bulk insert notes into the database, in chunks to bound memory/transaction size
    on very large uploads.

    Args:
        - project_engine: SQLAlchemy engine for the project database.
        - notes: List of dictionaries, where each dictionary represents a note to be
                 inserted. Dict format: {'text_id': str, 'patient_id': str, 'text': str,
                 'text_date': str|datetime, 'text_tag_1'..'text_tag_4': str (optional)}
        - chunk_size_insert_notes: Number of notes inserted per transaction/statement.

    Returns:
        int: number of notes inserted.
    '''
    logger.info(f"Preparing to bulk insert {len(notes)} notes into the database.")
    formatted_notes = [_format_note(note) for note in notes]
    logger.debug("Finished formatting notes. Proceeding with bulk insert.")

    with session_scope(project_engine) as session:
        for i in range(0, len(formatted_notes), chunk_size_insert_notes):
            session.execute(insert(Notes), formatted_notes[i:i + chunk_size_insert_notes])

    logger.info(f"Successfully bulk inserted {len(formatted_notes)} notes into the database.")
    return len(formatted_notes)


@log_function_call
def bulk_upsert_patients(project_engine, patient_ids: list[str],
                         chunk_size_upsert_patients: int = 2000) -> tuple[int, int]:
    '''
    Creates default Patients and Results entries for each of `patient_ids` that
    do not already exist. Preserves upload order via the index_no field, offset
    by however many patients already exist. Existing patients/results are left
    untouched (mongo's $setOnInsert semantics).

    Args:
        - patient_ids (list[str]) : List of all uploaded patient IDs in order.
        - chunk_size_upsert_patients: number of patient/result rows per insert statement.

    Returns:
        tuple[int, int]: (patients_inserted, results_inserted). Row counts reflect
        rows actually inserted; conflicting (pre-existing) patient_ids are skipped.
    '''
    with session_scope(project_engine) as session:
        number_of_patients_in_db = session.execute(
            select(Patients.patient_id)
        ).scalars().all()
        starting_index = len(number_of_patients_in_db)

        notes_summary_by_patient = {
            row.patient_id: row
            for row in session.execute(select(NotesSummary)).scalars().all()
        }

        patient_rows = []
        results_rows = []
        now = datetime.now()

        for offset, p_id in enumerate(patient_ids):
            p_id = str(p_id).strip()
            index_no = starting_index + offset
            summary = notes_summary_by_patient.get(p_id)

            patient_rows.append({
                "patient_id": p_id,
                "admin_locked": False,
                "comments": "",
                "index_no": index_no,
                "locked": False,
                "reviewed": False,
                "last_reviewed_by": None,
                "updated": False,
            })

            results_rows.append({
                "patient_id": p_id,
                "comments": "",
                "event_date": None,
                "event_information": None,
                "index_no": index_no,
                "first_note_date": summary.first_note_date if summary else None,
                "last_note_date": summary.last_note_date if summary else None,
                "max_score": None,
                "max_score_note_date": None,
                "max_score_note_id": None,
                "reviewed_notes": 0,
                "reviewed_sentences": 0,
                "total_notes": summary.num_notes if summary else 0,
                "total_sentences": 0,
                "reviewer": None,
                "last_updated_at": now,
            })

        total_uploaded_patients = 0
        total_uploaded_results = 0

        logger.info("Performing chunked upserts on the Patients table.")
        for i in range(0, len(patient_rows), chunk_size_upsert_patients):
            chunk = patient_rows[i:i + chunk_size_upsert_patients]
            result = session.execute(_upsert_ignore(project_engine, Patients), chunk)
            total_uploaded_patients += result.rowcount if result.rowcount and result.rowcount > 0 else 0

        logger.info("Performing chunked upserts on the Results table.")
        for i in range(0, len(results_rows), chunk_size_upsert_patients):
            chunk = results_rows[i:i + chunk_size_upsert_patients]
            result = session.execute(_upsert_ignore(project_engine, Results), chunk)
            total_uploaded_results += result.rowcount if result.rowcount and result.rowcount > 0 else 0

    logger.info(f"Inserted {total_uploaded_patients} patients and {total_uploaded_results} results.")
    return total_uploaded_patients, total_uploaded_results


@log_function_call
def insert_one_annotation(project_engine, annotation: dict) -> None:
    '''
    Adds an annotation to the database.

    Args:
        project_engine: SQLAlchemy engine for the project database.
        annotation (dict): keys matching the Annotations columns. `note_id` (as
                            produced by the NLP processor) is accepted as an
                            alias for `text_id`.
    '''
    annotation = dict(annotation)
    if "note_id" in annotation:
        annotation["text_id"] = annotation.pop("note_id")
    annotation.setdefault("status", Annotations.STATUS_UNREVIEWED)

    with session_scope(project_engine) as session:
        session.execute(insert(Annotations).values(**annotation))


@log_function_call
def insert_pines_prediction(project_engine, text_id, patient_id, text_date,
                           predicted_score, report_type=None, document_type=None) -> None:
    '''
    Records a PINES prediction for a note. One row per text_id (enforced by a
    unique constraint on PINES.text_id).
    '''
    with session_scope(project_engine) as session:
        session.execute(
            insert(PINES).values(
                text_id=text_id,
                patient_id=patient_id,
                text_date=text_date,
                max_predicted_score=predicted_score,
                report_type=report_type,
                document_type=document_type,
            )
        )


@log_function_call
def add_comment(project_engine, patient_id, comment) -> None:
    """
    Stores a new comment for a patient.

    Args:
        project_engine: SQLAlchemy engine for the project database.
        patient_id (str) : Unique ID for the patient.
        comment (str) : Text of the comment on this patient.
    """
    comment = comment.strip()
    if len(comment) == 0:
        logger.debug(f"Comment deleted on patient # {patient_id}.")
    else:
        logger.info(f"Adding comment to patient #{patient_id}")

    with session_scope(project_engine) as session:
        session.execute(
            update(Patients).where(Patients.patient_id == patient_id).values(comments=comment)
        )

