"""Business logic for predictor configuration."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.common.crud import get_scoped, list_scoped, soft_delete
from app.predictors.models import PredictorConfig, PredictorType


async def create_predictor_config(
    session: AsyncSession,
    project_id: str,
    name: str,
    predictor_type: PredictorType,
    config: dict,
    created_by: str,
) -> PredictorConfig:
    pc = PredictorConfig(
        project_id=project_id,
        name=name,
        predictor_type=predictor_type,
        config=config,
        created_by=created_by,
    )
    session.add(pc)
    await session.commit()
    await session.refresh(pc)
    return pc


async def list_predictor_configs(
    session: AsyncSession, project_id: str
) -> list[PredictorConfig]:
    return await list_scoped(session, PredictorConfig, project_id)


async def get_predictor_config(
    session: AsyncSession, project_id: str, predictor_id: str
) -> PredictorConfig | None:
    return await get_scoped(session, PredictorConfig, project_id, predictor_id)


async def update_predictor_config(
    session: AsyncSession,
    project_id: str,
    predictor_id: str,
    name: str | None = None,
    config: dict | None = None,
) -> PredictorConfig | None:
    pc = await get_predictor_config(session, project_id, predictor_id)
    if not pc:
        return None
    if name is not None:
        pc.name = name
    if config is not None:
        pc.config = config
    session.add(pc)
    await session.commit()
    await session.refresh(pc)
    return pc


async def delete_predictor_config(
    session: AsyncSession, project_id: str, predictor_id: str
) -> bool:
    pc = await get_predictor_config(session, project_id, predictor_id)
    if not pc:
        return False
    await soft_delete(session, pc)
    return True


async def activate_predictor(
    session: AsyncSession, project_id: str, predictor_id: str
) -> PredictorConfig | None:
    """Set a predictor as the active one for the project (deactivates others)."""
    pc = await get_predictor_config(session, project_id, predictor_id)
    if not pc:
        return None

    # Deactivate all others
    stmt = select(PredictorConfig).where(
        PredictorConfig.project_id == project_id,
        PredictorConfig.deleted_at.is_(None),
        PredictorConfig.is_active.is_(True),
    )
    result = await session.execute(stmt)
    for other in result.scalars().all():
        other.is_active = False
        session.add(other)

    pc.is_active = True
    session.add(pc)
    await session.commit()
    await session.refresh(pc)
    return pc
