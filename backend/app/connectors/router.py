"""API routes for data sources, ingestion, patients, and notes."""

from fastapi import APIRouter, Depends, Form, HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.connectors.registry import get_connector
from app.connectors.schemas import (
    CreateDataSourceRequest,
    DataSourceResponse,
    IngestionResponse,
    NoteResponse,
    PatientListResponse,
    PatientResponse,
    PreviewResponse,
)
from app.connectors.service import (
    cancel_ingestion_job,
    create_data_source,
    delete_data_source,
    dispatch_ingestion_job,
    get_data_source,
    get_ingestion_job_status,
    get_patient_notes,
    list_data_sources,
    list_patients,
    upload_and_create_data_source,
)
from app.jobs.schemas import BackgroundJobResponse
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
    content = await file.read()
    try:
        return await upload_and_create_data_source(
            session,
            project_id,
            filename=file.filename or "",
            file_data=content,
            content_type=file.content_type or "application/octet-stream",
            column_mapping=column_mapping,
        )
    except EnvironmentError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


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


@router.post("/sources/{data_source_id}/ingest", response_model=BackgroundJobResponse)
async def ingest_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    current_user: User = Depends(require_project_role("admin")),
):
    """Trigger ingestion of a data source as a background job."""
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    return await dispatch_ingestion_job(session, project_id, data_source_id, current_user.id)


@router.get("/sources/{data_source_id}/ingest/status", response_model=BackgroundJobResponse | None)
async def ingestion_job_status_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    """Get the latest ingestion job status for a data source."""
    return await get_ingestion_job_status(session, project_id, data_source_id)


@router.post("/sources/{data_source_id}/ingest/cancel")
async def cancel_ingestion_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Cancel a running ingestion job."""
    result = await cancel_ingestion_job(session, project_id, data_source_id)
    if not result:
        raise HTTPException(status_code=404, detail="No active ingestion job found")
    return result


@router.post("/sources/{data_source_id}/resync", response_model=IngestionResponse)
async def resync_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Re-sync a data source: update existing notes, add new ones."""
    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    from app.connectors.service import resync_data_source
    result = await resync_data_source(session, project_id, data_source_id)
    return IngestionResponse(
        data_source_id=result.id,
        status=result.status,
        message=f"Re-synced {result.row_count or 0} rows" if result.row_count else result.error_message or "No data",
    )


@router.delete("/sources/{data_source_id}/data")
async def purge_data_source_endpoint(
    project_id: str,
    data_source_id: str,
    confirm: bool = False,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin")),
):
    """Purge all data (patients, notes, sentences, annotations) from a data source."""
    if not confirm:
        raise HTTPException(
            status_code=400,
            detail="Pass ?confirm=true to confirm data deletion",
        )

    ds = await get_data_source(session, project_id, data_source_id)
    if not ds:
        raise HTTPException(status_code=404, detail="Data source not found")

    from app.connectors.service import purge_data_source
    deleted = await purge_data_source(session, project_id, data_source_id)
    return {"deleted_notes": deleted, "data_source_id": data_source_id}

# ── Patients + Notes ──────────────────────────────────────────────


@router.get("/patients", response_model=PatientListResponse)
async def list_patients_endpoint(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    search: str | None = None,
    status: str | None = None,
    session: AsyncSession = Depends(get_session),
    _current_user: User = Depends(require_project_role("admin", "annotator", "viewer")),
):
    result = await list_patients(
        session, project_id, limit=limit, offset=offset, search=search, status=status,
    )
    return PatientListResponse(
        items=[
            PatientResponse(
                id=r["patient"].id,
                patient_id_ext=r["patient"].patient_id_ext,
                status=r["patient"].status.value,
                note_count=r["note_count"],
                created_at=r["patient"].created_at,
            )
            for r in result["items"]
        ],
        total=result["total"],
        limit=result["limit"],
        offset=result["offset"],
    )


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
