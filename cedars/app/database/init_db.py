'''
init_db.py

Functions to bootstrap the global application database and per-project databases.
'''

from uuid import uuid4

from loguru import logger

from sqlalchemy import create_engine, insert

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_session import session_scope
from cedars.app.database.global_app_tables import GlobalBase, Projects, UserProjectRelation
from cedars.app.database.project_table_creation import ProjectBase, ProjectSettings, ProjectUsers

logger.enable(__name__)


@log_function_call
def create_project_tables(engine, database_url, project_name) -> None:
    '''
    Creates every project-scoped table (Patients, Notes, Annotations, ... ProjectSettings)
    in the database pointed to by `engine`.
    '''
    ProjectBase.metadata.create_all(engine)
    logger.info(f"Tables created successfully at {database_url} for project {project_name}.")


@log_function_call
def populate_project_info(engine, project_id, project_name,
                          user_id, cedars_version: float) -> None:
    '''
    Inserts the project's row into the global Projects table.
    '''
    with session_scope(engine) as session:
        session.execute(
            insert(Projects).values(
                project_id=project_id,
                project_name=project_name,
                investigator=user_id,
                cedars_version=cedars_version
            )
        )

    logger.info(f"Populated project info for project {project_id}.")


@log_function_call
def create_project_settings(project_engine) -> None:
    '''
    Creates the single ProjectSettings row for a newly initialized project database.
    '''
    with session_scope(project_engine) as session:
        session.execute(insert(ProjectSettings).values())

    logger.info("Created default ProjectSettings row.")


@log_function_call
def attach_user_to_project(global_engine, project_engine,
                           project_id, user_id, is_admin) -> None:
    '''
    Registers a user as a member of a project in both the global database
    (UserProjectRelation) and the project's own database (ProjectUsers).
    '''
    with session_scope(global_engine) as session:
        session.execute(
            insert(UserProjectRelation).values(
                project_id=project_id,
                user_id=user_id,
                added_by=user_id,
                has_admin_privileges=is_admin
            )
        )

    with session_scope(project_engine) as session:
        session.execute(
            insert(ProjectUsers).values(
                user_id=user_id,
                is_admin=is_admin
            )
        )

    logger.info(f"Successfully added user {user_id} to project {project_id}.")


@log_function_call
def initialize_project(global_engine, base_database_url, project_name,
                       current_user_id, cedars_version: float,
                       project_id=None) -> None:
    '''
    Initializes a new project: creates its database/tables, registers it in the
    global database, creates its default settings row, and attaches the creating
    user as its first (admin) member.
    '''
    if project_id is None:
        project_id = str(uuid4())

    project_database_url = f"{base_database_url}/cedars_{project_id}.db"
    logger.info(f"Initializing project: {project_name}, at: {project_database_url}")
    project_engine = create_engine(project_database_url, echo=True, future=True)

    try:
        create_project_tables(project_engine, project_database_url, project_name)
        populate_project_info(global_engine, project_id, project_name,
                              current_user_id, cedars_version)
        create_project_settings(project_engine)
        attach_user_to_project(global_engine, project_engine, project_id,
                               current_user_id, is_admin=True)
    finally:
        project_engine.dispose()

    return project_id


@log_function_call
def initialize_application(database_url) -> None:
    '''
    Initializes the global application database (Users, Projects, UserProjectRelation).
    '''
    logger.info(f"Initializing application at: {database_url}")

    engine = create_engine(database_url, echo=True, future=True)
    try:
        GlobalBase.metadata.create_all(engine)
        logger.info(f"Tables created successfully for application at {database_url}.")
    finally:
        engine.dispose()
