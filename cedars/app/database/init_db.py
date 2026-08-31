'''
init_db.py

Functions to bootstrap the global application database and per-project databases.
'''

from uuid import uuid4

from loguru import logger

from sqlalchemy import insert, text

from ..cedars_enums import log_function_call
from . import (dispose_project_engine, get_admin_engine,
               get_global_engine, get_project_engine,
               project_db_name)
from .db_session import session_scope
from .global_app_tables import GlobalBase, Projects, UserProjectRelation
from .project_table_creation import ProjectBase, ProjectSettings, ProjectUsers

logger.enable(__name__)


@log_function_call
def create_project_database(project_id: str) -> None:
    '''
    Issues `CREATE DATABASE` for a new project on the shared Postgres server.
    Uses the admin engine (AUTOCOMMIT) since CREATE DATABASE cannot run inside
    a transaction. No-ops if the database already exists.
    '''
    db_name = project_db_name(project_id)
    admin_engine = get_admin_engine()
    with admin_engine.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :name"), {"name": db_name}
        ).scalar_one_or_none()
        if exists:
            logger.info(f"Database {db_name} already exists.")
            return
        # Database identifiers can't be bound parameters; db_name is derived
        # from a server-generated UUID (project_id), never user input.
        conn.execute(text(f'CREATE DATABASE "{db_name}"'))

    logger.info(f"Created database {db_name} for project {project_id}.")


@log_function_call
def create_project_tables(engine, project_name) -> None:
    '''
    Creates every project-scoped table (Patients, Notes, Annotations, ... ProjectSettings)
    in the database pointed to by `engine`.
    '''
    ProjectBase.metadata.create_all(engine)
    logger.info(f"Tables created successfully for project {project_name}.")


@log_function_call
def populate_project_info(engine, project_id, project_name,
                          user_id, cedars_version: float, description: str = "") -> None:
    '''
    Inserts the project's row into the global Projects table.
    '''
    with session_scope(engine) as session:
        session.execute(
            insert(Projects).values(
                project_id=project_id,
                project_name=project_name,
                description=description,
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
def initialize_project(project_name, current_user_id, cedars_version: float,
                       project_id=None, description: str = "") -> str:
    '''
    Initializes a new project: creates its Postgres database/tables, registers
    it in the global database, creates its default settings row, and attaches
    the creating user as its first (admin) member.

    Returns:
        str: the project_id (generated if not provided).
    '''
    if project_id is None:
        project_id = str(uuid4())

    logger.info(f"Initializing project: {project_name} ({project_id})")
    create_project_database(project_id)
    project_engine = get_project_engine(project_id)
    global_engine = get_global_engine()

    create_project_tables(project_engine, project_name)
    populate_project_info(global_engine, project_id, project_name,
                          current_user_id, cedars_version, description)
    create_project_settings(project_engine)
    attach_user_to_project(global_engine, project_engine, project_id,
                           current_user_id, is_admin=True)

    return project_id


@log_function_call
def initialize_application() -> None:
    '''
    Initializes the global application database (Users, Projects, UserProjectRelation).
    '''
    engine = get_global_engine()
    GlobalBase.metadata.create_all(engine)
    logger.info("Tables created successfully for the global application database.")


@log_function_call
def run_alembic_upgrade(ini_filename: str, revision: str = "head", **x_args) -> None:
    '''
    Programmatically runs `alembic upgrade <revision>` using the given ini file
    (`alembic_global.ini` or `alembic_project.ini`, resolved relative to the
    `cedars/` package directory), optionally passing `-x key=value` arguments
    (e.g. `project_id=<id>` for `alembic_project.ini`).

    This is the versioned-migration counterpart to `create_project_tables`/
    `initialize_application`'s `metadata.create_all()` calls - use this once a
    project/environment already has its baseline schema and needs a later
    migration applied.
    '''
    import argparse
    from pathlib import Path

    from alembic import command
    from alembic.config import Config

    cedars_root = Path(__file__).resolve().parents[2]
    alembic_cfg = Config(str(cedars_root / ini_filename))
    # -x key=value arguments are read by env.py via context.get_x_argument(),
    # which pulls from cmd_opts.x when invoked programmatically (not via the CLI).
    alembic_cfg.cmd_opts = argparse.Namespace(x=[f"{k}={v}" for k, v in x_args.items()])

    command.upgrade(alembic_cfg, revision)
    logger.info(f"Applied alembic migrations ({ini_filename}, revision={revision}, {x_args}).")


@log_function_call
def migrate_all_projects(revision: str = "head") -> None:
    '''
    Fans out `alembic_project.ini` migrations to every project in the global
    registry - run this after authoring a new project-schema revision.
    '''
    from .db_projects import list_projects

    for project in list_projects(get_global_engine()):
        run_alembic_upgrade("alembic_project.ini", revision, project_id=project.project_id)



@log_function_call
def drop_project_database(project_id: str) -> None:
    '''
    Fully drops a project's Postgres database (used when a project is deleted).
    '''
    dispose_project_engine(project_id)
    db_name = project_db_name(project_id)
    admin_engine = get_admin_engine()
    with admin_engine.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{db_name}" WITH (FORCE)'))

    logger.info(f"Dropped database {db_name} for project {project_id}.")


