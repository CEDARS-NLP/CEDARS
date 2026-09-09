"""Annotation-export (download) routes (admin only).

Ports the Flask ``ops`` download routes: list generated files, create a compact
or full export (background job), poll job status, download, and delete.
"""
from fastapi import APIRouter, Depends, HTTPException, Response, status

from ..dependencies import require_project_admin
from ..schemas import (DownloadFileOut, JobIdResponse, JobStatusResponse,
                       MessageResponse)
from ..services import download_service

router = APIRouter(prefix="/projects/{project_id}/download", tags=["download"])


def _validate_filename(filename: str) -> None:
    """Reject filenames that could escape the project's S3 prefix."""
    if not filename or "/" in filename or "\\" in filename or filename in (".", ".."):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST,
                            detail="Invalid filename.")


@router.get("/files", response_model=list[DownloadFileOut])
def list_files(_ctx=Depends(require_project_admin)):
    """List generated annotation export files."""
    return download_service.list_files()


@router.post("/compact", response_model=JobIdResponse)
def create_compact(ctx=Depends(require_project_admin)):
    """Create a compact annotations export (background)."""
    return JobIdResponse(job_id=download_service.create_download(ctx.project_id, False))


@router.post("/full", response_model=JobIdResponse)
def create_full(ctx=Depends(require_project_admin)):
    """Create a full annotations export incl. key sentences (background)."""
    return JobIdResponse(job_id=download_service.create_download(ctx.project_id, True))


@router.get("/check/{job_id}", response_model=JobStatusResponse)
def check(job_id: str, _ctx=Depends(require_project_admin)):
    """Poll the status of an export-generation job."""
    return JobStatusResponse(**download_service.check_job(job_id))


@router.get("/file/{filename}")
def download(filename: str, _ctx=Depends(require_project_admin)):
    """Download a generated export as a CSV attachment."""
    _validate_filename(filename)
    data = download_service.get_file_bytes(filename)
    return Response(
        content=data,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment;filename=cedars_{filename}"},
    )


@router.delete("/file/{filename}", response_model=MessageResponse)
def delete(filename: str, _ctx=Depends(require_project_admin)):
    """Delete a generated export from storage."""
    _validate_filename(filename)
    download_service.delete_file(filename)
    return MessageResponse(message=f"Deleted {filename}.")
