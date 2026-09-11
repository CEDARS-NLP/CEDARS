'''
redis_acl.py

Per-project Redis ACL provisioning. Each project gets its own Redis ACL user,
restricted by key pattern to that project's queues/jobs, so a project's RQ
dashboard/connection cannot see another project's data even though every
project shares the same physical Redis server. Credentials are generated once
per project and stored in the global registry (mirrors how ``project_db_name``
works for Postgres in :mod:`app.database`).

Note: registries such as ``rq:workers``/``rq:worker:*`` are not queue-scoped in
RQ, so ACL users are granted read access to them - this leaks worker names
(not job data) across projects and is an accepted, documented limitation.
'''
import secrets

from loguru import logger
from redis import Redis
from sqlalchemy import delete, insert, select

from ..cedars_enums import log_function_call
from .db_session import session_scope
from .global_app_tables import ProjectRedisCredentials

SECRET_BYTES = 32


def redis_acl_username(project_id: str) -> str:
    """Map a project_id to its Redis ACL username."""
    return f"cedars_proj_{project_id}"


def _key_patterns(project_id: str) -> list:
    """Key patterns this project's ACL user is allowed to touch.

    Uses a broad ``*{project_id}*`` match (rather than only the queue-name
    prefixes) because not every job_id is queue-name-prefixed - e.g. NLP jobs
    use ``spacy:{project_id}:{patient_id}`` (see ``app.services.nlp_service``).
    ``project_id`` is a per-project UUID, so this stays project-scoped.
    """
    return [
        f"~rq:*{project_id}*",
        f"~review_state:{project_id}:*",
        "~rq:queues",       # set of known queue names (names only, no job data)
        "~rq:workers",       # global worker registry (names only, no job data)
        "~rq:worker:*",
    ]


@log_function_call
def create_project_redis_user(admin_redis: Redis, global_engine, project_id: str):
    '''
    Provisions (or rotates) the Redis ACL user for ``project_id`` and stores its
    credentials in the global registry. Returns ``(username, secret)``.

    Best-effort: if the connected Redis backend does not support ``ACL``
    (e.g. ``fakeredis`` in the test suite), the error is logged and the
    generated credentials are still stored, so the rest of the application can
    be exercised without a real Redis server.
    '''
    username = redis_acl_username(project_id)
    secret = secrets.token_urlsafe(SECRET_BYTES)

    try:
        admin_redis.execute_command(
            "ACL", "SETUSER", username, "on", f">{secret}", "resetkeys",
            *_key_patterns(project_id), "+@all",
        )
    except Exception:  # noqa: BLE001 - ACL support varies by backend (see docstring)
        logger.warning(f"Redis ACL SETUSER not applied for project {project_id} "
                       "(backend may not support ACL). Credentials are still stored.")

    with session_scope(global_engine) as session:
        session.execute(delete(ProjectRedisCredentials)
                        .where(ProjectRedisCredentials.project_id == project_id))
        session.execute(insert(ProjectRedisCredentials).values(
            project_id=project_id, redis_username=username, redis_secret=secret,
        ))

    logger.info(f"Provisioned Redis ACL user {username} for project {project_id}.")
    return username, secret


@log_function_call
def revoke_project_redis_user(admin_redis: Redis, global_engine, project_id: str) -> None:
    '''
    Revokes the Redis ACL user for ``project_id`` and removes its stored
    credentials. Safe to call even if the user was never provisioned.
    '''
    username = redis_acl_username(project_id)
    try:
        admin_redis.execute_command("ACL", "DELUSER", username)
    except Exception:  # noqa: BLE001 - see create_project_redis_user
        logger.warning(f"Redis ACL DELUSER not applied for project {project_id}.")

    with session_scope(global_engine) as session:
        session.execute(delete(ProjectRedisCredentials)
                        .where(ProjectRedisCredentials.project_id == project_id))

    logger.info(f"Revoked Redis ACL user {username} for project {project_id}.")


@log_function_call
def get_project_redis_credentials(global_engine, project_id: str):
    '''
    Returns ``(username, secret)`` for ``project_id``.

    Raises:
        RuntimeError: if the project has no stored Redis credentials (it was
            never provisioned, e.g. an old project predating this feature).
    '''
    with session_scope(global_engine) as session:
        row = session.execute(
            select(ProjectRedisCredentials)
            .where(ProjectRedisCredentials.project_id == project_id)
        ).scalar_one_or_none()

    if row is None:
        raise RuntimeError(
            f"No Redis credentials provisioned for project {project_id}.")
    return row.redis_username, row.redis_secret
