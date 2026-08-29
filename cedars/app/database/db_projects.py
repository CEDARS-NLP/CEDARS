'''
db_projects.py

Project metadata and per-project settings (PINES integration config) management,
spanning both the global application database (Projects) and a project's own
database (ProjectSettings). Equivalent to mongo's INFO collection.
'''

from loguru import logger

from sqlalchemy import select, update, delete

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_session import session_scope
from cedars.app.database.global_app_tables import Projects, UserProjectRelation
from cedars.app.database.project_table_creation import ProjectBase, ProjectSettings

logger.enable(__name__)


@log_function_call
def update_project_name(global_engine, project_id, new_name) -> None:
    '''
    Updates a project's display name in the global Projects table.
    '''
    with session_scope(global_engine) as session:
        session.execute(
            update(Projects)
            .where(Projects.project_id == project_id)
            .values(project_name=new_name)
        )

    logger.info(f"Updated project {project_id} name to {new_name}.")


@log_function_call
def update_project_description(global_engine, project_id, new_description) -> None:
    '''
    Updates a project's description in the global Projects table.
    '''
    with session_scope(global_engine) as session:
        session.execute(
            update(Projects)
            .where(Projects.project_id == project_id)
            .values(description=new_description)
        )


@log_function_call
def list_projects(global_engine) -> list:
    '''
    Every project in the global registry, ordered by creation time.
    '''
    with session_scope(global_engine) as session:
        return session.execute(
            select(Projects).order_by(Projects.creation_time)
        ).scalars().all()


@log_function_call
def get_info(global_engine, project_engine, project_id) -> dict:
    '''
    Returns a dict of project metadata, combining the global Projects row with
    the project's own ProjectSettings row. Equivalent to mongo's INFO document.

    Returns:
        dict, or {} if the project does not exist in the global database.
    '''
    with session_scope(global_engine) as session:
        project = session.execute(
            select(Projects).where(Projects.project_id == project_id)
        ).scalar_one_or_none()

    if project is None:
        return {}

    info = {
        "project_id": project.project_id,
        "project": project.project_name,
        "description": project.description,
        "investigator": project.investigator,
        "creation_time": project.creation_time,
        "CEDARS_version": project.cedars_version,
        "pines_url": None,
        "is_pines_server_enabled": False,
    }

    with session_scope(project_engine) as session:
        settings = session.execute(select(ProjectSettings)).scalar_one_or_none()

    if settings is not None:
        info["pines_url"] = settings.pines_url
        info["is_pines_server_enabled"] = settings.is_pines_server_enabled

    return info


@log_function_call
def get_proj_name(global_engine, project_id) -> str | None:
    '''
    Returns the display name of a project, or None if it does not exist.
    '''
    with session_scope(global_engine) as session:
        project = session.execute(
            select(Projects).where(Projects.project_id == project_id)
        ).scalar_one_or_none()

    return project.project_name if project is not None else None


@log_function_call
def get_curr_version(global_engine, project_id) -> float | None:
    '''
    Returns the CEDARS version a project was created with.
    '''
    with session_scope(global_engine) as session:
        project = session.execute(
            select(Projects).where(Projects.project_id == project_id)
        ).scalar_one_or_none()

    return project.cedars_version if project is not None else None


@log_function_call
def create_pines_info(project_engine, pines_url, is_url_from_api) -> str:
    '''
    Sets the initial PINES url and enabled status for a project.
    '''
    update_pines_api_url(project_engine, pines_url)
    update_pines_api_status(project_engine, is_url_from_api)

    return pines_url


@log_function_call
def update_pines_api_status(project_engine, new_status: bool) -> None:
    '''
    Updates whether the PINES server is considered enabled for this project.
    '''
    logger.info(f"Setting PINES API status to {new_status}")
    with session_scope(project_engine) as session:
        session.execute(update(ProjectSettings).values(is_pines_server_enabled=new_status))


@log_function_call
def update_pines_api_url(project_engine, new_url: str) -> None:
    '''
    Updates the PINES API url for this project.
    '''
    logger.info(f"Setting PINES API url to {new_url}")
    with session_scope(project_engine) as session:
        session.execute(update(ProjectSettings).values(pines_url=new_url))


@log_function_call
def get_pines_url(project_engine) -> str | None:
    '''
    Retrieves the configured PINES url for this project.
    '''
    with session_scope(project_engine) as session:
        settings = session.execute(select(ProjectSettings)).scalar_one_or_none()

    return settings.pines_url if settings is not None else None


@log_function_call
def is_pines_api_running(project_engine) -> bool:
    '''
    Returns True if a PINES API server is configured as enabled for this project.
    '''
    with session_scope(project_engine) as session:
        settings = session.execute(select(ProjectSettings)).scalar_one_or_none()

    return bool(settings.is_pines_server_enabled) if settings is not None else False


@log_function_call
def terminate_project(global_engine, project_engine, project_id) -> None:
    '''
    Resets a project to its initial (empty) state: drops every table in the
    project's own database and recreates them, and removes its membership rows
    from the global database's UserProjectRelation table.

    Note: unlike mongo's terminate_project, this does not delete or recreate the
    project's row in the global Projects table, nor does it re-attach any user -
    callers that need that behavior should call init_db.attach_user_to_project
    and init_db.create_project_settings afterwards.
    '''
    logger.info(f"Terminating project {project_id}.")

    ProjectBase.metadata.drop_all(project_engine)
    ProjectBase.metadata.create_all(project_engine)

    with session_scope(global_engine) as session:
        session.execute(
            delete(UserProjectRelation).where(UserProjectRelation.project_id == project_id)
        )

    logger.info(f"Project {project_id} has been reset to its initial state.")


@log_function_call
def delete_project_registry(global_engine, project_id) -> None:
    '''
    Removes a project's rows from the global database (UserProjectRelation,
    then Projects). Does not touch the project's own database - pair this with
    init_db.drop_project_database to fully remove a project.
    '''
    with session_scope(global_engine) as session:
        session.execute(
            delete(UserProjectRelation).where(UserProjectRelation.project_id == project_id)
        )
        session.execute(delete(Projects).where(Projects.project_id == project_id))

    logger.info(f"Removed project {project_id} from the global registry.")

