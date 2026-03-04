"""Audit log service: write entries and query history."""

import logging
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.models import AuditAction, AuditEntry

logger = logging.getLogger(__name__)


async def log_action(
    session: AsyncSession,
    project_id: str,
    action: AuditAction,
    user_id: str | None = None,
    patient_id: str | None = None,
    detail: dict | None = None,
) -> None:
    """Append an audit entry. Fire-and-forget — logs but never raises."""
    try:
        entry = AuditEntry(
            project_id=project_id,
            action=action,
            user_id=user_id,
            patient_id=patient_id,
            detail=detail or {},
        )
        session.add(entry)
        await session.commit()
    except Exception:
        logger.exception("Failed to write audit entry: %s %s", action, detail)


async def get_patient_activity(
    session: AsyncSession,
    project_id: str,
    patient_id: str,
    limit: int = 100,
) -> dict:
    """Get activity timeline for a specific patient."""
    from app.auth.models import User

    stmt = (
        select(AuditEntry, User.name)
        .outerjoin(User, AuditEntry.user_id == User.id)
        .where(
            AuditEntry.project_id == project_id,
            AuditEntry.patient_id == patient_id,
        )
        .order_by(AuditEntry.created_at.desc())
        .limit(limit)
    )
    result = await session.execute(stmt)
    rows = result.all()

    unique_users: set[str] = set()
    entries = []
    for entry, user_name in rows:
        display_name = user_name or "System"
        unique_users.add(display_name)
        entries.append({
            "id": entry.id,
            "action": entry.action.value,
            "user_name": display_name,
            "user_id": entry.user_id,
            "detail": entry.detail,
            "created_at": entry.created_at.isoformat(),
        })

    return {
        "patient_id": patient_id,
        "summary": {
            "total_actions": len(entries),
            "unique_users": len(unique_users),
            "users": sorted(unique_users),
        },
        "entries": entries,
    }


async def query_audit_log(
    session: AsyncSession,
    project_id: str,
    patient_id: str | None = None,
    user_id: str | None = None,
    action: str | None = None,
    since: datetime | None = None,
    until: datetime | None = None,
    limit: int = 50,
    offset: int = 0,
) -> dict:
    """Query audit log with filters. Admin use."""
    from app.auth.models import User

    conditions = [AuditEntry.project_id == project_id]
    if patient_id:
        conditions.append(AuditEntry.patient_id == patient_id)
    if user_id:
        conditions.append(AuditEntry.user_id == user_id)
    if action:
        conditions.append(AuditEntry.action == action)
    if since:
        conditions.append(AuditEntry.created_at >= since)
    if until:
        conditions.append(AuditEntry.created_at <= until)

    count_stmt = select(func.count()).select_from(AuditEntry).where(*conditions)
    total = (await session.execute(count_stmt)).scalar() or 0

    stmt = (
        select(AuditEntry, User.name)
        .outerjoin(User, AuditEntry.user_id == User.id)
        .where(*conditions)
        .order_by(AuditEntry.created_at.desc())
        .offset(offset)
        .limit(limit)
    )
    result = await session.execute(stmt)

    entries = []
    for entry, user_name in result.all():
        entries.append({
            "id": entry.id,
            "action": entry.action.value,
            "user_name": user_name or "System",
            "user_id": entry.user_id,
            "patient_id": entry.patient_id,
            "detail": entry.detail,
            "created_at": entry.created_at.isoformat(),
        })

    return {"items": entries, "total": total, "limit": limit, "offset": offset}
