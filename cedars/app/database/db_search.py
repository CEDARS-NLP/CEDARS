'''
db_search.py

Read-only queries against a project's database: annotations, patients, notes,
note-date summaries, counts, and PINES prediction lookups.
'''

from typing import Optional

from sqlalchemy import select, func, exists, and_

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_session import session_scope
from cedars.app.database.project_table_creation import (
    Annotations, Events, Notes, NotesSummary, PINES, Patients, Results,
)

# ---------------------------------------------------------------------------
# Annotation queries
# ---------------------------------------------------------------------------

@log_function_call
def get_all_annotations_for_note(project_engine, text_id):
    '''
    All non-negated annotations for a note, ordered by text_date then sentence_number.
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Annotations)
            .where(Annotations.text_id == text_id, Annotations.isNegated == False)  # noqa: E712
            .order_by(Annotations.text_date, Annotations.sentence_number)
        )
        return session.execute(stmt).scalars().all()


@log_function_call
def get_all_annotations_for_sentence(project_engine, text_id, sentence_number):
    '''
    All non-negated annotations for a specific sentence in a note, ordered by
    text_date then note_start_index.
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Annotations)
            .where(Annotations.text_id == text_id,
                  Annotations.sentence_number == sentence_number,
                  Annotations.isNegated == False)  # noqa: E712
            .order_by(Annotations.text_date, Annotations.note_start_index)
        )
        return session.execute(stmt).scalars().all()


@log_function_call
def get_all_annotations_for_patient(project_engine, patient_id):
    '''
    All non-negated annotations for a patient, ordered by text_date, text_id, note_start_index.
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Annotations)
            .where(Annotations.patient_id == patient_id, Annotations.isNegated == False)  # noqa: E712
            .order_by(Annotations.text_date, Annotations.text_id, Annotations.note_start_index)
        )
        return session.execute(stmt).scalars().all()


@log_function_call
def get_annotation(project_engine, annotation_id):
    '''
    A single annotation by its primary key, or None.
    '''
    with session_scope(project_engine) as session:
        return session.get(Annotations, annotation_id)


@log_function_call
def get_annotation_note(project_engine, annotation_id):
    '''
    The Notes row linked to a given annotation, or None.
    '''
    with session_scope(project_engine) as session:
        annotation = session.get(Annotations, annotation_id)
        if annotation is None:
            return None

        return session.execute(
            select(Notes).where(Notes.text_id == annotation.text_id)
        ).scalar_one_or_none()


@log_function_call
def get_patient_annotation_ids(project_engine, patient_id,
                               status=Annotations.STATUS_UNREVIEWED, key="annotation_id"):
    '''
    Annotation IDs (or sentence strings, if key="sentence") for a patient's
    non-negated annotations matching `status`, ordered by text_id, text_date,
    sentence_number.
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Annotations)
            .where(Annotations.patient_id == patient_id,
                  Annotations.isNegated == False,  # noqa: E712
                  Annotations.status == status)
            .order_by(Annotations.text_id, Annotations.text_date, Annotations.sentence_number)
        )
        annotations = session.execute(stmt).scalars().all()

        if key == "sentence":
            return [
                f'{a.text_id}:{str(a.text_date)[:10]}:{" ".join(a.sentence.split())}'
                for a in annotations
            ]

        return [str(getattr(a, key)) for a in annotations]


@log_function_call
def get_annotations_post_event(project_engine, patient_id, event_date) -> list[int]:
    '''
    IDs of unreviewed annotations for a patient on/after `event_date`.
    '''
    with session_scope(project_engine) as session:
        stmt = select(Annotations.annotation_id).where(
            Annotations.patient_id == patient_id,
            Annotations.text_date >= event_date,
            Annotations.status == Annotations.STATUS_UNREVIEWED,
        )
        return list(session.execute(stmt).scalars().all())


@log_function_call
def get_all_annotations(project_engine):
    '''
    Every annotation in the project database.
    '''
    with session_scope(project_engine) as session:
        return session.execute(select(Annotations)).scalars().all()


@log_function_call
def get_annotated_notes_for_patient(project_engine, patient_id) -> list[str]:
    '''
    Distinct note (text_id) values that have at least one annotation for this
    patient, in first-seen order (text_date, text_id, note_start_index).
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Annotations.text_id)
            .where(Annotations.patient_id == patient_id)
            .order_by(Annotations.text_date, Annotations.text_id, Annotations.note_start_index)
        )
        text_ids = session.execute(stmt).scalars().all()

    return list(dict.fromkeys(text_ids))


# ---------------------------------------------------------------------------
# Patient queries
# ---------------------------------------------------------------------------

@log_function_call
def get_patient_by_id(project_engine, patient_id):
    '''
    A single patient row, or None.
    '''
    with session_scope(project_engine) as session:
        return session.get(Patients, patient_id)


@log_function_call
def get_patient(project_engine) -> Optional[str]:
    '''
    The first unreviewed, unlocked patient_id, in upload order (index_no).
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Patients.patient_id)
            .where(Patients.reviewed == False, Patients.locked == False)  # noqa: E712
            .order_by(Patients.index_no)
            .limit(1)
        )
        return session.execute(stmt).scalar_one_or_none()


@log_function_call
def get_patients_to_annotate(project_engine) -> Optional[str]:
    '''
    The first patient (in upload order) that has unreviewed annotations.
    '''
    for patient_id in get_patient_ids(project_engine):
        if len(get_patient_annotation_ids(project_engine, patient_id)) > 0:
            return patient_id

    return None


@log_function_call
def get_all_patient_ids(project_engine) -> list[str]:
    '''
    Every patient_id in the project, in upload order (index_no).
    '''
    with session_scope(project_engine) as session:
        stmt = select(Patients.patient_id).order_by(Patients.index_no)
        return list(session.execute(stmt).scalars().all())


@log_function_call
def get_patient_ids(project_engine) -> list[str]:
    '''
    Unreviewed, unlocked patient_ids, in upload order (index_no).
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(Patients.patient_id)
            .where(Patients.reviewed == False, Patients.locked == False)  # noqa: E712
            .order_by(Patients.index_no)
        )
        return list(session.execute(stmt).scalars().all())


@log_function_call
def get_patient_lock_status(project_engine, patient_id) -> Optional[bool]:
    '''
    Whether a patient is currently locked, or None if the patient doesn't exist.
    '''
    with session_scope(project_engine) as session:
        patient = session.get(Patients, patient_id)
        return patient.locked if patient is not None else None


@log_function_call
def get_patient_reviewer(project_engine, patient_id) -> Optional[str]:
    '''
    The user who last reviewed this patient, or None if unset.
    '''
    with session_scope(project_engine) as session:
        patient = session.get(Patients, patient_id)

    if patient is None or patient.last_reviewed_by is None or patient.last_reviewed_by.strip() == "":
        return None

    return patient.last_reviewed_by


@log_function_call
def patient_results_exist(project_engine, patient_id) -> bool:
    '''
    Whether a Results row already exists for this patient.
    '''
    with session_scope(project_engine) as session:
        return session.execute(
            select(exists().where(Results.patient_id == patient_id))
        ).scalar()


# ---------------------------------------------------------------------------
# Event queries (Events table: one row per patient)
# ---------------------------------------------------------------------------

@log_function_call
def get_event_date(project_engine, patient_id):
    '''
    The recorded clinical-event date for a patient, or None.
    '''
    with session_scope(project_engine) as session:
        event = session.execute(
            select(Events).where(Events.patient_id == patient_id)
        ).scalar_one_or_none()

    return event.event_date if event is not None else None


@log_function_call
def get_event_annotation_id(project_engine, patient_id):
    '''
    The annotation_id where a patient's clinical event was found, or None.
    '''
    with session_scope(project_engine) as session:
        event = session.execute(
            select(Events).where(Events.patient_id == patient_id)
        ).scalar_one_or_none()

    return event.annotation_id if event is not None else None


# ---------------------------------------------------------------------------
# Note queries
# ---------------------------------------------------------------------------

@log_function_call
def get_all_notes(project_engine, patient_id):
    '''
    Every note for a patient.
    '''
    with session_scope(project_engine) as session:
        stmt = select(Notes).where(Notes.patient_id == patient_id)
        return session.execute(stmt).scalars().all()


@log_function_call
def get_patient_notes(project_engine, patient_id, reviewed=False):
    '''
    Notes for a patient filtered by reviewed status.
    '''
    with session_scope(project_engine) as session:
        stmt = select(Notes).where(Notes.patient_id == patient_id, Notes.reviewed == reviewed)
        return session.execute(stmt).scalars().all()


@log_function_call
def get_note_date(project_engine, text_id):
    '''
    The text_date of a note.
    '''
    with session_scope(project_engine) as session:
        note = session.get(Notes, text_id)
        return note.text_date if note is not None else None


@log_function_call
def get_documents_to_annotate(project_engine, patient_id=None):
    '''
    Notes with no annotations that have not been marked reviewed, optionally
    restricted to a single patient. Implemented as a `NOT EXISTS` correlated
    subquery so it stays index-friendly (idx_annotations_patient_text) at scale.
    '''
    with session_scope(project_engine) as session:
        no_annotations = ~exists().where(Annotations.text_id == Notes.text_id)
        conditions = [Notes.reviewed != True, no_annotations]  # noqa: E712
        if patient_id:
            conditions.append(Notes.patient_id == patient_id)

        stmt = select(Notes).where(and_(*conditions))
        return session.execute(stmt).scalars().all()


# ---------------------------------------------------------------------------
# NotesSummary queries
# ---------------------------------------------------------------------------

@log_function_call
def get_notes_summary(project_engine, patient_id):
    '''
    Retrieves the summary of notes for a specific patient from the database.
    '''
    with session_scope(project_engine) as session:
        return session.execute(
            select(NotesSummary).where(NotesSummary.patient_id == patient_id)
        ).scalar_one_or_none()


@log_function_call
def get_all_notes_summaries(project_engine) -> dict:
    '''
    A dict of every patient's note summary, keyed by patient_id.
    '''
    with session_scope(project_engine) as session:
        summaries = session.execute(select(NotesSummary)).scalars().all()

    return {summary.patient_id: summary for summary in summaries}


@log_function_call
def get_first_note_date_for_patient(project_engine, patient_id, first_note_date=None):
    '''
    The earliest note date for a patient. Returns `first_note_date` unchanged
    if it was already provided (cache passthrough), else looks it up.
    '''
    if first_note_date is not None:
        return first_note_date

    summary = get_notes_summary(project_engine, patient_id)
    return summary.first_note_date if summary is not None else None


@log_function_call
def get_last_note_date_for_patient(project_engine, patient_id, last_note_date=None):
    '''
    The latest note date for a patient. Returns `last_note_date` unchanged if
    it was already provided (cache passthrough), else looks it up.
    '''
    if last_note_date is not None:
        return last_note_date

    summary = get_notes_summary(project_engine, patient_id)
    return summary.last_note_date if summary is not None else None


@log_function_call
def get_num_patient_notes(project_engine, patient_id, num_notes=None) -> int:
    '''
    The number of notes for a patient. Returns `num_notes` unchanged if it was
    already provided (cache passthrough), else looks it up (0 if unknown).
    '''
    if num_notes is not None:
        return num_notes

    summary = get_notes_summary(project_engine, patient_id)
    return summary.num_notes if summary is not None else 0


# ---------------------------------------------------------------------------
# Generic counts
# ---------------------------------------------------------------------------

@log_function_call
def get_total_counts(project_engine, model, **filters) -> int:
    '''
    Count of rows in `model` (an ORM class from project_table_creation.py)
    matching the given column=value filters.

    Args:
        model: e.g. Notes, Patients, Annotations, ...
        **filters: column=value equality filters.
    '''
    with session_scope(project_engine) as session:
        stmt = select(func.count()).select_from(model)
        for column, value in filters.items():
            stmt = stmt.where(getattr(model, column) == value)
        return session.execute(stmt).scalar_one()


# ---------------------------------------------------------------------------
# PINES prediction queries
# ---------------------------------------------------------------------------

@log_function_call
def get_note_prediction_from_db(project_engine, text_id) -> Optional[float]:
    '''
    The predicted score for a note, rounded to 2 decimal places, or None.
    '''
    with session_scope(project_engine) as session:
        prediction = session.execute(
            select(PINES).where(PINES.text_id == text_id)
        ).scalar_one_or_none()

    if prediction is None:
        return None

    return round(prediction.max_predicted_score, 2)


@log_function_call
def get_max_prediction_score(project_engine, patient_id) -> Optional[dict]:
    '''
    The highest predicted score for a patient's notes and the text_id it came from.

    Returns:
        {"patient_id": ..., "max_score": ..., "text_id": ...} or None if the
        patient has no predictions.
    '''
    with session_scope(project_engine) as session:
        max_score = session.execute(
            select(func.max(PINES.max_predicted_score)).where(PINES.patient_id == patient_id)
        ).scalar_one_or_none()

        if max_score is None:
            return None

        text_id = session.execute(
            select(PINES.text_id).where(PINES.patient_id == patient_id,
                                        PINES.max_predicted_score == max_score)
            .limit(1)
        ).scalar_one_or_none()

    return {"patient_id": patient_id, "max_score": max_score, "text_id": text_id}


@log_function_call
def get_formatted_patient_predictions(project_engine, patient_id) -> Optional[str]:
    '''
    Every prediction for a patient's notes, formatted as one
    "text_id:YYYY-MM-DD:score" line per note, newline-separated.

    Returns:
        str, or None if the patient has no predictions.
    '''
    with session_scope(project_engine) as session:
        stmt = (
            select(PINES.text_id, PINES.text_date, PINES.max_predicted_score)
            .where(PINES.patient_id == patient_id)
            .order_by(PINES.text_date)
        )
        rows = session.execute(stmt).all()

    if not rows:
        return None

    return "\n".join(
        f"{text_id}:{text_date}:{score}" for text_id, text_date, score in rows
    )
