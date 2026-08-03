"""Adjudication orchestration service.

Ports the Flask ``ops.adjudicate_records`` / ``ops.show_annotation`` /
``ops.save_adjudications`` / ``ops.unlock_patient`` workflow. The per-user review
state is kept in Redis (see :mod:`review_state`) instead of the Flask session;
the :class:`AdjudicationHandler` is reused verbatim. Highlighting is emitted as
character-offset spans (for the client-side ``EvidenceHighlighter``) rather than
server-rendered ``<mark>`` HTML.
"""
from datetime import datetime

from loguru import logger

from .. import db, ops_tasks, queues
from ..adjudication_handler import AdjudicationHandler
from ..cedars_enums import PatientStatus
from . import review_state

DATE_FORMAT = "%Y-%m-%d"


# --- helpers ---------------------------------------------------------------

def _load_patient_data(patient_id):
    """Read the raw inputs needed to initialize a patient (ported verbatim)."""
    patient = db.get_patient_by_id(patient_id)
    return {
        "raw_annotations": db.get_all_annotations_for_patient(patient_id),
        "hide_duplicates": db.get_search_query("hide_duplicates"),
        "stored_event_date": db.get_event_date(patient_id),
        "stored_annotation_id": db.get_event_annotation_id(patient_id),
        "patient_comments": (patient or {}).get("comments", ""),
    }


def _iso(value):
    """Serialize a date/datetime to an ISO date string (``YYYY-MM-DD``)."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date().isoformat()
    return value.isoformat()


def _note_spans(text, annotations_for_note):
    """Compute non-overlapping match spans across the whole note (absolute offsets)."""
    spans = []
    prev_end = 0
    for annotation in annotations_for_note:
        start = annotation["note_start_index"]
        end = annotation["note_end_index"]
        if start < prev_end:
            continue
        spans.append({
            "text": text[start:end],
            "start_pos": start,
            "end_pos": end,
            "match_source": annotation.get("token") or text[start:end],
        })
        prev_end = end
    return spans


def _sentence_spans(text, current_annotation, annotations_for_sentence):
    """Return the current sentence text + match spans relative to that sentence."""
    sentence_str = current_annotation["sentence"]
    try:
        sentence_start = text.lower().index(sentence_str.lower())
    except ValueError:
        sentence_start = 0
    sentence_end = sentence_start + len(sentence_str)
    sentence_text = text[sentence_start:sentence_end]

    spans = []
    prev_end = sentence_start
    for annotation in annotations_for_sentence:
        start = annotation["note_start_index"]
        end = annotation["note_end_index"]
        if (start < prev_end) and (start != 0):
            continue
        spans.append({
            "text": text[start:end],
            "start_pos": max(0, start - sentence_start),
            "end_pos": max(0, end - sentence_start),
            "match_source": annotation.get("token") or text[start:end],
        })
        prev_end = end
    return sentence_text, spans


def _build_annotation_view(handler, comments):
    """Build the annotation payload (scalars from the handler + offset spans).

    We compute the scalar fields directly (rather than calling the handler's
    ``get_annotation_details``) because that method also renders server-side
    ``<mark>`` HTML, which the client no longer uses — highlighting is done from
    the character offsets returned here.
    """
    annotation = handler.get_curr_annotation()
    annotation_id = handler.get_curr_annotation_id()
    note = db.get_annotation_note(annotation_id)
    if not note:
        return None

    annotations_for_note = handler.get_all_annotations_for_curr_note()
    annotations_for_sentence = handler.get_all_annotations_for_curr_sentence()

    text = note["text"]
    sentence_text, sentence_spans = _sentence_spans(text, annotation,
                                                    annotations_for_sentence)
    patient_data = handler.get_patient_data()
    return {
        "pos_start": patient_data["current_index"] + 1,
        "total_pos": len(patient_data["annotation_ids"]),
        "patient_id": str(handler.patient_id),
        "note_id": annotation["note_id"],
        "note_date": _iso(annotation.get("text_date")),
        "event_date": _iso(patient_data.get("event_date")),
        "note_comment": comments or "",
        "tags": [note.get("text_tag_1", ""), note.get("text_tag_2", ""),
                 note.get("text_tag_3", ""), note.get("text_tag_4", ""),
                 note.get("text_tag_5", "")],
        "full_note": text,
        "full_note_evidence": _note_spans(text, annotations_for_note),
        "sentence": sentence_text,
        "sentence_evidence": sentence_spans,
    }


def _annotation_from_state(username, project_id, state):
    """Return the annotation view for the reviewer's current state (show_annotation)."""
    handler = AdjudicationHandler(state["patient_id"])
    handler.load_from_patient_data(state["patient_id"], state["patient_data"])
    view = _build_annotation_view(handler, state.get("patient_comments", ""))
    if view is None:
        return _load_next_patient(username, project_id)
    return {"complete": False, "patient_id": str(state["patient_id"]),
            "annotation": view}


def _setup_patient(username, project_id, patient_id):
    """Initialize a patient for review; returns a view, or ``None`` if it has no
    reviewable annotations (already unlocked + records refreshed)."""
    raw = _load_patient_data(patient_id)
    handler = AdjudicationHandler(patient_id)
    patient_data, annotations_with_duplicates = handler.init_patient_data(
        raw["raw_annotations"], raw["hide_duplicates"],
        raw["stored_event_date"], raw["stored_annotation_id"])

    db.batch_mark_annotation_reviewed(annotations_with_duplicates, username)

    if len(patient_data["annotation_ids"]) > 0:
        db.set_patient_lock_status(patient_id, True)

    patient_status = handler.get_patient_status()

    if patient_status == PatientStatus.NO_ANNOTATIONS:
        logger.info(f"Patient {patient_id} has no annotations. Showing next patient")
        queues.ops_queue.enqueue(ops_tasks.upsert_patient_records,
                                 project_id, patient_id, datetime.now(), username)
        db.set_patient_lock_status(patient_id, False)
        return None

    state = {
        "patient_id": patient_id,
        "patient_data": patient_data,
        "reviewed_annotation_ids": [],
        "patient_comments": raw["patient_comments"],
        "skip_after_event": db.get_search_query(query_key="skip_after_event"),
    }
    review_state.set_state(username, project_id, state)

    result = _annotation_from_state(username, project_id, state)
    result["patient_status"] = patient_status.name
    return result


def _load_next_patient(username, project_id):
    """Select and set up the next reviewable patient (adjudicate_records GET)."""
    visited = set()
    while True:
        patient_id = db.get_patients_to_annotate()
        if patient_id is None or patient_id in visited:
            return {"complete": True}
        visited.add(patient_id)
        result = _setup_patient(username, project_id, patient_id)
        if result is not None:
            return result


def _release_patient(username, project_id, state):
    """Persist + unlock the patient currently held in ``state`` and clear it."""
    patient_id = state.get("patient_id")
    if patient_id is not None:
        if state.get("patient_comments") is not None:
            db.add_comment(patient_id, state["patient_comments"].strip())
        if state.get("reviewed_annotation_ids") is not None:
            db.batch_mark_annotation_reviewed(state["reviewed_annotation_ids"], username)
        queues.ops_queue.enqueue(ops_tasks.upsert_patient_records,
                                 project_id, patient_id, datetime.now(), username)
        db.set_patient_lock_status(patient_id, False)
    review_state.clear_state(username, project_id)


# --- public API ------------------------------------------------------------

def get_current_or_next(username, project_id):
    """Resume the reviewer's current patient, or load the next one."""
    state = review_state.get_state(username, project_id)
    if state and state.get("patient_id") is not None:
        return _annotation_from_state(username, project_id, state)
    return _load_next_patient(username, project_id)


def get_current_annotation(username, project_id):
    """Return the current annotation (show_annotation); load next if no state."""
    state = review_state.get_state(username, project_id)
    if not state or state.get("patient_id") is None:
        return _load_next_patient(username, project_id)
    return _annotation_from_state(username, project_id, state)


def search_patient(username, project_id, search_value):
    """Search for a specific patient, releasing the current one first."""
    state = review_state.get_state(username, project_id)
    if state and state.get("patient_id") is not None:
        _release_patient(username, project_id, state)

    search_value = str(search_value).strip()
    patient_id = None
    is_locked = False
    if search_value:
        patient = db.get_patient_by_id(search_value)
        if patient is not None:
            is_locked = db.get_patient_lock_status(search_value)
            patient_id = patient["patient_id"] if not is_locked else None

    if patient_id is None:
        message = (f"Patient {search_value} is currently being reviewed by another "
                   "user. Showing next patient" if is_locked
                   else f"Patient {search_value} does not exist. Showing next patient")
        result = _load_next_patient(username, project_id)
        result["message"] = message
        return result

    result = _setup_patient(username, project_id, patient_id)
    if result is None:
        return _load_next_patient(username, project_id)
    return result


def save_action(username, project_id, action, comment, event_date):
    """Apply an adjudication action (save_adjudications) and advance."""
    state = review_state.get_state(username, project_id)
    if not state or state.get("patient_id") is None:
        return _load_next_patient(username, project_id)

    handler = AdjudicationHandler(state["patient_id"])
    handler.load_from_patient_data(state["patient_id"], state["patient_data"])
    current_annotation_id = handler.get_curr_annotation_id()
    state["patient_comments"] = (comment or "").strip()
    patient_id = state["patient_id"]
    skip_after_event = state["skip_after_event"]

    db_results_updated = False
    is_shift_performed = False

    if action == "new_date":
        db.revert_skipped_annotations(patient_id)
        handler.reset_all_skipped()
        new_date = datetime.strptime(event_date, DATE_FORMAT)
        annotations_after_event = []
        if skip_after_event:
            annotations_after_event = db.get_annotations_post_event(patient_id, new_date)
        db_results_updated = True
        handler.mark_event_date(new_date, current_annotation_id, annotations_after_event)
        queues.ops_queue.enqueue(
            ops_tasks.enter_patient_date, project_id, patient_id, new_date,
            current_annotation_id, username, state["patient_comments"],
            state["reviewed_annotation_ids"], datetime.now(), skip_after_event,
            handler.is_patient_reviewed())
    elif action == "del_date":
        db_results_updated = True
        handler.delete_event_date()
        queues.ops_queue.enqueue(
            ops_tasks.delete_patient_date, project_id, patient_id,
            current_annotation_id, username, state["patient_comments"],
            state["reviewed_annotation_ids"], datetime.now(),
            handler.is_patient_reviewed())
    elif action == "adjudicate":
        state["reviewed_annotation_ids"].append(current_annotation_id)
        handler._adjudicate_annotation()  # noqa: SLF001 (reused verbatim)
    else:
        # Navigation shift (prev/next/first/last/+-10) or a no-op "comment" save.
        handler.perform_shift(action)
        is_shift_performed = True

    state["patient_data"] = handler.get_patient_data()

    if handler.is_patient_reviewed() and not is_shift_performed:
        db.mark_patient_reviewed(patient_id, reviewed_by=username)
        if not db_results_updated:
            queues.ops_queue.enqueue(
                ops_tasks.update_patient_data, project_id, patient_id,
                state["patient_comments"], username,
                state["reviewed_annotation_ids"], datetime.now())
        review_state.clear_state(username, project_id)
        # Match the Flask redirect: move straight to the next patient.
        result = _load_next_patient(username, project_id)
        result["patient_complete"] = True
        return result

    review_state.set_state(username, project_id, state)
    return _annotation_from_state(username, project_id, state)


def unlock(username, project_id):
    """Release the reviewer's current patient (unlock_patient)."""
    state = review_state.get_state(username, project_id)
    message = "No patient to unlock."
    if state and state.get("patient_id") is not None:
        patient_id = state["patient_id"]
        _release_patient(username, project_id, state)
        message = f"Unlocking patient # {patient_id}."
    return {"message": message}
