"""Data-ingestion routes (admin only).

Mirrors the original Flask ``ops.upload_data``: list previously uploaded source
files, and upload-or-select a file then load it into the project's database.
Ingestion runs synchronously, matching the original behavior.
"""
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status

from ..dependencies import require_project_admin
from ..schemas import DataFileOut, IngestResponse
from ..services import data_service

router = APIRouter(prefix="/projects/{project_id}/data", tags=["data"])


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
        summary = data_service.emr_to_mongodb(s3_key, insert_chunk, upsert_chunk)
    except Exception as exc:  # noqa: BLE001 - surface ingestion errors to the client
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR,
                            f"Failed to upload data: {str(exc)}") from exc

    return IngestResponse(
        filename=s3_key,
        message=f"Data from {s3_key} uploaded to the database.",
        total_rows=summary["total_rows"],
        total_chunks=summary["total_chunks"],
        total_patients=summary["total_patients"],
    )
