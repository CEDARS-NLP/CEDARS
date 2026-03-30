"""Business logic for pipeline EventConfig management."""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.pipeline.models import EventConfig


async def create_event_config(
    session: AsyncSession,
    project_id: str,
    name: str,
    description: str,
    include_criteria: str,
    exclude_criteria: str,
    search_patterns: dict,
    llm_provider: str,
    llm_model: str,
    llm_api_base: str | None = None,
) -> EventConfig:
    ec = EventConfig(
        project_id=project_id,
        name=name,
        description=description,
        include_criteria=include_criteria,
        exclude_criteria=exclude_criteria,
        search_patterns=search_patterns,
        llm_provider=llm_provider,
        llm_model=llm_model,
        llm_api_base=llm_api_base,
    )
    session.add(ec)
    await session.commit()
    await session.refresh(ec)
    return ec


async def list_event_configs(
    session: AsyncSession, project_id: str
) -> list[EventConfig]:
    stmt = (
        select(EventConfig)
        .where(
            EventConfig.project_id == project_id,
            EventConfig.deleted_at.is_(None),
        )
        .order_by(EventConfig.created_at.desc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def get_event_config(
    session: AsyncSession, project_id: str, event_config_id: str
) -> EventConfig | None:
    stmt = select(EventConfig).where(
        EventConfig.id == event_config_id,
        EventConfig.project_id == project_id,
        EventConfig.deleted_at.is_(None),
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def update_event_config(
    session: AsyncSession,
    project_id: str,
    event_config_id: str,
    **fields,
) -> EventConfig | None:
    ec = await get_event_config(session, project_id, event_config_id)
    if not ec:
        return None
    if ec.is_committed:
        raise ValueError("Cannot update a committed EventConfig")

    for key, value in fields.items():
        if value is not None and hasattr(ec, key):
            setattr(ec, key, value)
    ec.updated_at = datetime.now(UTC)
    session.add(ec)
    await session.commit()
    await session.refresh(ec)
    return ec


async def delete_event_config(
    session: AsyncSession, project_id: str, event_config_id: str
) -> bool:
    ec = await get_event_config(session, project_id, event_config_id)
    if not ec:
        return False
    if ec.is_committed:
        raise ValueError("Cannot delete a committed EventConfig")
    ec.deleted_at = datetime.now(UTC)
    session.add(ec)
    await session.commit()
    return True


async def commit_event_config(
    session: AsyncSession,
    project_id: str,
    event_config_id: str,
    confidence_threshold: float | None = None,
) -> EventConfig | None:
    ec = await get_event_config(session, project_id, event_config_id)
    if not ec:
        return None
    if ec.is_committed:
        raise ValueError("EventConfig is already committed")
    ec.is_committed = True
    ec.confidence_threshold = confidence_threshold
    ec.updated_at = datetime.now(UTC)
    session.add(ec)
    await session.commit()
    await session.refresh(ec)
    return ec
