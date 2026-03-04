"""Pydantic schemas for connector API requests and responses."""

from datetime import datetime

from pydantic import BaseModel

from app.connectors.models import ConnectorType, IngestionStatus


class CreateDataSourceRequest(BaseModel):
    name: str
    connector_type: ConnectorType
    config: dict = {}


class UpdateDataSourceRequest(BaseModel):
    name: str | None = None
    config: dict | None = None


class DataSourceResponse(BaseModel):
    id: str
    project_id: str
    name: str
    connector_type: ConnectorType
    config: dict
    status: IngestionStatus
    row_count: int | None
    error_message: str | None
    last_sync: datetime | None
    created_at: datetime


class PreviewResponse(BaseModel):
    columns: list[str]
    rows: list[dict]
    total_available: int | None


class IngestionResponse(BaseModel):
    data_source_id: str
    status: IngestionStatus
    message: str


class PatientResponse(BaseModel):
    id: str
    patient_id_ext: str
    status: str
    note_count: int = 0
    created_at: datetime


class NoteResponse(BaseModel):
    id: str
    patient_id: str
    text_id: str
    note_date: datetime
    text: str
    source_ref: str | None
    created_at: datetime
