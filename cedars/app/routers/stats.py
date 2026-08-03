"""Project statistics route (ported from the Flask ``stats`` blueprint).

Available to any authenticated project member (the original ``stats`` route was
``@login_required``, not admin-only).
"""
from fastapi import APIRouter, Depends

from .. import db
from ..dependencies import ProjectContext, require_project
from ..schemas import StatsOut

router = APIRouter(prefix="/projects/{project_id}", tags=["stats"])


@router.get("/stats", response_model=StatsOut)
def get_stats(_ctx: ProjectContext = Depends(require_project)):
    """Return cohort statistics for the current project."""
    stats = db.get_curr_stats()
    return StatsOut(
        number_of_patients=stats["number_of_patients"],
        number_of_annotated_patients=stats["number_of_annotated_patients"],
        number_of_reviewed=stats["number_of_reviewed"],
        # The original stats page renders these bar charts with integer values.
        lemma_dist={k: int(v) for k, v in stats["lemma_dist"].items()},
        user_review_stats={k: int(v) for k, v in stats["user_review_stats"].items()},
    )
