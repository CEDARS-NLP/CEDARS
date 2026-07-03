"""Generic project-scoped, soft-delete-aware CRUD query helpers.

Nearly every service module reimplemented the same three queries against a
model with ``id``, ``project_id``, ``deleted_at`` and ``created_at`` columns:
fetch one by id within a project, list all within a project, and soft-delete
one. These helpers centralize that query logic. They deliberately do NOT touch
column definitions (no mixin) — the ``deleted_at`` columns keep their existing
per-model ``sa_column`` declarations, so there is no schema/migration impact.
"""

from typing import TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.utils import now_utc

T = TypeVar("T")


async def get_scoped(
    session: AsyncSession,
    model: type[T],
    project_id: str,
    obj_id: str,
) -> T | None:
    """Fetch a single non-deleted row by id, scoped to a project."""
    stmt = select(model).where(
        model.id == obj_id,
        model.project_id == project_id,
        model.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def list_scoped(
    session: AsyncSession,
    model: type[T],
    project_id: str,
    *,
    order_by_desc: bool = True,
) -> list[T]:
    """List non-deleted rows for a project, newest first by ``created_at``."""
    order = model.created_at.desc() if order_by_desc else model.created_at.asc()
    stmt = (
        select(model)
        .where(model.project_id == project_id, model.deleted_at.is_(None))
        .order_by(order)
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def soft_delete(session: AsyncSession, instance: object, *, commit: bool = True) -> None:
    """Mark an instance deleted by stamping ``deleted_at`` and persisting it."""
    instance.deleted_at = now_utc()
    session.add(instance)
    if commit:
        await session.commit()
