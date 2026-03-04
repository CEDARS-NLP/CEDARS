"""Request/response schemas for audit log."""

from pydantic import BaseModel


class AuditEntryResponse(BaseModel):
    id: str
    action: str
    user_name: str
    user_id: str | None
    patient_id: str | None = None
    detail: dict
    created_at: str


class AuditLogResponse(BaseModel):
    items: list[AuditEntryResponse]
    total: int
    limit: int
    offset: int


class PatientActivitySummary(BaseModel):
    total_actions: int
    unique_users: int
    users: list[str]


class PatientActivityResponse(BaseModel):
    patient_id: str
    summary: PatientActivitySummary
    entries: list[AuditEntryResponse]
