'''
db_deletes.py

Bulk-delete operations against a project's database.
'''

from loguru import logger

from sqlalchemy import delete

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_session import session_scope
from cedars.app.database.project_table_creation import Annotations, ProjectBase, Task

logger.enable(__name__)


@log_function_call
def empty_annotations(project_engine) -> None:
    '''
    Deletes every annotation and task record for the project. Callers are
    responsible for clearing any associated external task queue (e.g. RQ)
    separately - this only touches the database.
    '''
    logger.info("Deleting all data in the Annotations and Task tables.")
    with session_scope(project_engine) as session:
        session.execute(delete(Annotations))
        session.execute(delete(Task))


@log_function_call
def drop_project_database(project_engine) -> None:
    '''
    Drops every project-scoped table. Equivalent to mongo's drop_database(name)
    for a project's own database.
    '''
    logger.info("Dropping all project tables.")
    ProjectBase.metadata.drop_all(project_engine)

