"""Pydantic request/response models for the CEDARS API.

Models are grouped by workflow area and expanded as each phase is ported.
"""
from typing import Literal, Optional

from pydantic import BaseModel


# --- auth ---------------------------------------------------------------

class RegisterRequest(BaseModel):
    username: str
    password: str
    confirm_password: str


class LoginRequest(BaseModel):
    username: str
    password: str


class UserOut(BaseModel):
    username: str
    is_admin: bool


class LoginResponse(BaseModel):
    message: str
    user: UserOut


class MessageResponse(BaseModel):
    message: str


# --- projects -----------------------------------------------------------

class ProjectCreate(BaseModel):
    name: str
    description: Optional[str] = ""


class ProjectUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None


class ProjectOut(BaseModel):
    id: str
    name: str
    description: Optional[str] = ""
    owner: Optional[str] = None
    role: Optional[str] = None
    created_at: Optional[str] = None


ProjectRole = Literal["admin", "annotator"]


class ProjectMemberCreate(BaseModel):
    username: str
    role: ProjectRole = "annotator"


class ProjectMemberUpdate(BaseModel):
    role: ProjectRole


class ProjectMemberOut(BaseModel):
    username: str
    role: ProjectRole
    added_by: str


# --- data ---------------------------------------------------------------

class DataFileOut(BaseModel):
    key: str
    name: str
    size: int


class IngestResponse(BaseModel):
    filename: str
    message: str
    total_rows: int
    total_chunks: int
    total_patients: int


# --- query / NLP --------------------------------------------------------

class QueryUpdate(BaseModel):
    query: str
    nlp_apply: bool = False
    hide_duplicates: bool = True
    skip_after_event: bool = False


class QueryOut(BaseModel):
    query: str = ""
    nlp_apply: bool = False
    hide_duplicates: bool = True
    skip_after_event: bool = False
    exclude_negated: bool = False


class SaveQueryResponse(BaseModel):
    new_query: bool
    dispatched: int
    message: str


class NlpRunResponse(BaseModel):
    dispatched: int
    message: str


class NlpStatusOut(BaseModel):
    total_patients: int
    tasks_in_progress: int
    tasks_completed: int
    tasks_failed: int = 0


# --- adjudication -------------------------------------------------------

class EvidenceSpan(BaseModel):
    text: str
    start_pos: int
    end_pos: int
    match_source: str


class AnnotationView(BaseModel):
    pos_start: int
    total_pos: int
    patient_id: str
    note_id: str
    note_date: Optional[str] = None
    event_date: Optional[str] = None
    note_comment: str = ""
    tags: list[str] = []
    full_note: str = ""
    full_note_evidence: list[EvidenceSpan] = []
    sentence: str = ""
    sentence_evidence: list[EvidenceSpan] = []


class AdjudicateResponse(BaseModel):
    complete: bool = False
    patient_id: Optional[str] = None
    patient_status: Optional[str] = None
    patient_complete: Optional[bool] = None
    annotation: Optional[AnnotationView] = None
    message: Optional[str] = None


class AdjudicateAction(BaseModel):
    action: str
    comment: str = ""
    event_date: Optional[str] = None


class PatientSearch(BaseModel):
    patient_id: str = ""


# --- stats / download ---------------------------------------------------

class StatsOut(BaseModel):
    number_of_patients: int
    number_of_annotated_patients: int
    number_of_reviewed: int
    lemma_dist: dict[str, int] = {}
    user_review_stats: dict[str, int] = {}


class DownloadFileOut(BaseModel):
    name: str
    size: int
    last_modified: str


class JobIdResponse(BaseModel):
    job_id: str


class JobStatusResponse(BaseModel):
    status: str


# --- internal processes -------------------------------------------------

class InternalStatusOut(BaseModel):
    rq_dashboard_url: str
    queue_length: int
    failed_jobs: int
    successful_jobs: int


class SimpleJobResponse(BaseModel):
    job_id: str
    message: str


class PinesStatusOut(BaseModel):
    available: bool
