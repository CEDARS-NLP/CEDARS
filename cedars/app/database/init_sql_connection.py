from loguru import logger
from uuid import uuid4

from sqlalchemy import create_engine

from project_table_creation import ProjectBase
from global_app_tables import GlobalBase

logger.enable(__name__)

def create_project_tables(database_url, project_name) -> None:
    """ """

    engine = create_engine(database_url, echo=True, future=True)
    try:
        ProjectBase.metadata.create_all(engine)
        logger.info("Tables created successfully at %s for project %s",
                    database_url, project_name)
    finally:
        engine.dispose()

def populate_project_info():
    pass

def initialize_project(base_database_url, project_name, project_id=None) -> None:
    """Initialize the project by creating tables in the database."""
    if project_id is None:
        project_id = str(uuid4())

    project_database_url = f"{base_database_url}/cedars_{project_id}.db"
    logger.info("Initializing project: %s, at: %s", project_name,
                project_database_url)

    create_project_tables(project_database_url, project_name)

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
