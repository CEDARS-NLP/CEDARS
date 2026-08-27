'''
db_updates.py

Mutations against a project's database: annotation/note/patient review-status
transitions, event-date tracking, patient locking, and the RESULTS rollup.

Note: ReviewerLog.reviewer and Results.reviewer are FKs to ProjectUsers.user_id.
Callers that pass system reviewer names (e.g. "CEDARS", "PINES", as used by
nlpprocessor.py) must ensure a matching ProjectUsers row exists, or the
database will reject the write - this mirrors an existing assumption in the
mongo implementation that was never enforced there.
'''

from datetime import datetime, timezone

from loguru import logger

from sqlalchemy import delete, func, insert, select, update

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_search import (
    get_all_patient_ids,
    get_annotation,
    get_first_note_date_for_patient,
    get_last_note_date_for_patient,
    get_max_prediction_score,
    get_note_date,
    get_num_patient_notes,
    get_patient_annotation_ids,
    get_patient_by_id,
    get_patient_reviewer,
    get_event_annotation_id,
    get_event_date,
    patient_results_exist,
)
from cedars.app.database.db_session import session_scope
from cedars.app.database.project_table_creation import (
    Annotations, Events, Notes, NotesSummary, Patients, ReviewerLog, Results,
)

logger.enable(__name__)


# ---------------------------------------------------------------------------
# Annotation review-status transitions
# ---------------------------------------------------------------------------

@log_function_call
def mark_annotation_reviewed(project_engine, annotation_id, reviewed_by) -> None:
    '''
    Marks an annotation as reviewed, logs the review, and - if no unreviewed
    annotations remain for its note - marks the note reviewed too.
    '''
    logger.debug(f"Marking annotation #{annotation_id} as reviewed.")

    with session_scope(project_engine) as session:
        annotation = session.get(Annotations, annotation_id)
        if annotation is None:
            logger.warning(f"Annotation #{annotation_id} not found.")
            return

        text_id = annotation.text_id
        session.execute(
            update(Annotations).where(Annotations.annotation_id == annotation_id)
            .values(status=Annotations.STATUS_REVIEWED)
        )
        session.execute(
            insert(ReviewerLog).values(text_id=text_id, annotation_id=annotation_id,
                                       reviewer=reviewed_by)
        )

        remaining_unreviewed = session.execute(
            select(func.count()).select_from(Annotations)
            .where(Annotations.text_id == text_id,
                  Annotations.status == Annotations.STATUS_UNREVIEWED)
        ).scalar_one()

    if remaining_unreviewed == 0:
        mark_note_reviewed(project_engine, text_id, reviewed_by)


@log_function_call
def batch_mark_annotation_reviewed(project_engine, annotation_ids, reviewed_by) -> None:
    '''
    Marks a batch of annotations as reviewed, logs each review, and marks any
    notes with no more unreviewed annotations as reviewed.
    '''
    logger.debug(f"Marking annotations {annotation_ids} as reviewed.")

    with session_scope(project_engine) as session:
        text_ids = list(session.execute(
            select(Annotations.text_id).where(Annotations.annotation_id.in_(annotation_ids))
        ).scalars().all())
        distinct_text_ids = list(dict.fromkeys(text_ids))

        session.execute(
            update(Annotations).where(Annotations.annotation_id.in_(annotation_ids))
            .values(status=Annotations.STATUS_REVIEWED)
        )
        session.execute(
            insert(ReviewerLog),
            [{"text_id": tid, "annotation_id": aid, "reviewer": reviewed_by}
             for tid, aid in zip(text_ids, annotation_ids)]
        )

        remaining_counts = dict(session.execute(
            select(Annotations.text_id, func.count())
            .where(Annotations.text_id.in_(distinct_text_ids),
                  Annotations.status == Annotations.STATUS_UNREVIEWED)
            .group_by(Annotations.text_id)
        ).all())

    notes_to_mark_reviewed = [
        text_id for text_id in distinct_text_ids if remaining_counts.get(text_id, 0) == 0
    ]

    if notes_to_mark_reviewed:
        batch_mark_note_reviewed(project_engine, notes_to_mark_reviewed, reviewed_by)


@log_function_call
def revert_annotation_reviewed(project_engine, annotation_id, reviewed_by) -> None:
    '''
    Reverts an annotation to unreviewed, cascading to its note and patient.
    Used when a patient's event_date is deleted.
    '''
    logger.debug(f"Marking annotation #{annotation_id} as un-reviewed.")

    with session_scope(project_engine) as session:
        annotation = session.get(Annotations, annotation_id)
        if annotation is None:
            logger.warning(f"Annotation #{annotation_id} not found.")
            return

        text_id = annotation.text_id
        session.execute(
            update(Annotations).where(Annotations.annotation_id == annotation_id)
            .values(status=Annotations.STATUS_UNREVIEWED)
        )

    revert_note_reviewed(project_engine, text_id, reviewed_by)


@log_function_call
def mark_annotations_post_event(project_engine, patient_id: str, event_date) -> None:
    '''
    Marks unreviewed annotations on/after `event_date` as SKIPPED - they occur
    after the recorded clinical event and don't need manual review.
    '''
    logger.info(f"Skipping future annotations for patient {patient_id} after {event_date}.")

    with session_scope(project_engine) as session:
        session.execute(
            update(Annotations).where(
                Annotations.patient_id == patient_id,
                Annotations.text_date >= event_date,
                Annotations.status == Annotations.STATUS_UNREVIEWED,
            ).values(status=Annotations.STATUS_SKIPPED)
        )


@log_function_call
def revert_skipped_annotations(project_engine, patient_id: str) -> None:
    '''
    Reverts SKIPPED annotations back to UNREVIEWED for a patient, e.g. when
    their event_date is deleted.
    '''
    with session_scope(project_engine) as session:
        session.execute(
            update(Annotations).where(
                Annotations.patient_id == patient_id,
                Annotations.status == Annotations.STATUS_SKIPPED,
            ).values(status=Annotations.STATUS_UNREVIEWED)
        )


@log_function_call
def update_annotation_reviewed(project_engine, note_id: str) -> int:
    '''
    Marks every annotation for a note as reviewed.

    Returns:
        int: number of annotations updated.
    '''
    with session_scope(project_engine) as session:
        result = session.execute(
            update(Annotations).where(Annotations.text_id == note_id)
            .values(status=Annotations.STATUS_REVIEWED)
        )
        return result.rowcount


# ---------------------------------------------------------------------------
# Note review-status transitions
# ---------------------------------------------------------------------------

@log_function_call
def mark_note_reviewed(project_engine, note_id, reviewed_by: str) -> None:
    '''
    Marks a note as reviewed and logs the review.
    '''
    logger.debug(f"Marking note #{note_id} as reviewed.")
    with session_scope(project_engine) as session:
        session.execute(
            update(Notes).where(Notes.text_id == note_id).values(reviewed=True)
        )
        session.execute(
            insert(ReviewerLog).values(text_id=note_id, annotation_id=None, reviewer=reviewed_by)
        )


@log_function_call
def batch_mark_note_reviewed(project_engine, note_ids, reviewed_by: str) -> None:
    '''
    Marks a batch of notes as reviewed and logs each review.
    '''
    logger.debug(f"Marking notes {note_ids} as reviewed.")
    with session_scope(project_engine) as session:
        session.execute(
            update(Notes).where(Notes.text_id.in_(note_ids)).values(reviewed=True)
        )
        session.execute(
            insert(ReviewerLog),
            [{"text_id": note_id, "annotation_id": None, "reviewer": reviewed_by}
             for note_id in note_ids]
        )


@log_function_call
def revert_note_reviewed(project_engine, note_id, reviewed_by: str) -> None:
    '''
    Reverts a note to unreviewed, cascading to its patient.
    '''
    logger.debug(f"Marking note #{note_id} as un-reviewed.")
    with session_scope(project_engine) as session:
        note = session.get(Notes, note_id)
        if note is None:
            logger.warning(f"Note #{note_id} not found.")
            return

        patient_id = note.patient_id
        session.execute(
            update(Notes).where(Notes.text_id == note_id).values(reviewed=False)
        )

    revert_patient_reviewed(project_engine, patient_id, reviewed_by)


# ---------------------------------------------------------------------------
# Patient review-status transitions
# ---------------------------------------------------------------------------

@log_function_call
def revert_patient_reviewed(project_engine, patient_id, reviewed_by: str) -> None:
    '''
    Marks a patient as unreviewed.
    '''
    logger.debug(f"Marking patient #{patient_id} as un-reviewed.")
    with session_scope(project_engine) as session:
        session.execute(
            update(Patients).where(Patients.patient_id == patient_id)
            .values(reviewed=False, last_reviewed_by=reviewed_by)
        )


@log_function_call
def mark_patient_reviewed(project_engine, patient_id: str, reviewed_by: str,
                          is_reviewed=True) -> None:
    '''
    Marks a patient as reviewed and recomputes their RESULTS row.
    '''
    logger.debug(f"Marking patient #{patient_id} as reviewed.")
    with session_scope(project_engine) as session:
        session.execute(
            update(Patients).where(Patients.patient_id == patient_id)
            .values(reviewed=is_reviewed, last_reviewed_by=reviewed_by)
        )

    logger.info(f"Storing results for patient #{patient_id}")
    upsert_patient_records(project_engine, patient_id, datetime.now(), updated_by=reviewed_by)


@log_function_call
def reset_patient_reviewed(project_engine) -> None:
    '''
    Resets every patient/note to unreviewed and clears all recorded events.
    '''
    with session_scope(project_engine) as session:
        session.execute(
            update(Patients).values(reviewed=False, last_reviewed_by="", comments="")
        )
        session.execute(update(Notes).values(reviewed=False))
        session.execute(delete(Events))


@log_function_call
def set_patient_lock_status(project_engine, patient_id: str, status: bool) -> None:
    '''
    Locks or unlocks a patient (prevents concurrent review by multiple users).
    '''
    with session_scope(project_engine) as session:
        session.execute(
            update(Patients).where(Patients.patient_id == patient_id).values(locked=status)
        )


@log_function_call
def remove_all_locked(project_engine) -> None:
    '''
    Unlocks every patient. Called on server shutdown.
    '''
    with session_scope(project_engine) as session:
        session.execute(update(Patients).values(locked=False))


# ---------------------------------------------------------------------------
# Event date/annotation tracking (Events: one row per patient)
# ---------------------------------------------------------------------------

def _upsert_event(session, patient_id: str, **values) -> None:
    '''
    Updates the Events row for `patient_id`, creating it first if necessary.
    '''
    event = session.execute(
        select(Events).where(Events.patient_id == patient_id)
    ).scalar_one_or_none()

    if event is None:
        defaults = {"patient_id": patient_id, "has_event": False, "annotation_id": None,
                   "event_date": None}
        defaults.update(values)
        session.execute(insert(Events).values(**defaults))
    else:
        session.execute(
            update(Events).where(Events.patient_id == patient_id).values(**values)
        )


@log_function_call
def update_event_date(project_engine, patient_id: str, new_date, annotation_id) -> None:
    '''
    Records the clinical event date (and the annotation it was found in) for a patient.
    '''
    logger.debug(f"Updating date on patient #{patient_id} to {new_date}.")
    with session_scope(project_engine) as session:
        _upsert_event(session, patient_id, event_date=new_date, has_event=True,
                      annotation_id=annotation_id)


@log_function_call
def delete_event_date(project_engine, patient_id: str) -> None:
    '''
    Clears the clinical event date and its linked annotation for a patient.
    '''
    logger.debug(f"Deleting date on patient #{patient_id}.")
    with session_scope(project_engine) as session:
        _upsert_event(session, patient_id, event_date=None, has_event=False, annotation_id=None)


@log_function_call
def update_event_annotation_id(project_engine, patient_id: str, annotation_id) -> None:
    '''
    Records which annotation a patient's clinical event was found in.
    '''
    logger.debug(f"Updating event_annotation_id on patient #{patient_id}.")
    with session_scope(project_engine) as session:
        _upsert_event(session, patient_id, annotation_id=annotation_id)


@log_function_call
def delete_event_annotation_id(project_engine, patient_id: str) -> None:
    '''
    Clears the annotation linked to a patient's clinical event.
    '''
    logger.debug(f"Deleting event_annotation_id on patient #{patient_id}.")
    with session_scope(project_engine) as session:
        _upsert_event(session, patient_id, annotation_id=None)


# ---------------------------------------------------------------------------
# RESULTS rollup
# ---------------------------------------------------------------------------

@log_function_call
def upsert_patient_records(project_engine, patient_id: str,
                           insert_datetime: datetime = None, updated_by: str = None) -> None:
    '''
    Recomputes and stores the RESULTS row for a patient.

    Note: mongo's RESULTS also cached free-text `sentences` and `predicted_notes`
    fields; the SQL Results table has no equivalent columns, so those values are
    computed here (via get_patient_annotation_ids/get_formatted_patient_predictions)
    only to derive counts, not persisted verbatim.
    '''
    num_reviewed_notes = get_total_counts_notes_reviewed(project_engine, patient_id)

    reviewed_sentences = get_patient_annotation_ids(
        project_engine, patient_id, status=Annotations.STATUS_REVIEWED, key="sentence")
    unreviewed_sentences = get_patient_annotation_ids(
        project_engine, patient_id, status=Annotations.STATUS_UNREVIEWED, key="sentence")
    total_sentences = len(reviewed_sentences) + len(unreviewed_sentences)

    event_date = get_event_date(project_engine, patient_id)
    key_annotation_id = get_event_annotation_id(project_engine, patient_id)
    event_information = ""
    if event_date and key_annotation_id:
        key_annotation = get_annotation(project_engine, key_annotation_id)
        if key_annotation is not None:
            event_information = f"{key_annotation.sentence}\nNote_id : {key_annotation.text_id}"

    first_note_date = get_first_note_date_for_patient(project_engine, patient_id)
    last_note_date = get_last_note_date_for_patient(project_engine, patient_id)

    patient = get_patient_by_id(project_engine, patient_id)
    comments = patient.comments if patient is not None else ""

    reviewer = updated_by if updated_by is not None else get_patient_reviewer(project_engine, patient_id)

    max_score = None
    max_score_note_id = None
    max_score_note_date = None
    try:
        best = get_max_prediction_score(project_engine, patient_id)
        if best:
            max_score = best["max_score"]
            max_score_note_id = best["text_id"]
            max_score_note_date = get_note_date(project_engine, max_score_note_id)
        else:
            logger.info(f"No prediction scores found for patient: {patient_id}")
    except Exception as exc:  # pylint: disable=broad-except
        logger.info(f"Error in upsert_patient_records - get_max_prediction_score: {exc}")
        logger.info(f"PINES results not available for patient: {patient_id}")

    patient_results = {
        "reviewed_notes": num_reviewed_notes,
        "total_notes": get_num_patient_notes(project_engine, patient_id),
        "total_sentences": total_sentences,
        "reviewed_sentences": len(reviewed_sentences),
        "event_date": event_date,
        "event_information": event_information,
        "first_note_date": first_note_date,
        "last_note_date": last_note_date,
        "comments": comments,
        "reviewer": reviewer,
        "max_score_note_id": max_score_note_id,
        "max_score_note_date": max_score_note_date,
        "max_score": max_score,
        "last_updated_at": insert_datetime or datetime.now(timezone.utc),
    }

    logger.info(f"Updating results for patient #{patient_id}.")
    with session_scope(project_engine) as session:
        session.execute(
            update(Results).where(Results.patient_id == patient_id).values(**patient_results)
        )


def get_total_counts_notes_reviewed(project_engine, patient_id) -> int:
    '''
    Number of reviewed notes for a patient. Kept private/local to avoid a
    circular import on db_search's generic get_total_counts.
    '''
    with session_scope(project_engine) as session:
        return session.execute(
            select(func.count()).select_from(Notes)
            .where(Notes.patient_id == patient_id, Notes.reviewed == True)  # noqa: E712
        ).scalar_one()


@log_function_call
def update_patient_results(project_engine, update_existing_results: bool = False) -> None:
    '''
    Recomputes RESULTS rows for every patient that doesn't have one yet, or for
    every patient if `update_existing_results` is True.
    '''
    for patient_id in get_all_patient_ids(project_engine):
        if update_existing_results or not patient_results_exist(project_engine, patient_id):
            upsert_patient_records(project_engine, patient_id)


# ---------------------------------------------------------------------------
# NotesSummary rebuild
# ---------------------------------------------------------------------------

@log_function_call
def update_notes_summary(project_engine) -> None:
    '''
    Rebuilds the NotesSummary table from Notes (per-patient min/max date and count).
    '''
    with session_scope(project_engine) as session:
        agg = select(
            Notes.patient_id.label("patient_id"),
            func.min(Notes.text_date).label("first_note_date"),
            func.max(Notes.text_date).label("last_note_date"),
            func.count().label("num_notes"),
        ).group_by(Notes.patient_id)

        session.execute(delete(NotesSummary))
        session.execute(
            insert(NotesSummary).from_select(
                ["patient_id", "first_note_date", "last_note_date", "num_notes"],
                agg,
            )
        )
