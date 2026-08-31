"""Initialize database and object-storage connections (framework-agnostic).

Each project owns its own PostgreSQL *database* on a shared server (created at
project-creation time via ``CREATE DATABASE``); a separate, dedicated
"global" database holds cross-project state (Users/Projects/UserProjectRelation).
``mongo.db``-style per-collection access has been replaced by per-project
SQLAlchemy engines, resolved for the current request via a context variable.
Database operations take their engine explicitly, while application workflows
obtain the correct project engine from this module. S3 is exposed as lazy boto3
singletons, unchanged.

This lives in ``__init__.py`` (making ``database/`` a regular package) so that
both ``from app.database import get_global_engine`` and submodule
imports like ``from app.database.db_session import session_scope``
resolve correctly - a bare ``database.py`` alongside this package would be
permanently shadowed by the package and silently unimportable.
"""
import os
import contextvars
from threading import Lock
from urllib.parse import quote_plus

import boto3
from dotenv import load_dotenv
from loguru import logger
from botocore.exceptions import ClientError
from sqlalchemy import create_engine


load_dotenv()


def _build_pg_uri(db_name: str) -> str:
    """Build a PostgreSQL connection URI for `db_name` from environment vars."""
    protocol = os.getenv("DB_PROTOCOL", "postgresql")
    user = os.getenv("DB_USER")
    pwd = quote_plus(os.getenv("DB_PWD") or "")
    host = os.getenv("DB_HOST")
    port = os.getenv("DB_PORT", "5432")
    params = os.getenv("DB_PARAMS", "")
    uri = f"{protocol}://{user}:{pwd}@{host}:{port}/{db_name}"
    return f"{uri}?{params}" if params else uri


# The global database holds cross-project state:
#   - Users               : global accounts used for authentication
#   - Projects             : registry of all projects (for listing / lookup)
#   - UserProjectRelation  : project membership
GLOBAL_DB_NAME = os.getenv("GLOBAL_DB_NAME", "cedars_global")

# Database Postgres itself always has, used only to issue `CREATE DATABASE`
# for new projects (that statement cannot run against the DB being created).
ADMIN_DB_NAME = os.getenv("DB_ADMIN_NAME", "postgres")

# Fallback project id used when no project context is bound (maintenance scripts).
DEFAULT_PROJECT_ID = os.getenv("DEFAULT_PROJECT_ID", "default")

_global_engine = None
_admin_engine = None
_project_engines: dict = {}
_engine_lock = Lock()


def project_db_name(project_id: str) -> str:
    """Map a ``project_id`` to its dedicated Postgres database name."""
    return f"cedars_proj_{project_id}"


def get_global_engine():
    """Return the process-wide engine for the global application database."""
    global _global_engine  # pylint: disable=global-statement
    if _global_engine is None:
        _global_engine = create_engine(_build_pg_uri(GLOBAL_DB_NAME),
                                       pool_pre_ping=True, future=True)
    return _global_engine


def get_admin_engine():
    """Return the process-wide engine used only to CREATE/DROP project databases."""
    global _admin_engine  # pylint: disable=global-statement
    if _admin_engine is None:
        _admin_engine = create_engine(_build_pg_uri(ADMIN_DB_NAME),
                                      isolation_level="AUTOCOMMIT", future=True)
    return _admin_engine


def get_project_engine(project_id: str):
    """Return a cached (or newly created) engine for ``project_id``'s database."""
    if project_id not in _project_engines:
        with _engine_lock:
            if project_id not in _project_engines:
                _project_engines[project_id] = create_engine(
                    _build_pg_uri(project_db_name(project_id)),
                    pool_pre_ping=True, future=True)
    return _project_engines[project_id]


def dispose_project_engine(project_id: str) -> None:
    """Dispose and forget a project's cached engine (e.g. after termination)."""
    with _engine_lock:
        engine = _project_engines.pop(project_id, None)
    if engine is not None:
        engine.dispose()


# --- project context -------------------------------------------------------

_current_project_id = contextvars.ContextVar("cedars_current_project_id", default=None)


def set_current_project_db(project_id):
    """Bind the current context to ``project_id``; returns a reset token."""
    return _current_project_id.set(project_id)


def reset_current_project_db(token):
    """Undo a previous :func:`set_current_project_db` using its token."""
    _current_project_id.reset(token)


def get_current_project_id():
    """Return the project_id bound to the current context (or the default)."""
    return _current_project_id.get() or DEFAULT_PROJECT_ID


def get_current_project_engine():
    """Return the SQLAlchemy engine for the project bound to the current context."""
    return get_project_engine(get_current_project_id())


# --- object storage (S3 / MinIO) ------------------------------------------

def get_bucket_name():
    """Return the configured S3 bucket name, defaulting to cedars-{project_id}."""
    explicit = os.getenv("S3_BUCKET")
    if explicit:
        return explicit
    return f"cedars-{get_current_project_id()}"


def project_s3_prefix():
    """Return an S3 key prefix that isolates the current project's objects."""
    return get_current_project_id()


def _new_s3(resource=False):
    """Construct a boto3 S3 client or resource from environment credentials.

    Falls back to MINIO_ACCESS_KEY / MINIO_SECRET_KEY when the AWS_* vars are
    absent, and defaults the endpoint to http://minio:9000 in that case.
    """
    in_aws_mode = bool(os.getenv("AWS_ACCESS_KEY_ID"))
    kwargs = {
        "region_name": os.getenv("REGION", "us-east-1"),
        "aws_access_key_id": os.getenv("AWS_ACCESS_KEY_ID") or os.getenv("MINIO_ACCESS_KEY"),
        "aws_secret_access_key": os.getenv("AWS_SECRET_ACCESS_KEY") or os.getenv("MINIO_SECRET_KEY"),
    }
    # Use explicit endpoint when set; otherwise default to MinIO in self-hosted mode.
    endpoint = os.getenv("S3_ENDPOINT_URL") or (None if in_aws_mode else "http://minio:9000")
    if endpoint:
        kwargs["endpoint_url"] = endpoint
    factory = boto3.resource if resource else boto3.client
    return factory("s3", **kwargs)


def get_s3():
    """Return a boto3 S3 *client*, creating the bucket if it does not exist."""
    s3_client = _new_s3(resource=False)
    bucket_name = get_bucket_name()
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        logger.info(f"Bucket '{bucket_name}' already exists in object storage")
    except ClientError as e:
        error_code = e.response["Error"]["Code"]
        if error_code in ("404", "NoSuchBucket"):
            logger.info(f"Bucket '{bucket_name}' not found — creating it")
            s3_client.create_bucket(Bucket=bucket_name)
            logger.info(f"Bucket '{bucket_name}' created")
        else:
            logger.error(f"Error checking if bucket exists: {e}")
            raise
    return s3_client


def get_s3_resource():
    """Return a boto3 S3 *resource* (used for versioned delete operations)."""
    return _new_s3(resource=True)


class _LazyProxy:
    """Minimal lazy singleton proxy (replaces werkzeug ``LocalProxy``)."""

    def __init__(self, factory):
        self._factory = factory
        self._obj = None

    def _get(self):
        if self._obj is None:
            self._obj = self._factory()
        return self._obj

    def __getattr__(self, name):
        return getattr(self._get(), name)


# S3 handles are lazy so that importing this module never touches the network.
s3 = _LazyProxy(get_s3)
s3_resource = _LazyProxy(get_s3_resource)
