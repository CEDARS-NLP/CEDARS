import os

from loguru import logger
from uuid import uuid4

from sqlalchemy import create_engine
from sqlalchemy import insert

from project_table_creation import ProjectBase
from global_app_tables import GlobalBase, Projects
from global_app_tables import UserProjectRelation
from project_table_creation import ProjectUsers
from cedars.app.cedars_enums import log_function_call

logger.enable(__name__)

@log_function_call
def create_project_tables(engine, database_url, project_name) -> None:
    """ """
    ProjectBase.metadata.create_all(engine)
    logger.info("Tables created successfully at %s for project %s",
                database_url, project_name)

@log_function_call
def populate_project_info(engine, project_id,
                          project_name, user_id) -> None:
    stmt = insert(Projects).values(
        project_id=project_id,
        project_name=project_name,
        investigator=user_id,
        cedars_version=float(os.getenv("CEDARS Version"))
    )

    with engine.connect() as conn:
        conn.execute(stmt)
        conn.commit()

@log_function_call
def attach_user_to_project(global_engine,
                           project_engine,
                           project_id,
                           user_id, is_admin) -> None:

    # First assign the user to the project in the UserProjectRelation table
    relation_stmt = insert(UserProjectRelation).values(
        project_id=project_id,
        user_id=user_id,
        has_admin_privileges=is_admin
    )

    with global_engine.connect() as conn:
        conn.execute(relation_stmt)
        conn.commit()

    # Next, add the initial user to the project's database
    project_stmt = insert(ProjectUsers).values(
        user_id=user_id,
        is_admin=is_admin
    )

    with project_engine.connect() as conn:
        conn.execute(project_stmt)
        conn.commit()

    logger.info(f"Successfully added user {user_id} to project {project_id}.")

@log_function_call
def initialize_project(global_engine,
                       base_database_url, project_name,
                       current_user_id,
                       project_id=None) -> None:
    """Initialize the project by creating tables in the database."""
    if project_id is None:
        project_id = str(uuid4())

    project_database_url = f"{base_database_url}/cedars_{project_id}.db"
    logger.info("Initializing project: %s, at: %s", project_name,
                project_database_url)
    project_engine = create_engine(project_database_url, echo=True, future=True)

    try:
        create_project_tables(project_engine, project_database_url, project_name)
        populate_project_info(global_engine, project_id,
                              project_name, current_user_id)
        attach_user_to_project(global_engine,
                                project_engine,
                                project_id,
                                current_user_id,
                                is_admin=True)
    finally:
        project_engine.dispose()

@log_function_call
def initialize_application(database_url) -> None:
    """Initialize the application by creating tables in the database."""
    if project_id is None:
        project_id = str(uuid4())

    logger.info("Initializing application at: %s", database_url)

    engine = create_engine(database_url, echo=True, future=True)
    try:
        GlobalBase.metadata.create_all(engine)
        logger.info("Tables created successfully for application at %s", database_url)
    finally:
        engine.dispose()
