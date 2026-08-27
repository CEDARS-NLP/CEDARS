from loguru import logger

from sqlalchemy.orm import Session

from sqlalchemy import select
from sqlalchemy import insert

from global_app_tables import Users
from cedars.app.cedars_enums import log_function_call


logger.enable(__name__)


@log_function_call
def add_user(db_engine, user_id, password_hash=None, uses_orcid=False):
    '''
    Adds a user to the global application database.
    Args:
        db_engine: The SQLAlchemy engine for the global application database.
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

    stmt = insert(Users).values(
        user_id=user_id,
        password_hash=password_hash,
        uses_orcid=uses_orcid
    )

    with db_engine.connect() as conn:
        conn.execute(stmt)
        conn.commit()

    logger.info(f"Successfully added user {user_id} to database.")

@log_function_call
def validate_local_user(db_engine, user_id,
                        entered_password_hash) -> (bool, str): # type: ignore
    """
    Validates a local user by checking if the provided password hash matches the stored hash.
    Args:
        db_engine: The SQLAlchemy engine for the global application database.
        user_id (str): The unique identifier for the user.
        entered_password_hash (str): The password hash to validate against the stored hash.

    Returns:
        bool: True if the password hash matches, False otherwise.
        str: A message indicating the result of the validation.

    """

    stmt = select(Users).where(Users.c.user_id == user_id)

    with Session(db_engine) as session:
        results = session.execute(stmt)
        user_info = results.first() # as user_id is unique, there should be only one result

        if user_info is None:
            logger.warning(f"User {user_id} not found in the database.")
            return False, "User not found."

        if user_info.password_hash == entered_password_hash:
            logger.info(f"User {user_id} validated successfully.")
            return True, "Authentication successful."
        else:
            logger.warning(f"Invalid password for user {user_id}.")
            return False, "Invalid password."
