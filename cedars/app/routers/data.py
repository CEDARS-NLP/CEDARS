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
from ..database.db_search import (get_all_annotations_for_patient, get_all_notes,
                                  get_event_annotation_id, get_event_date)
from ..database.db_updates import reopen_patient
from ..database.project_table_creation import Annotations
from ..dependencies import ProjectContext, require_project, require_project_admin
from ..schemas import (DataFileOut, DataSourceOut, IngestResponse, MessageResponse,
                       NoteOut, PatientAnnotationOut, PatientListItemOut,
                       PatientListOut, PatientReviewStatsOut)
from ..services import adjudication_service, data_service

_REVIEW_STATUS_LABELS = {
    Annotations.STATUS_UNREVIEWED: "unreviewed",
    Annotations.STATUS_REVIEWED: "reviewed",
    Annotations.STATUS_SKIPPED: "skipped",
}

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


@router.get("/patients/{patient_id}/notes", response_model=list[NoteOut])
def get_patient_notes_endpoint(
    patient_id: str,
    _ctx: ProjectContext = Depends(require_project),
):
    """List a patient's clinical notes, oldest first."""
    notes = get_all_notes(get_current_project_engine(), patient_id)
    return [
        NoteOut(id=note.text_id, patient_id=note.patient_id, text_id=note.text_id,
               note_date=note.text_date, text=note.text)
        for note in sorted(notes, key=lambda note: note.text_date)
    ]


@router.get("/patients/{patient_id}/annotations", response_model=list[PatientAnnotationOut])
def get_patient_annotations_endpoint(
    patient_id: str,
    _ctx: ProjectContext = Depends(require_project),
):
    """List a patient's non-negated annotations, in note/sentence order."""
    project_engine = get_current_project_engine()
    annotations = get_all_annotations_for_patient(project_engine, patient_id)
    event_annotation_id = get_event_annotation_id(project_engine, patient_id)
    event_date = get_event_date(project_engine, patient_id)
    return [
        PatientAnnotationOut(
            id=annotation.annotation_id,
            note_id=annotation.text_id,
            sentence_text=annotation.sentence,
            matched_tokens=annotation.token,
            is_negated=annotation.isNegated,
            review_status=_REVIEW_STATUS_LABELS[annotation.status],
            event_date=event_date if annotation.annotation_id == event_annotation_id else None,
            note_date=annotation.text_date,
            sentence_number=annotation.sentence_number,
        )
        for annotation in annotations
    ]


@router.get("/patients/{patient_id}/stats", response_model=PatientReviewStatsOut)
def get_patient_stats_endpoint(
    patient_id: str,
    _ctx: ProjectContext = Depends(require_project),
):
    """Review-status counts and recorded event for a single patient."""
    project_engine = get_current_project_engine()
    annotations = get_all_annotations_for_patient(project_engine, patient_id)
    counts = {label: 0 for label in _REVIEW_STATUS_LABELS.values()}
    for annotation in annotations:
        counts[_REVIEW_STATUS_LABELS[annotation.status]] += 1
    return PatientReviewStatsOut(
        total=len(annotations),
        unreviewed=counts["unreviewed"],
        reviewed=counts["reviewed"],
        skipped=counts["skipped"],
        current_event_date=get_event_date(project_engine, patient_id),
        event_annotation_id=get_event_annotation_id(project_engine, patient_id),
    )


@router.post("/patients/{patient_id}/reopen", response_model=MessageResponse)
def reopen_patient_endpoint(
    patient_id: str,
    ctx: ProjectContext = Depends(require_project_admin),
):
    """Unlock a reviewed patient and load them into the caller's adjudicate session,
    the same way searching for their ID in the Adjudicate page would."""
    reopen_patient(get_current_project_engine(), patient_id)
    adjudication_service.search_patient(ctx.user.username, ctx.project_id, patient_id)
    return MessageResponse(message=f"Patient {patient_id} re-opened for review.")


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
