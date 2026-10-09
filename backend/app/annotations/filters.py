"""Shared query filters for annotations."""

from sqlalchemy import and_, or_, select
from sqlmodel import col

from app.annotations.models import Annotation, AnnotationPrediction


def reviewable_filter(active_predictor_id: str | None = None):
    """Condition for annotations a human should still look at.

    Keyword-only annotations have no prediction at all and are always reviewable.
    A predictor can rule one out by returning a negative label.

    - ``active_predictor_id`` given: ONLY that predictor's verdict is consulted;
      the legacy inline ``Annotation.predicted_label`` is ignored.
    - ``active_predictor_id`` is None (no active predictor): legacy behavior is
      preserved (inline label or any prediction row rules out).

    ``manual_review_override`` always keeps an annotation reviewable.
    """
    if active_predictor_id is not None:
        ruled_out = (
            select(col(AnnotationPrediction.id))
            .where(
                col(AnnotationPrediction.annotation_id) == col(Annotation.id),
                col(AnnotationPrediction.predictor_config_id) == active_predictor_id,
                col(AnnotationPrediction.predicted_label) == 0,
            )
            .exists()
        )
        return or_(
            col(Annotation.manual_review_override).is_(True),
            ~ruled_out,
        )

    ruled_out_by_predictor = (
        select(col(AnnotationPrediction.id))
        .where(
            col(AnnotationPrediction.annotation_id) == col(Annotation.id),
            col(AnnotationPrediction.predicted_label) == 0,
        )
        .exists()
    )
    return or_(
        col(Annotation.manual_review_override).is_(True),
        and_(
            or_(col(Annotation.predicted_label).is_(None), col(Annotation.predicted_label) != 0),
            ~ruled_out_by_predictor,
        ),
    )
