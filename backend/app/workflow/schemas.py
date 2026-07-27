"""Pydantic schemas for the v1-style workflow API."""

from datetime import date

from pydantic import BaseModel


class SaveQueryRequest(BaseModel):
    """Search query + options (v1 upload_query form)."""

    query: str
    hide_duplicates: bool = True
    skip_after_event: bool = True
    use_negation: bool = False
    nlp_apply: bool = False  # run the active predictor after NLP


class SaveQueryResponse(BaseModel):
    changed: bool
    dispatched_patients: int
    mode: str  # "queued" | "sync" | "none"
    job_id: str | None = None


class NlpRunResponse(BaseModel):
    dispatched_patients: int
    mode: str  # "queued" | "sync"
    job_id: str | None = None


class ReviewActionRequest(BaseModel):
    """One adjudication action (v1 save_adjudications submit_button)."""

    # adjudicate | new_date | del_date | first_anno | prev_10 | prev_1 | next_1 | next_10 | last_anno
    action: str
    comment: str = ""
    event_date: str | None = None  # YYYY-MM-DD, required for action == "new_date"


class AnnotationView(BaseModel):
    """The annotation shown to the reviewer (v1 get_annotation_details)."""

    pos_start: int
    total_pos: int
    patient_id: str
    note_id: str
    note_date: date | None = None
    event_date: date | None = None
    note_comment: str = ""
    highlighted_sentence: str
    full_note: str
    tags: list[str] = []


class NextPatientResponse(BaseModel):
    complete: bool = False
    patient_id: str | None = None
    patient_status: str | None = None
    annotation: AnnotationView | None = None


class ActionResponse(BaseModel):
    patient_complete: bool = False
    annotation: AnnotationView | None = None


class SimpleJobResponse(BaseModel):
    """Generic response for internal-process operations."""

    status: str
    detail: str = ""
    affected: int | None = None
