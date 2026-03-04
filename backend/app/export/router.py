"""API routes for data export."""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.models import User
from app.common.database import get_session
from app.dependencies import require_project_role
from app.export.schemas import ExportAnnotationRow, ExportStatsResponse
from app.export.service import export_annotations, format_csv, get_export_stats

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
