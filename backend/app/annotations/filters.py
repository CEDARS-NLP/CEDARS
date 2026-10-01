"""Shared query filters for annotations."""

from sqlalchemy import and_, or_, select

from app.annotations.models import Annotation, AnnotationPrediction


def reviewable_filter():
    """Condition for annotations a human should still look at.

    Keyword-only annotations have no prediction at all and are always reviewable.
    An optional predictor can rule one out by returning a negative label.
    """
    ruled_out_by_predictor = (
        select(AnnotationPrediction.id)
        .where(
            AnnotationPrediction.annotation_id == Annotation.id,
            AnnotationPrediction.predicted_label == 0,
        )
        .exists()
    )
    return and_(
        or_(Annotation.predicted_label.is_(None), Annotation.predicted_label != 0),
        ~ruled_out_by_predictor,
    )
