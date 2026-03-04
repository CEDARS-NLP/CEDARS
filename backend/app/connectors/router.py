"""API routes for data sources, ingestion, patients, and notes."""

import io
import uuid

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.common.s3 import upload_file
from app.connectors.models import ConnectorType
from app.connectors.registry import get_connector
from app.connectors.schemas import (
    CreateDataSourceRequest,
    DataSourceResponse,
    IngestionResponse,
    NoteResponse,
    PatientResponse,
    PreviewResponse,
)
from app.connectors.service import (
    create_data_source,
    delete_data_source,
    get_data_source,
    get_patient_notes,
    list_data_sources,
    list_patients,
    run_ingestion,
)
from app.dependencies import require_project_role

router = APIRouter(prefix="/api/v1/projects/{project_id}/data", tags=["data"])


# ── Data Sources ──────────────────────────────────────────────────


@router.post("/sources", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def create_data_source_endpoint(
    project_id: str,
    body: CreateDataSourceRequest,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    ds = await create_data_source(
        session, project_id, body.name, body.connector_type, body.config
    )
    return ds


@router.get("/sources", response_model=list[DataSourceResponse])
async def list_data_sources_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    return await list_data_sources(session, project_id)


@router.get("/sources/{data_source_id}", response_model=DataSourceResponse)
async def get_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")
    return ds


@router.delete("/sources/{data_source_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    deleted = await delete_data_source(session, project_id, data_source_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Data source not found")


# ── File Upload ───────────────────────────────────────────────────


@router.post("/upload", response_model=DataSourceResponse, status_code=status.HTTP_201_CREATED)
async def upload_file_endpoint(
    project_id: str,
    file: UploadFile,
    column_mapping: str | None = Form(None),
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Upload a CSV or JSON file to S3 and create a data source.

    Accepts an optional `column_mapping` form field (JSON string) that maps
    CEDARS field names to the file's column names, e.g.:
    ``{"patient_id": "MRN", "text_id": "note_id", "text": "note_text"}``
    """
    import json as _json

    from app.config import settings

    if not settings.s3_bucket or not settings.s3_endpoint:
        raise HTTPException(
            status_code=503,
            detail="Object storage is not configured. Set CEDARS_S3_ENDPOINT and CEDARS_S3_BUCKET.",
        )

    if not file.filename:
        raise HTTPException(status_code=400, detail="Filename is required")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    if ext not in ("csv", "json"):
        raise HTTPException(status_code=400, detail="Only CSV and JSON files are supported")

    # Parse column mapping from form data
    mapping = {"patient_id": "patient_id", "text_id": "text_id", "text": "text", "note_date": "note_date"}
    if column_mapping:
        try:
            user_mapping = _json.loads(column_mapping)
            if isinstance(user_mapping, dict):
                mapping.update(user_mapping)
        except _json.JSONDecodeError:
            raise HTTPException(status_code=400, detail="column_mapping must be valid JSON")

    # Validate required fields are present in mapping
    for required in ("patient_id", "text_id", "text", "note_date"):
        if not mapping.get(required):
            raise HTTPException(
                status_code=400,
                detail=f"Column mapping must include '{required}'",
            )

    # Upload to S3
    s3_key = f"projects/{project_id}/uploads/{uuid.uuid4()}/{file.filename}"
    content = await file.read()
    upload_file(s3_key, io.BytesIO(content), content_type=file.content_type or "application/octet-stream")

    config = {
        "s3_key": s3_key,
        "file_type": ext,
        "column_mapping": mapping,
    }

    ds = await create_data_source(
        session, project_id, file.filename, ConnectorType.FILE_UPLOAD, config
    )
    return ds


# ── Preview ───────────────────────────────────────────────────────


@router.get("/sources/{data_source_id}/preview", response_model=PreviewResponse)
async def preview_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    limit: int = 10,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    connector = get_connector(ds.connector_type)
    result = await connector.preview(ds.config, limit=limit)
    return PreviewResponse(
        columns=result.columns,
        rows=result.rows,
        total_available=result.total_available,
    )


# ── Ingestion ─────────────────────────────────────────────────────


@router.post("/sources/{data_source_id}/ingest", response_model=IngestionResponse)
async def ingest_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Trigger ingestion of a data source into the project."""
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    result = await run_ingestion(session, project_id, data_source_id)
    return IngestionResponse(
        data_source_id=result.id,
        status=result.status,
        message=f"Ingested {result.row_count or 0} rows" if result.row_count else result.error_message or "No data",
    )


# ── Patients + Notes ──────────────────────────────────────────────


@router.get("/patients", response_model=list[PatientResponse])
async def list_patients_endpoint(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    results = await list_patients(session, project_id, limit=limit, offset=offset)
    return [
        PatientResponse(
            id=r["patient"].id,
            patient_id_ext=r["patient"].patient_id_ext,
            status=r["patient"].status.value,
            note_count=r["note_count"],
            created_at=r["patient"].created_at,
        )
        for r in results
    ]


@router.get("/patients/{patient_id}/notes", response_model=list[NoteResponse])
async def list_patient_notes_endpoint(
    project_id: str,
    patient_id: str,
    limit: int = 100,
    offset: int = 0,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    notes = await get_patient_notes(session, project_id, patient_id, limit=limit, offset=offset)
    return [
        NoteResponse(
            id=n.id,
            patient_id=n.patient_id,
            text_id=n.text_id,
            note_date=n.note_date,
            text=n.text,
            source_ref=n.source_ref,
            created_at=n.created_at,
        )
        for n in notes
    ]
