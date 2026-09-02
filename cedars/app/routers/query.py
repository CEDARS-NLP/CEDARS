"""Query + NLP routes.

Mirrors the original Flask ``ops.upload_query`` / ``ops.do_nlp_processing`` /
``ops.get_job_status``. Saving a query (as in Flask) also dispatches NLP
processing. A separate ``/nlp/run`` allows re-running NLP without changing the
query, and ``/nlp/status`` reports progress.
"""
import re

from fastapi import APIRouter, Depends

from ..database import get_current_project_engine
from ..database.db_deletes import empty_annotations
from ..database.db_query import get_search_query_details, save_query as save_search_query
from ..database.db_updates import reset_patient_reviewed
from ..dependencies import ProjectContext, require_project, require_project_admin
from ..queues import task_queue
from ..schemas import (NlpRunResponse, NlpStatusOut, QueryOut, QueryUpdate,
                       SaveQueryResponse)
from ..services import nlp_service

router = APIRouter(prefix="/projects/{project_id}", tags=["query", "nlp"])

# The original query-syntax pattern (kept verbatim for parity).
SEARCH_QUERY_PATTERN = (
    r'^\s*(\(\s*[a-zsA-Z0-9*?]+(\s+AND\s+[a-zA-Z0-9*?]+)*\s*\)|[a-zA-Z0-9*?]+)'
    r'(\s*OR\s+(\(\s*[a-zA-Z0-9*?]+(\s+AND\s+[a-zA-Z0-9*?]+)*\s*\)|[a-zA-Z0-9*?]+))*\s*$'
)


@router.get("/query", response_model=QueryOut)
def get_query(_ctx: ProjectContext = Depends(require_project_admin)):
    """Return the current search query and its options."""
    details = get_search_query_details(get_current_project_engine())
    return QueryOut(
        query=details.get("query", "") if details else "",
        nlp_apply=bool(details.get("apply_pines", False)) if details else False,
        hide_duplicates=bool(details.get("hide_duplicates", True)) if details else True,
        skip_after_event=bool(details.get("skip_after_event", False)) if details else False,
        exclude_negated=bool(details.get("exclude_negated", False)) if details else False,
    )


@router.put("/query", response_model=SaveQueryResponse)
def save_query(payload: QueryUpdate,
               ctx: ProjectContext = Depends(require_project_admin)):
    """Save the query and dispatch NLP (matches the Flask upload_query action)."""
    search_query = payload.query or ""
    # Parity with the original: only a malformed *pattern* is rejected (never
    # happens for a constant pattern), so any user query is accepted.
    try:
        re.match(SEARCH_QUERY_PATTERN, search_query)
    except re.error:
        pass

    use_negation = False  # negation view disabled in the original UI
    new_query_added = save_search_query(
        get_current_project_engine(), search_query, use_negation,
        bool(payload.hide_duplicates), bool(payload.skip_after_event),
        tag_query_exact=False, apply_pines=bool(payload.nlp_apply),
        apply_llm=False)
    if new_query_added:
        project_engine = get_current_project_engine()
        empty_annotations(project_engine)
        task_queue.empty()
        reset_patient_reviewed(project_engine)

    dispatched = nlp_service.run_nlp(ctx.project_id, ctx.user.username)
    return SaveQueryResponse(
        new_query=new_query_added,
        dispatched=dispatched,
        message=f"Query saved. Dispatched NLP for {dispatched} patient(s).",
    )


@router.post("/nlp/run", response_model=NlpRunResponse)
def run_nlp(ctx: ProjectContext = Depends(require_project_admin)):
    """Re-run NLP for all patients without changing the query."""
    dispatched = nlp_service.run_nlp(ctx.project_id, ctx.user.username)
    return NlpRunResponse(dispatched=dispatched,
                          message=f"Dispatched NLP for {dispatched} patient(s).")


@router.get("/nlp/status", response_model=NlpStatusOut)
def nlp_status(_ctx: ProjectContext = Depends(require_project)):
    """Report NLP processing progress for this project."""
    return NlpStatusOut(**nlp_service.nlp_status())
