"""Business logic for pipeline EventConfig management and metrics."""

from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from app.common.crud import get_scoped, list_scoped, soft_delete
from app.common.utils import now_utc
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
    return await list_scoped(session, EventConfig, project_id)


async def get_event_config(
    session: AsyncSession, project_id: str, event_config_id: str
) -> EventConfig | None:
    return await get_scoped(session, EventConfig, project_id, event_config_id)


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
    ec.updated_at = now_utc()
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
    await soft_delete(session, ec)
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
    ec.updated_at = now_utc()
    session.add(ec)
    await session.commit()
    await session.refresh(ec)
    return ec


async def compute_run_metrics(session: AsyncSession, run_id: str) -> dict:
    """Compute metrics from note predictions and current human production decisions."""
    from app.annotations.models import Annotation
    from app.connectors.models import Patient
    from app.pipeline.models import PipelineRun
    from app.production.models import NotePrediction

    pipeline_run = await session.get(PipelineRun, run_id)
    production_run_id = (pipeline_run.result_summary or {}).get("production_run_id") \
        if pipeline_run else None
    annotation_run_filter = (
        col(Annotation.production_run_id) == production_run_id
        if production_run_id
        else col(Annotation.pipeline_run_id) == run_id
    )
    stmt = (
        select(Annotation, NotePrediction, Patient)
        .join(
            NotePrediction,
            and_(
                col(NotePrediction.project_id) == col(Annotation.project_id),
                col(NotePrediction.run_id) == col(Annotation.production_run_id),
                col(NotePrediction.text_id) == col(Annotation.text_id),
            ),
        )
        .join(
            Patient,
            and_(
                col(Patient.project_id) == col(Annotation.project_id),
                col(Patient.patient_id_ext) == col(Annotation.patient_id),
            ),
        )
        .where(
            annotation_run_filter,
            col(Annotation.status) == "R",
            or_(
                col(Annotation.review_reason) == "human_negative",
                col(Patient.event_annotation_id) == col(Annotation.annotation_id),
            ),
            col(NotePrediction.status) == "succeeded",
            col(NotePrediction.label).is_not(None),
        )
    )
    reviewed = list((await session.execute(stmt)).all())

    if not reviewed:
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

    true_positive_scores: list[float] = []

    for ann, prediction, patient in reviewed:
        predicted_positive = prediction.label == 1
        reviewer_positive = patient.event_annotation_id == ann.annotation_id

        if predicted_positive and reviewer_positive:
            tp += 1
        elif predicted_positive and not reviewer_positive:
            fp += 1
        elif not predicted_positive and reviewer_positive:
            fn += 1
        else:
            tn += 1

        if prediction.score is not None:
            scores.append(prediction.score)
            if predicted_positive and reviewer_positive:
                true_positive_scores.append(prediction.score)

    precision = tp / (tp + fp) if (tp + fp) > 0 else None
    recall = tp / (tp + fn) if (tp + fn) > 0 else None
    f1 = (
        2 * precision * recall / (precision + recall)
        if precision is not None and recall is not None and precision + recall > 0
        else None
    )

    # Suggest threshold: median of true positive scores, or None
    suggested = (
        sorted(true_positive_scores)[len(true_positive_scores) // 2]
        if true_positive_scores
        else None
    )

    return {
        "total_reviewed": len(reviewed),
        "true_positives": tp,
        "false_positives": fp,
        "false_negatives": fn,
        "true_negatives": tn,
        "precision": round(precision, 4) if precision is not None else None,
        "recall": round(recall, 4) if recall is not None else None,
        "f1_score": round(f1, 4) if f1 is not None else None,
        "suggested_threshold": suggested,
    }
