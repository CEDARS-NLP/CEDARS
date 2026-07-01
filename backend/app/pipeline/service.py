"""Business logic for pipeline EventConfig management and metrics."""

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
    llm_api_key: str | None = None,
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
        llm_api_key=llm_api_key,
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


async def compute_run_metrics(session: AsyncSession, run_id: str) -> dict:
    """Compute precision/recall/F1 from reviewed annotations in a pipeline run."""
    from app.annotations.models import Annotation, ReviewStatus

    stmt = select(Annotation).where(
        Annotation.pipeline_run_id == run_id,
        Annotation.review_status.in_([ReviewStatus.CONFIRMED, ReviewStatus.REJECTED]),
    )
    result = await session.execute(stmt)
    annotations = list(result.scalars().all())

    if not annotations:
        return {
            "total_reviewed": 0,
            "true_positives": 0,
            "false_positives": 0,
            "false_negatives": 0,
            "true_negatives": 0,
            "precision": None,
            "recall": None,
            "f1_score": None,
            "suggested_threshold": None,
        }

    tp = fp = fn = tn = 0
    scores: list[float] = []

    for ann in annotations:
        predicted_positive = (ann.predicted_label == 1)
        reviewer_positive = (ann.review_status == ReviewStatus.CONFIRMED)

        if predicted_positive and reviewer_positive:
            tp += 1
        elif predicted_positive and not reviewer_positive:
            fp += 1
        elif not predicted_positive and reviewer_positive:
            fn += 1
        else:
            tn += 1

        if ann.predicted_score is not None:
            scores.append(ann.predicted_score)

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (2 * precision * recall / (precision + recall)) if precision and recall else None

    # Suggest threshold: median of true positive scores, or None
    tp_scores = [
        s for s, a in zip(scores, annotations)
        if a.predicted_label == 1 and a.review_status == ReviewStatus.CONFIRMED
    ]
    suggested = sorted(tp_scores)[len(tp_scores) // 2] if tp_scores else None

    return {
        "total_reviewed": len(annotations),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1_score": round(f1, 4) if f1 is not None else None,
        "suggested_threshold": suggested,
    }
