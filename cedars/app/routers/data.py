"""Data-ingestion routes (admin only).

Mirrors the original Flask ``ops.upload_data``: list previously uploaded source
files, and upload-or-select a file then load it into the project's database.
Ingestion runs synchronously, matching the original behavior.
"""
from typing import Optional
from loguru import logger

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status

from ..database import get_current_project_engine
from ..database.db_overview import list_data_sources
from ..database.db_patients import WORKFLOW_STATUSES, list_patients
from ..dependencies import ProjectContext, require_project, require_project_admin
from ..schemas import (DataFileOut, DataSourceOut, IngestResponse, PatientListItemOut,
                       PatientListOut)
from ..services import data_service

router = APIRouter(prefix="/projects/{project_id}/data", tags=["data"])


@router.get("/sources", response_model=list[DataSourceOut])
def list_sources(_ctx: ProjectContext = Depends(require_project)):
    """List active ingestion sources from this project's own database."""
    return [
        DataSourceOut(
            id=source.source_id,
            name=source.name,
            connector_type=source.connector_type,
            object_key=source.object_key,
            status=source.status,
            row_count=source.row_count,
            error_message=source.error_message,
            created_at=source.created_at,
            last_synced_at=source.last_synced_at,
        )
        for source in list_data_sources(get_current_project_engine())
    ]


@router.get("/patients", response_model=PatientListOut)
def list_project_patients(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    search: Optional[str] = Query(default=None, max_length=100),
    patient_status: Optional[str] = Query(default=None, alias="status"),
    _ctx: ProjectContext = Depends(require_project),
):
    """Browse patients in the bound project with search, workflow state, and counts."""
    if patient_status and patient_status not in WORKFLOW_STATUSES:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Unknown patient status.")
    items, total = list_patients(
        get_current_project_engine(), limit, offset, search, patient_status
    )
    return PatientListOut(
        items=[PatientListItemOut(**item) for item in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/files", response_model=list[DataFileOut])
def list_files(_ctx=Depends(require_project_admin)):
    """List source files previously uploaded for this project."""
    return data_service.list_uploaded_files()


@router.post("/upload", response_model=IngestResponse)
def upload_and_ingest(
    _ctx=Depends(require_project_admin),
    file: Optional[UploadFile] = File(None),
    miniofile: Optional[str] = Form(None),
):
    """Upload (or reuse) a source file, then load it into the database."""
    if miniofile and miniofile not in ("None", ""):
        s3_key = miniofile
    elif file is not None and file.filename:
        if not data_service.allowed_data_file(file.filename):
            raise HTTPException(
                status.HTTP_400_BAD_REQUEST,
                "Invalid file type. Please upload a .csv, .xlsx, .json, .parquet, "
                ".pickle, .pkl, .xml or .csv.gz file.")
        s3_key = data_service.upload_source_file(file.file, file.filename,
                                                 file.content_type)
    else:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "No file provided.")

    insert_chunk, upsert_chunk = data_service.ingest_chunk_sizes()
    try:
        summary = data_service.emr_to_sql(s3_key, insert_chunk, upsert_chunk)
    except Exception as exc:  # noqa: BLE001 - surface ingestion errors to the client
        logger.exception("Data ingestion failed. Rolling back transaction.")
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"Failed to upload data: {str(exc)}") from exc

    return IngestResponse(
        filename=s3_key,
        message=f"Data from {s3_key} uploaded to the database.",
        total_rows=summary["total_rows"],
        total_chunks=summary["total_chunks"],
        total_patients=summary["total_patients"],
    )
