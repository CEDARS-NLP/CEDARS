'''
db_inserts.py

Functions to load notes and other user inputs into the database.
'''

from datetime import datetime
from loguru import logger


from sqlalchemy import update
from sqlalchemy import insert

from cedars.app.database.project_table_creation import ProjectUsers, Query
from cedars.app.cedars_enums import log_function_call
from cedars.app.database.global_app_tables import UserProjectRelation


logger.enable(__name__)

@log_function_call
def add_user_to_project(global_engine, project_engine, 
                        username,
                        added_by,
                        has_admin_privileges,
                        project_id):
    '''
    Adds a new user to the database.
    '''
    insert_stmt = insert(UserProjectRelation).values(
        username=username,
        project_id=project_id,
        added_by=added_by,
        has_admin_privileges=has_admin_privileges
    )
    
    with global_engine.connect() as conn:
        conn.execute(insert_stmt)
        conn.commit()
    
    logger.info(f"Successfully added user {username} to global database.")

    insert_stmt = insert(ProjectUsers).values(
        user_id=username,
        is_admin=has_admin_privileges
    )

    with project_engine.connect() as conn:
        conn.execute(insert_stmt)
        conn.commit()

    logger.info(f"Successfully added user {username} to the database for {project_id}.")

@log_function_call
def save_query(project_engine, query, exclude_negated, hide_duplicates,  # pylint: disable=R0913
               skip_after_event, tag_query,
               apply_pines, apply_llm,
               date_min=datetime.now(),
               date_max=datetime.now()):
    '''
    Saves a query to a project's database.
    By default, the query is marked as current. If a new query is added, the old one should be marked as not current.
    '''

    insert_stmt = insert(Query).values(
        query=query,
        exclude_negated=exclude_negated,
        hide_duplicates=hide_duplicates,
        skip_after_event=skip_after_event,
        tag_query_exact=tag_query['exact'],
        apply_pines=apply_pines,
        apply_llm=apply_llm,
        date_min=date_min,
        date_max=date_max,
        current=True
    )

    # Reset all prior queries to not current before inserting the new one
    update_stmt = update(Query).where(Query.current == True).values(current=False)

    with project_engine.connect() as conn:
        conn.execute(update_stmt)
        conn.execute(insert_stmt)
        conn.commit()

    logger.info(f"Successfully added query {query} to database.")

def _format_note(note):
    logger.debug(f"Formatting note info for note {note['text_id']}.")
    date_format = "%Y-%m-%d"
    text_date = note["text_date"]
    if isinstance(text_date, str):
        try:
            note["text_date"] = datetime.strptime(text_date, date_format)
        except ValueError:
            raise ValueError(f"Invalid date format for text_date: {text_date} for note {note['text_id']}. Expected format: {date_format}")
    else:
        raise ValueError(f"Unexpected type for text_date: {type(text_date)} for note {note['text_id']}. Expected str.")


def bulk_insert_notes(project_engine, notes):
    '''
    Bulk insert notes into the database.

    Args:
        - project_engine: SQLAlchemy engine for the project database.
        - notes: List of dictionaries, where each dictionary represents a note to be inserted.
                 Dict format: {'text_id': str, 'patient_id': str, 'text': str,
                 'date': datetime, 'source': str, 'other_metadata': dict}
    '''
    logger.info(f"Preparing to bulk insert {len(notes)} notes into the database.")
    logger.debug("Formatting notes...")
    notes = [_format_note(note) for note in notes]
    logger.debug("Finished formatting notes. Proceeding with bulk insert.")

    with project_engine.connect() as conn:
        conn.execute(insert(ProjectUsers), notes)
        conn.commit()
    
    logger.info(f"Successfully bulk inserted {len(notes)} notes into the database.")

