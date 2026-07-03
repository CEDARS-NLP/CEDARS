"""API routes for data export."""

import logging

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.common.errors import raise_not_found
from app.dependencies import require_project_role
from app.export.databricks import ExportType, export_to_databricks
from app.export.schemas import (
    DatabricksExportRequest,
    DatabricksExportResponse,
    ExportAnnotationRow,
    ExportStatsResponse,
)
from app.export.service import export_annotations, format_csv, get_export_stats

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/api/v1/projects/{project_id}/export",
    tags=["export"],
)


@router.get("/stats", response_model=ExportStatsResponse)
async def export_stats_endpoint(
    project_id: str,
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "viewer")),
):
    """Get export statistics for the project."""
    return await get_export_stats(session, project_id)


@router.get("/annotations", response_model=list[ExportAnnotationRow])
async def export_annotations_json_endpoint(
    project_id: str,
    status: str | None = Query(None, description="Filter: reviewed, events, or all"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "viewer")),
):
    """Export annotations as JSON."""
    return await export_annotations(session, project_id, status_filter=status)


@router.get("/annotations/csv")
async def export_annotations_csv_endpoint(
    project_id: str,
    status: str | None = Query(None, description="Filter: reviewed, events, or all"),
    session: AsyncSession = Depends(get_session),
    _user: User = Depends(require_project_role("admin", "viewer")),
):
    """Export annotations as CSV file download."""
    annotations = await export_annotations(session, project_id, status_filter=status)
    csv_content = format_csv(annotations)
    return Response(
        content=csv_content,
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=annotations-{project_id[:8]}.csv"},
    )


@router.post("/databricks", response_model=DatabricksExportResponse)
async def export_to_databricks_endpoint(
    project_id: str,
    body: DatabricksExportRequest,
    session: AsyncSession = Depends(get_session),
    user: User = Depends(require_project_role("admin")),
):
    """Export project results to a Databricks table."""
    try:
        export_type = ExportType(body.export_type)
    except ValueError:
        valid = [e.value for e in ExportType]
        raise HTTPException(
            status_code=400,
            detail=f"Invalid export_type '{body.export_type}'. Must be one of: {valid}",
        )

    try:
        rows_exported = await export_to_databricks(
            session=session,
            project_id=project_id,
            data_source_id=body.data_source_id,
            target_table=body.target_table,
            export_type=export_type,
        )
    except ValueError as exc:
        raise_not_found(str(exc))
    except Exception:
        logger.exception("Databricks export failed")
        raise HTTPException(status_code=500, detail="Export to Databricks failed")

    return DatabricksExportResponse(
        rows_exported=rows_exported,
        target_table=body.target_table,
        export_type=body.export_type,
        status="success",
    )
