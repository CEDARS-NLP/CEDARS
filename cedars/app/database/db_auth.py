'''
db_auth.py

User authentication and project-membership lookups against the global
application database and per-project databases.
'''

from loguru import logger

from sqlalchemy import select, insert

from cedars.app.cedars_enums import log_function_call
from cedars.app.database.db_session import session_scope
from cedars.app.database.global_app_tables import Users
from cedars.app.database.project_table_creation import ProjectUsers


logger.enable(__name__)


@log_function_call
def add_user(engine, user_id, password_hash=None, uses_orcid=False):
    '''
    Adds a user to the global application database.
    Args:
        engine: The SQLAlchemy engine for the global application database.
        user_id (str): The unique identifier for the user.
                        May be an email or username depending on the authentication method used.
                        If using ORCID, this must be a valid email with the ORCID system.

    '''

    if not uses_orcid and password_hash is None:
        raise ValueError("Password hash must be provided for local authentication.",
                         "If using ORCID, ORCID system must be setup.")
    elif uses_orcid and password_hash is not None:
        raise ValueError("Can only authenticate with either ORCID or local authentication, not both. If using ORCID, password hash must be None.")

    if password_hash is not None:
        logger.info(f"Adding user {user_id} to database with local authentication.")
    else:
        logger.info(f"Adding user {user_id} to database with ORCID authentication.")

    with session_scope(engine) as session:
        session.execute(
            insert(Users).values(
                user_id=user_id,
                password_hash=password_hash,
                uses_orcid=uses_orcid
            )
        )

    logger.info(f"Successfully added user {user_id} to database.")


@log_function_call
def get_user(engine, user_id):
    '''
    Retrieves a user's row from the global application database.

    Returns:
        Users row, or None if no such user exists.
    '''
    with session_scope(engine) as session:
        user = session.execute(
            select(Users).where(Users.user_id == user_id)
        ).scalar_one_or_none()

    return user


@log_function_call
def validate_local_user(engine, user_id,
                        entered_password_hash) -> tuple[bool, str]:
    """
    Validates a local user by checking if the provided password hash matches the stored hash.
    Args:
        engine: The SQLAlchemy engine for the global application database.
        user_id (str): The unique identifier for the user.
        entered_password_hash (str): The password hash to validate against the stored hash.

    Returns:
        bool: True if the password hash matches, False otherwise.
        str: A message indicating the result of the validation.

    """
    with session_scope(engine) as session:
        user_info = session.execute(
            select(Users).where(Users.user_id == user_id)
        ).scalar_one_or_none()

        if user_info is None:
            logger.warning(f"User {user_id} not found in the database.")
            return False, "User not found."

        if user_info.password_hash == entered_password_hash:
            logger.info(f"User {user_id} validated successfully.")
            return True, "Authentication successful."
        else:
            logger.warning(f"Invalid password for user {user_id}.")
            return False, "Invalid password."


@log_function_call
def is_admin_user(project_engine, user_id) -> bool:
    '''
    Checks whether a user has admin privileges within a specific project.
    Args:
        project_engine: The SQLAlchemy engine for the project database.
        user_id (str): The unique identifier for the user.

    Returns:
        bool: True if the user is an admin for this project, False otherwise
              (including if the user is not a member of the project).
    '''
    with session_scope(project_engine) as session:
        project_user = session.execute(
            select(ProjectUsers).where(ProjectUsers.user_id == user_id)
        ).scalar_one_or_none()

    return bool(project_user is not None and project_user.is_admin)


@log_function_call
def get_project_users(project_engine) -> list[str]:
    '''
    Returns the list of every user_id registered as a member of this project.
    Args:
        project_engine: The SQLAlchemy engine for the project database.

    Returns:
        list[str]: All user_ids in the project's ProjectUsers table.
    '''
    with session_scope(project_engine) as session:
        user_ids = session.execute(select(ProjectUsers.user_id)).scalars().all()

    return list(user_ids)
