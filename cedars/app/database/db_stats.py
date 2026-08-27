'''
db_stats.py

Project-wide summary statistics, computed SQL-side (COUNT/GROUP BY) rather
than pulling rows into Python, so this stays cheap at large scale.
'''

from loguru import logger

from sqlalchemy import func, select

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_session import session_scope
from cedars.app.database.project_table_creation import Annotations, Patients

logger.enable(__name__)


@log_function_call
def get_curr_stats(project_engine) -> dict:
    '''
    Returns basic statistics for the project:
        - number_of_patients
        - number_of_annotated_patients (patients with a non-negated annotation)
        - number_of_reviewed (patients marked reviewed)
        - user_review_stats (reviewed-patient count per reviewer)
        - lemma_dist (top 10 annotation tokens by % share of non-negated annotations)
    '''
    stats = {}

    with session_scope(project_engine) as session:
        stats["number_of_patients"] = session.execute(
            select(func.count()).select_from(Patients)
        ).scalar_one()

        stats["number_of_annotated_patients"] = session.execute(
            select(func.count(func.distinct(Annotations.patient_id)))
            .where(Annotations.isNegated == False)  # noqa: E712
        ).scalar_one()

        stats["number_of_reviewed"] = session.execute(
            select(func.count()).select_from(Patients).where(Patients.reviewed == True)  # noqa: E712
        ).scalar_one()

        reviewer_counts = session.execute(
            select(Patients.last_reviewed_by, func.count())
            .where(Patients.reviewed == True)  # noqa: E712
            .group_by(Patients.last_reviewed_by)
        ).all()
        stats["user_review_stats"] = {reviewer: count for reviewer, count in reviewer_counts}

        total_tokens = session.execute(
            select(func.count()).select_from(Annotations).where(Annotations.isNegated == False)  # noqa: E712
        ).scalar_one()

        lemma_dist = {}
        if total_tokens > 0:
            token_counts = session.execute(
                select(Annotations.token, func.count())
                .where(Annotations.isNegated == False)  # noqa: E712
                .group_by(Annotations.token)
                .order_by(func.count().desc())
                .limit(10)
            ).all()
            lemma_dist = {token: 100 * count / total_tokens for token, count in token_counts}
        stats["lemma_dist"] = lemma_dist

    return stats
