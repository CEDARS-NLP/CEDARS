'''
db_auth.py

User authentication and project-membership lookups against the global
application database and per-project databases.
'''

from loguru import logger

from sqlalchemy import delete, func, insert, select, update
from werkzeug.security import check_password_hash

from ..cedars_enums import log_function_call
from .db_session import session_scope
from .global_app_tables import UserProjectRelation, Users
from .project_table_creation import ProjectUsers, SYSTEM_REVIEWERS


logger.enable(__name__)


@log_function_call
def add_user(engine, user_id, password_hash=None, uses_orcid=False, is_admin=False):
    '''
    Adds a user to the global application database.
    Args:
        engine: The SQLAlchemy engine for the global application database.
        user_id (str): The unique identifier for the user.
                        May be an email or username depending on the authentication method used.
                        If using ORCID, this must be a valid email with the ORCID system.
        is_admin (bool): Whether this user is a global superuser.

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
                uses_orcid=uses_orcid,
                is_admin=is_admin,
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
def get_user_count(engine) -> int:
    '''
    Total number of registered users - used to decide if the next registration
    should become the first (global-admin) user.
    '''
    with session_scope(engine) as session:
        return session.execute(select(func.count()).select_from(Users)).scalar_one()


@log_function_call
def list_users(engine) -> list[str]:
    '''
    Every registered user_id in the global application database.
    '''
    with session_scope(engine) as session:
        return list(session.execute(select(Users.user_id)).scalars().all())


@log_function_call
def validate_local_user(engine, user_id, entered_password) -> tuple[bool, str]:
    """
    Validates a local user by checking if the provided plaintext password matches
    the stored werkzeug password hash.
    Args:
        engine: The SQLAlchemy engine for the global application database.
        user_id (str): The unique identifier for the user.
        entered_password (str): The plaintext password to validate.

    Returns:
        bool: True if the password is correct, False otherwise.
        str: A message indicating the result of the validation.

    """
    with session_scope(engine) as session:
        user_info = session.execute(
            select(Users).where(Users.user_id == user_id)
        ).scalar_one_or_none()

        if user_info is None:
            logger.warning(f"User {user_id} not found in the database.")
            return False, "User not found."

        if user_info.password_hash and check_password_hash(user_info.password_hash, entered_password):
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


@log_function_call
def get_project_membership(global_engine, project_id, user_id):
    '''
    Retrieves the user's membership row for a project from the global database.

    Returns:
        UserProjectRelation row, or None if the user is not assigned to the project.
    '''
    with session_scope(global_engine) as session:
        return session.execute(
            select(UserProjectRelation).where(
                UserProjectRelation.project_id == project_id,
                UserProjectRelation.user_id == user_id,
            )
        ).scalar_one_or_none()


@log_function_call
def list_user_project_memberships(global_engine, user_id) -> dict[str, bool]:
    '''
    Returns project_id -> has_admin_privileges for every project assigned to a user.
    '''
    with session_scope(global_engine) as session:
        rows = session.execute(
            select(UserProjectRelation.project_id,
                   UserProjectRelation.has_admin_privileges)
            .where(UserProjectRelation.user_id == user_id)
        ).all()

    return {project_id: bool(is_admin) for project_id, is_admin in rows}


@log_function_call
def list_project_members(global_engine, project_id) -> list[dict]:
    '''
    Returns membership rows for a project from the global database.
    '''
    with session_scope(global_engine) as session:
        rows = session.execute(
            select(UserProjectRelation.user_id,
                   UserProjectRelation.has_admin_privileges,
                   UserProjectRelation.added_by)
            .where(UserProjectRelation.project_id == project_id)
            .order_by(UserProjectRelation.user_id)
        ).all()

    return [
        {
            "username": user_id,
            "role": "admin" if has_admin_privileges else "annotator",
            "added_by": added_by,
        }
        for user_id, has_admin_privileges, added_by in rows
    ]


@log_function_call
def count_project_admins(global_engine, project_id) -> int:
    '''
    Counts users with admin privileges for a project.
    '''
    with session_scope(global_engine) as session:
        return session.execute(
            select(func.count()).select_from(UserProjectRelation).where(
                UserProjectRelation.project_id == project_id,
                UserProjectRelation.has_admin_privileges.is_(True),
            )
        ).scalar_one()


@log_function_call
def set_project_member_admin(global_engine, project_engine,
                             project_id, user_id, is_admin) -> None:
    '''
    Updates a member's project role in both membership tables.
    '''
    with session_scope(global_engine) as session:
        session.execute(
            update(UserProjectRelation)
            .where(UserProjectRelation.project_id == project_id,
                   UserProjectRelation.user_id == user_id)
            .values(has_admin_privileges=is_admin)
        )

    with session_scope(project_engine) as session:
        session.execute(
            update(ProjectUsers)
            .where(ProjectUsers.user_id == user_id)
            .values(is_admin=is_admin)
        )


@log_function_call
def remove_project_member(global_engine, project_engine, project_id, user_id) -> None:
    '''
    Removes a member from both the global and project-local membership tables.
    '''
    if user_id in SYSTEM_REVIEWERS:
        raise ValueError(f"Cannot remove system reviewer {user_id!r}.")

    with session_scope(global_engine) as session:
        session.execute(
            delete(UserProjectRelation).where(
                UserProjectRelation.project_id == project_id,
                UserProjectRelation.user_id == user_id,
            )
        )

    with session_scope(project_engine) as session:
        session.execute(delete(ProjectUsers).where(ProjectUsers.user_id == user_id))
