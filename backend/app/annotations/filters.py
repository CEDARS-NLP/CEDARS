"""Shared query filters for annotations."""

from sqlalchemy import and_, or_, select
from sqlmodel import col

from app.annotations.models import Annotation
from app.production.models import NotePrediction, ProductionState


def reviewable_filter(active_predictor_id: str | None = None):
    """Keep active-run positive and keyword-only rows in the human workflow."""
    active_run_id = (
        select(col(ProductionState.active_run_id))
        .where(col(ProductionState.project_id) == col(Annotation.project_id))
        .scalar_subquery()
    )
    ruled_out_by_note = (
        select(col(NotePrediction.id))
        .where(
            col(NotePrediction.project_id) == col(Annotation.project_id),
            col(NotePrediction.text_id) == col(Annotation.text_id),
            col(NotePrediction.run_id) == active_run_id,
            col(NotePrediction.label) == 0,
        )
        .exists()
    )
    return and_(
        or_(
            col(Annotation.review_reason).is_(None),
            ~col(Annotation.review_reason).in_(("llm_negative", "duplicate", "negated")),
        ),
        ~ruled_out_by_note,
    )
