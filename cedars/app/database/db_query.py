'''
db_query.py

Saving and retrieving the current (and historical) regex/tag search query for a project.
'''

from datetime import date
from typing import Optional, TypedDict

from loguru import logger

from sqlalchemy import select, update, insert

from ..cedars_enums import log_function_call
from .db_session import session_scope
from .project_table_creation import Query

logger.enable(__name__)


class QueryDetails(TypedDict, total=False):
    """Serialized settings for the currently active project query."""

    query_id: int
    query: str
    exclude_negated: bool
    hide_duplicates: bool
    skip_after_event: bool
    tag_query_exact: bool
    apply_pines: bool
    apply_llm: bool
    date_min: Optional[date]
    date_max: Optional[date]


@log_function_call
def save_query(project_engine, query, exclude_negated, hide_duplicates,  # pylint: disable=R0913
               skip_after_event, tag_query_exact,
               apply_pines, apply_llm,
               date_min=None, date_max=None) -> bool:
    '''
    Saves a new search query to a project's database, marking any previously
    current query as no longer current. If the new query is identical to the
    current one (same query text, skip_after_event and tag_query_exact), it is
    not saved again.

    Returns:
        bool: True if the query was saved, False if an identical query is already current.
    '''
    date_min = date_min or date.today()
    date_max = date_max or date.today()

    with session_scope(project_engine) as session:
        current = session.execute(
            select(Query).where(Query.current == True)  # noqa: E712
        ).scalar_one_or_none()

        if (current is not None and current.query == query
                and current.skip_after_event == skip_after_event
                and current.tag_query_exact == tag_query_exact):
            logger.info(f"Query already saved: {query}.")
            return False

        session.execute(update(Query).where(Query.current == True)  # noqa: E712
                        .values(current=False))

        session.execute(
            insert(Query).values(
                query=query,
                exclude_negated=exclude_negated,
                hide_duplicates=hide_duplicates,
                skip_after_event=skip_after_event,
                tag_query_exact=tag_query_exact,
                apply_pines=apply_pines,
                apply_llm=apply_llm,
                date_min=date_min,
                date_max=date_max,
                current=True
            )
        )

    logger.info(f"Saved query: {query}.")
    return True


@log_function_call
def get_search_query(project_engine, query_key="query"):
    '''
    Returns a single field from the currently active query.

    Returns:
        The value of `query_key` on the current Query row, or "" if there is no
        current query or the field doesn't exist.
    '''
    with session_scope(project_engine) as session:
        current = session.execute(
            select(Query).where(Query.current == True)  # noqa: E712
        ).scalar_one_or_none()

    if current is None:
        return ""

    return getattr(current, query_key, "")


@log_function_call
def get_search_query_details(project_engine) -> QueryDetails:
    '''
    Returns the full currently active query as a dict.

    Returns:
        QueryDetails, or {} if there is no current query.
    '''
    with session_scope(project_engine) as session:
        current = session.execute(
            select(Query).where(Query.current == True)  # noqa: E712
        ).scalar_one_or_none()

    if current is None:
        return {}

    return {
        "query_id": current.query_id,
        "query": current.query,
        "exclude_negated": current.exclude_negated,
        "hide_duplicates": current.hide_duplicates,
        "skip_after_event": current.skip_after_event,
        "tag_query_exact": current.tag_query_exact,
        "apply_pines": current.apply_pines,
        "apply_llm": current.apply_llm,
        "date_min": current.date_min,
        "date_max": current.date_max,
    }
